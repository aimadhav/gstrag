"""Small single-host durable queue. The sync credential can stage, never publish."""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid

from .notification_feed import COVERAGE, OfficialClient, SyncError
from .notification_sync import exclusive_run, now, run
from .store import StateError

COUNTS = ("downloaded_new_versions", "unchanged_versions", "staged_versions", "deferred_documents")


def import_notifications(settings):
    client = OfficialClient()
    try:
        return run(settings.root / "data/app/notification_sync", client=client,
                   sources=["cgst_tax", "cgst_rate"], max_pages=settings.notification_sync_max_pages,
                   since_year=settings.notification_sync_since_year,
                   max_documents=settings.notification_sync_max_documents, parse=True)
    finally:
        client.close()


class SyncJobs:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "hosted-jobs.sqlite3"
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT,
                    finished_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT, error TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_sync ON jobs((1))
                    WHERE status IN ('queued','running');
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, key):
        if not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", key):
            raise StateError(422, "invalid_idempotency_key")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM jobs WHERE request_key=?", (key,)).fetchone()
            if row:
                job_id = row["id"]
            else:
                if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone():
                    raise StateError(409, "sync_job_in_progress")
                job_id = str(uuid.uuid4())
                db.execute("INSERT INTO jobs(id,request_key,status,created_at) VALUES(?,?,'queued',?)",
                           (job_id, key, now()))
        return self.get(job_id)

    def get(self, job_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise StateError(404, "sync_job_not_found")
        # Deliberately exclude request keys, filesystem paths, source text and raw errors.
        return {k: row[k] for k in ("id", "status", "created_at", "started_at", "finished_at", "attempts", "error")} | {
            "result": json.loads(row["result_json"]) if row["result_json"] else None}

    def list(self, limit=30):
        with self.connection() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM jobs ORDER BY created_at DESC,id LIMIT ?", (limit,))]
        return [self.get(job_id) for job_id in ids]

    def recover(self):
        """Caller MUST own the lifetime worker lock before recovery or claims."""
        with self.connection() as db:
            db.execute("UPDATE jobs SET status='queued', error='interrupted_retry' WHERE status='running'")

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running', started_at=?, attempts=attempts+1, error=NULL WHERE id=?",
                       (now(), row["id"]))
        return self.get(row["id"])

    def finish(self, job_id, status, result=None, error=None):
        with self.connection() as db:
            db.execute("UPDATE jobs SET status=?, finished_at=?, result_json=?, error=? WHERE id=? AND status='running'",
                       (status, now(), json.dumps(result) if result is not None else None, error, job_id))

    def retry(self, job_id):
        with self.connection() as db:
            db.execute("UPDATE jobs SET status='queued', error='importer_busy' WHERE id=? AND status='running'", (job_id,))


class SyncWorker:
    """One thread and an OS-released SQLite owner lock; no leases or extra broker."""
    def __init__(self, jobs, runner):
        self.jobs, self.runner = jobs, runner
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.started = threading.Event()
        self.thread = None
        self.start_error = None
        self.ready = False

    def start(self):
        if self.thread is not None:
            raise RuntimeError("sync_worker_already_started")
        self.thread = threading.Thread(target=self._loop, daemon=True, name="gst-notification-sync")
        self.thread.start()
        if not self.started.wait(5):
            self.stop.set()
            raise RuntimeError("sync_worker_start_timeout")
        if self.start_error:
            raise RuntimeError(self.start_error)

    def close(self):
        self.ready = False
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _loop(self):
        try:
            # Separate from the importer/publication lock; held for this thread's lifetime.
            with exclusive_run(self.jobs.root / "hosted-worker"):
                self.jobs.recover()
                self.ready = True
                self.started.set()
                while not self.stop.is_set():
                    self.wake.clear()
                    if not self._process_one():
                        self.wake.wait(2)
        except Exception:
            # Never surface exception bodies: they may contain provider URLs/credentials.
            self.start_error = "sync_worker_unavailable"
        finally:
            self.ready = False
            self.started.set()

    def _process_one(self):
        job = self.jobs.claim()
        if not job:
            return False
        try:
            report = self.runner()
            if report.get("active_corpus_changed") is not False or report.get("published") != 0:
                raise ValueError("unsafe_sync_result")
            # Whitelist counts only. Keep detailed source/error reports on the backend.
            result = {k: int(report.get(k, 0)) for k in COUNTS}
            result.update(coverage=COVERAGE, active_corpus_changed=False, published=0,
                          error_count=len(report.get("errors", [])),
                          bounded_scan=bool(report.get("discovery", {}).get("bounded_scan", False)))
            self.jobs.finish(job["id"], "completed_with_errors" if result["error_count"] else "completed", result)
        except SyncError as exc:
            if str(exc) == "sync_already_running" and job["attempts"] < 3:
                self.jobs.retry(job["id"])
                self.stop.wait(2)
            else:
                self.jobs.finish(job["id"], "failed", error="importer_busy" if str(exc) == "sync_already_running" else "import_failed")
        except Exception:
            self.jobs.finish(job["id"], "failed", error="import_failed")
        return True
