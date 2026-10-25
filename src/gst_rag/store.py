"""Small SQLite state machine. No ORM, external broker, or public draft fields."""

from contextlib import contextmanager
import json
import sqlite3
import time
from uuid import uuid4


class StateError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


class Store:
    retention_seconds = 30 * 24 * 60 * 60

    def __init__(self, path, clock=time.time):
        self.path, self.clock = path, clock
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','admin')),
                    plan TEXT NOT NULL CHECK(plan IN ('plus','pro')), active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queries (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    conversation_id TEXT NOT NULL, parent_query_id TEXT REFERENCES queries(id) ON DELETE SET NULL,
                    question TEXT NOT NULL, as_of TEXT, topic_ids TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','processing','pending_review','clarification_required','approved','refused','expired')),
                    revision INTEGER NOT NULL DEFAULT 0, plan_at_retrieval TEXT,
                    private_packet TEXT, draft_text TEXT, answer_text TEXT, citations TEXT NOT NULL DEFAULT '[]',
                    approval_kind TEXT, public_message TEXT, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, approved_at REAL, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY, query_id TEXT NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
                    actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
                    created_at REAL NOT NULL, details TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS queries_owner ON queries(user_id, created_at);
                CREATE INDEX IF NOT EXISTS queries_queue ON queries(status, created_at);
                CREATE INDEX IF NOT EXISTS queries_expiry ON queries(expires_at);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def user(self, user_id=None, username=None):
        with self.connection() as db:
            row = db.execute("SELECT * FROM users WHERE id=?" if user_id else "SELECT * FROM users WHERE username=?",
                             (user_id or username,)).fetchone()
            return dict(row) if row else None

    def users(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,username,role,plan FROM users ORDER BY created_at,id LIMIT 100")]

    def create_user(self, username, password_hash, plan="plus", role="user", bootstrap=False):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if bootstrap and db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
                raise StateError(409, "admin_already_bootstrapped")
            user_id = str(uuid4())
            try:
                db.execute("INSERT INTO users(id,username,password_hash,role,plan,created_at) VALUES(?,?,?,?,?,?)",
                           (user_id, username, password_hash, role, plan, self.clock()))
            except sqlite3.IntegrityError as exc:
                raise StateError(409, "username_already_exists") from exc
        return self.user(user_id=user_id)

    def set_plan(self, user_id, plan):
        with self.connection() as db:
            if not db.execute("UPDATE users SET plan=? WHERE id=?", (plan, user_id)).rowcount:
                raise StateError(404, "user_not_found")
        return self.user(user_id=user_id)

    def enqueue(self, user_id, question, as_of, topics, parent_id=None):
        now, query_id = self.clock(), str(uuid4())
        with self.connection() as db:
            parent = None
            if parent_id:
                parent = db.execute("SELECT * FROM queries WHERE id=? AND user_id=?", (parent_id, user_id)).fetchone()
                self._live(parent)
            db.execute("""INSERT INTO queries(id,user_id,conversation_id,parent_query_id,question,as_of,topic_ids,status,
                       created_at,updated_at,expires_at) VALUES(?,?,?,?,?,?,?,'queued',?,?,?)""",
                       (query_id, user_id, parent["conversation_id"] if parent else str(uuid4()), parent_id,
                        question, as_of, json.dumps(topics), now, now, now + self.retention_seconds))
        return self.query(query_id, user_id)

    def _live(self, row):
        if row is None:
            raise StateError(404, "query_not_found")
        if row["expires_at"] <= self.clock():
            raise StateError(410, "query_expired")

    def query(self, query_id, user_id=None):
        with self.connection() as db:
            row = db.execute("SELECT * FROM queries WHERE id=?" + (" AND user_id=?" if user_id else ""),
                             (query_id, user_id) if user_id else (query_id,)).fetchone()
            self._live(row)
            return dict(row)

    def queries(self, user_id=None, conversation_id=None, review_only=False, limit=50, offset=0):
        terms, args = ["expires_at> ?"], [self.clock()]
        if user_id:
            terms.append("user_id=?")
            args.append(user_id)
        if conversation_id:
            terms.append("conversation_id=?")
            args.append(conversation_id)
        if review_only:
            terms.append("status='pending_review'")
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM queries WHERE " + " AND ".join(terms)
                    + " ORDER BY created_at DESC, id LIMIT ? OFFSET ?", (*args, limit, offset))]

    def recover_processing(self):
        # Single-process demo only; do not run several independent worker owners.
        with self.connection() as db:
            return db.execute("UPDATE queries SET status='queued', revision=revision+1, private_packet=NULL, draft_text=NULL WHERE status='processing'").rowcount

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT q.*,u.plan AS current_plan FROM queries q JOIN users u ON u.id=q.user_id
                WHERE q.status='queued' AND q.expires_at>? AND u.active=1 ORDER BY q.created_at,q.id LIMIT 1""", (self.clock(),)).fetchone()
            if not row:
                return None
            db.execute("UPDATE queries SET status='processing',plan_at_retrieval=?,revision=revision+1,updated_at=? WHERE id=?",
                       (row["current_plan"], self.clock(), row["id"]))
            return {**dict(row), "status": "processing", "plan_at_retrieval": row["current_plan"], "revision": row["revision"] + 1}

    def job_current(self, job):
        """Recheck access before an optional external generation call."""
        with self.connection() as db:
            row = db.execute("""SELECT q.*,u.plan AS current_plan,u.active FROM queries q
                JOIN users u ON u.id=q.user_id WHERE q.id=?""", (job["id"],)).fetchone()
            return bool(row and row["status"] == "processing" and row["revision"] == job["revision"]
                        and row["expires_at"] > self.clock() and row["active"]
                        and row["current_plan"] == job["plan_at_retrieval"])

    def finish(self, job, packet, draft_text=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT q.*,u.plan AS current_plan,u.active FROM queries q JOIN users u ON u.id=q.user_id WHERE q.id=?", (job["id"],)).fetchone()
            if not row or row["status"] != "processing" or row["revision"] != job["revision"] or row["expires_at"] <= self.clock():
                return False
            if row["current_plan"] != job["plan_at_retrieval"] or not row["active"]:
                db.execute("UPDATE queries SET status='queued',plan_at_retrieval=NULL,private_packet=NULL,draft_text=NULL,revision=revision+1 WHERE id=?", (job["id"],))
                return False
            status = "clarification_required" if packet["status"] == "clarification_required" else "pending_review"
            db.execute("UPDATE queries SET status=?,private_packet=?,draft_text=?,public_message=?,revision=revision+1,updated_at=? WHERE id=?",
                       (status, json.dumps(packet), draft_text, packet.get("public_message"), self.clock(), job["id"]))
            return True

    def _review_row(self, db, query_id, revision):
        row = db.execute("SELECT q.*,u.plan AS current_plan FROM queries q JOIN users u ON u.id=q.user_id WHERE q.id=?", (query_id,)).fetchone()
        self._live(row)
        if row["revision"] != revision or row["status"] != "pending_review":
            raise StateError(409, "review_state_or_revision_changed")
        return row

    def draft(self, query_id, revision, text, actor_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._review_row(db, query_id, revision)
            db.execute("UPDATE queries SET draft_text=?,revision=revision+1,updated_at=? WHERE id=?", (text, self.clock(), query_id))
            self._event(db, query_id, actor_id, "draft_saved", {})
        return self.query(query_id)

    def _event(self, db, query_id, actor_id, action, details):
        db.execute("INSERT INTO review_events(query_id,actor_id,action,created_at,details) VALUES(?,?,?,?,?)",
                   (query_id, actor_id, action, self.clock(), json.dumps(details)))

    def decide(self, query_id, revision, action, text, citation_ids, actor_id):
        from .benchmark import allowed
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._review_row(db, query_id, revision)
            citations, answer, message = [], None, None
            if action in {"approve", "edit_and_approve"}:
                if row["current_plan"] != row["plan_at_retrieval"]:
                    raise StateError(409, "access_changed_reprocess_required")
                answer = row["draft_text"] if action == "approve" else text
                if not answer or not citation_ids:
                    raise StateError(422, "approval_requires_answer_and_citations")
                packet = json.loads(row["private_packet"] or "{}")
                available = {c["citation_id"]: c for c in packet.get("citations", [])}
                for key in dict.fromkeys(citation_ids):
                    source = available.get(key)
                    if source is None or not allowed(source, row["current_plan"]):
                        raise StateError(422, "citation_not_in_permitted_query_evidence")
                    citations.append({k: source[k] for k in ["citation_id", "source_name", "source_type", "pages"]})
                import re
                if not set(re.findall(r"\[(S[1-9][0-9]*)\]", answer)) <= set(citation_ids):
                    raise StateError(422, "inline_citations_must_be_in_approval_selection")
                validate_public_text(answer)
                status = "approved"
            elif action in {"refuse", "request_clarification"}:
                if not text:
                    raise StateError(422, "decision_requires_public_message")
                validate_public_text(text)
                message = text
                status = "refused" if action == "refuse" else "clarification_required"
            else:
                raise StateError(422, "unknown_review_action")
            now = self.clock()
            db.execute("""UPDATE queries SET status=?,answer_text=?,citations=?,approval_kind=?,public_message=?,approved_at=?,
                       expires_at=?,revision=revision+1,updated_at=? WHERE id=?""",
                       (status, answer, json.dumps(citations), action, message, now if status == "approved" else None,
                        now + self.retention_seconds, now, query_id))
            self._event(db, query_id, actor_id, action, {"citation_ids": list(dict.fromkeys(citation_ids))})
        return self.query(query_id)

    def requeue(self, query_id, revision, actor_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM queries WHERE id=?", (query_id,)).fetchone()
            self._live(row)
            if row["revision"] != revision or row["status"] not in {"pending_review", "clarification_required"}:
                raise StateError(409, "query_cannot_be_reprocessed")
            db.execute("""UPDATE queries SET status='queued',private_packet=NULL,draft_text=NULL,plan_at_retrieval=NULL,
                public_message=NULL,revision=revision+1,updated_at=? WHERE id=?""", (self.clock(), query_id))
            self._event(db, query_id, actor_id, "requeued", {})
        return self.query(query_id)

    def purge(self, apply=False):
        with self.connection() as db:
            count = db.execute("SELECT count(*) FROM queries WHERE expires_at<=?", (self.clock(),)).fetchone()[0]
            if apply:
                db.execute("DELETE FROM queries WHERE expires_at<=?", (self.clock(),))
            return count


def validate_public_text(text):
    import re
    # Plain-text answers only in this demo. PDF URLs belong to admin endpoints.
    if re.search(r"https?://|file://|/admin/|\]\(", text, re.I):
        raise StateError(422, "public_answer_must_not_contain_links")
