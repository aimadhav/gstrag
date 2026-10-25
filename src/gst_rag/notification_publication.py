"""Admin source review and explicit, verified corpus publication.

No automatic source approval, legal precedence inference, schedule, or deletion.
The operator-only index command is the ONLY provider-writing operation here.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time

from .benchmark import BM25, normalize
from .ingestion import read_json
from .models import NotificationReview
from .notification_sync import Registry, atomic_write, digest, exclusive_run, now
from .notification_feed import SyncError
from .notifications import english_date, source_items
from .service import Corpus
from .store import StateError
from .vector_store import DEFAULT_INDEX, PineconeStore, Snapshot, app_jina


SERIES = {"central_tax": "Central Tax", "central_tax_rate": "Central Tax (Rate)"}
REFERENCE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{4})\s*[-–—]?\s*Central\s+Tax(\s*\(\s*Rate\s*\))?", re.I)


def references(text):
    return {f"{'central_tax_rate' if rate else 'central_tax'}:{int(n)}/{year}"
            for n, year, rate in REFERENCE.findall(text) if int(n)}


def tokenizer_local():
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True, fix_mistral_regex=False)
    tokenizer.model_max_length = 10**9
    return tokenizer


def encoded(data):
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False).encode()


def require_admin(actor):
    if not actor or actor.get("role") != "admin" or not actor.get("active", True):
        raise StateError(403, "admin_required")


def identifier(value):
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise StateError(422, "invalid_ingestion_identifier")
    return value


class Publications:
    def __init__(self, root, tokenizer_factory=tokenizer_local):
        self.root = Path(root).resolve()
        self.sync_root = self.root / "data/app/notification_sync"
        self.tokenizer_factory = tokenizer_factory

    @contextmanager
    def registry(self, mutate=False):
        @contextmanager
        def no_lock():
            yield
        try:
            with self._registry_connection(mutate, no_lock) as registry:
                yield registry
        except SyncError:
            raise StateError(409, "ingestion_operation_conflict") from None
        except sqlite3.Error:
            raise StateError(503, "ingestion_registry_unavailable") from None

    @contextmanager
    def _registry_connection(self, mutate, no_lock):
        with exclusive_run(self.sync_root) if mutate else no_lock():
            registry = Registry(self.sync_root)
            try:
                registry.db.executescript("""
                    CREATE TABLE IF NOT EXISTS source_reviews (
                      version_id TEXT PRIMARY KEY REFERENCES versions(id), revision INTEGER NOT NULL,
                      status TEXT NOT NULL, actor_id TEXT NOT NULL, saved_at TEXT NOT NULL,
                      stage_sha256 TEXT NOT NULL, review_json TEXT NOT NULL, review_sha256 TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS source_review_events (
                      id INTEGER PRIMARY KEY,version_id TEXT NOT NULL,revision INTEGER NOT NULL,
                      action TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,review_sha256 TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS publications (
                      id TEXT PRIMARY KEY,base_sha256 TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,
                      review_refs TEXT NOT NULL,state TEXT NOT NULL,actor_id TEXT NOT NULL,
                      created_at TEXT NOT NULL,mode TEXT,index_name TEXT,embeddings_sha256 TEXT,
                      verified_counts TEXT,activated_at TEXT,activated_by TEXT,error TEXT);
                """)
                yield registry
            finally:
                registry.close()

    def _stage(self, registry, version_id):
        version = registry.db.execute("SELECT * FROM versions WHERE id=?", (identifier(version_id),)).fetchone()
        if not version:
            raise StateError(404, "ingestion_version_not_found")
        version = dict(version)
        if version["status"] != "pending_source_metadata_review" or not version["stage_path"]:
            raise StateError(409, "source_not_staged")
        pdf = registry.path(version["pdf_path"])
        stage_path = registry.path(version["stage_path"])
        try:
            if digest(pdf.read_bytes()) != version["sha256"] or digest(stage_path.read_bytes()) != version["stage_sha256"]:
                raise StateError(409, "staged_source_changed")
            staged = read_json(stage_path)
            directory = stage_path.parent
            manifest = read_json(directory / "manifest.json")
            if (digest((directory / "docling.json").read_bytes()) != staged["docling_sha256"]
                    or manifest["sha256"] != version["sha256"] or staged["source_sha256"] != version["sha256"]
                    or staged["document_id"] != manifest["document_id"] or staged["eligible_for_retrieval"] is not False):
                raise StateError(409, "staged_source_changed")
            metadata = json.loads(version["metadata_json"])
            expected = metadata.get("source_type", "notification")
            if (expected not in {"icai_book", "firm_book", "notification"} or manifest["source_type"] != expected
                    or manifest["plan_required"] != ("pro" if expected == "firm_book" else "plus")
                    or (expected != "notification" and metadata.get("origin") != "admin_upload")):
                raise StateError(409, "staged_source_policy_mismatch")
        except (OSError, KeyError, ValueError):
            raise StateError(409, "staged_source_unavailable") from None
        return version, staged, manifest, directory, pdf

    @staticmethod
    def _review(registry, version_id):
        row = registry.db.execute("SELECT * FROM source_reviews WHERE version_id=?", (version_id,)).fetchone()
        return dict(row) if row else None

    def list_sources(self, actor, limit=50, offset=0):
        require_admin(actor)
        with self.registry() as registry:
            rows = registry.db.execute("""SELECT v.id,v.identity,v.status,v.sha256,v.stage_sha256,v.error,
                r.revision,r.status AS review_status FROM versions v LEFT JOIN source_reviews r ON v.id=r.version_id
                WHERE COALESCE(json_extract(v.metadata_json,'$.source_type'),'notification')='notification'
                ORDER BY v.created_at DESC,v.id LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
            return [dict(row) | {"revision": row["revision"] or 0} for row in rows]

    def detail(self, version_id, actor):
        require_admin(actor)
        with self.registry() as registry:
            version, staged, manifest, directory, _ = self._stage(registry, version_id)
            review = self._review(registry, version_id)
            return {"version_id": version_id, "candidate": json.loads(version["metadata_json"]),
                    "source_sha256": version["sha256"], "stage_sha256": version["stage_sha256"],
                    "revision": review["revision"] if review else 0,
                    "review_status": review["status"] if review else "pending",
                    "review": json.loads(review["review_json"]) if review else None,
                    "page_count": manifest["page_count"], "document_id": staged["document_id"],
                    "items": list(source_items(directory).values()), "draft_chunks": staged["records"],
                    "pdf_url": f"/admin/ingestion/notifications/{version_id}/pdf"}

    def pdf(self, version_id, actor):
        require_admin(actor)
        with self.registry() as registry:
            return self._stage(registry, version_id)[4]

    def _records(self, staged, manifest, directory, review, reviewer_id):
        candidate = staged["candidate"]
        if candidate["kind"] != "notification" or candidate["series"] not in SERIES or not candidate.get("number"):
            raise StateError(422, "corrigendum_or_series_requires_separate_policy")
        if review["effective_from"] < review["issued_on"]:
            raise StateError(422, "retrospective_effect_requires_separate_policy")
        items = source_items(directory)
        anchors = [a for a in review["anchors"].values() if a]
        for anchor in anchors:
            item = items.get(anchor["source_ref"])
            if (not item or anchor["pages"] != item["pages"] or normalize(anchor["quote"]) not in normalize(item["text"])
                    or not item["pages"] or any(p < 1 or p > manifest["page_count"] for p in item["pages"])):
                raise StateError(422, "review_anchor_not_on_claimed_source_page")
        key = f"{candidate['series']}:{candidate['number']}/{candidate['year']}"
        if key not in references(review["anchors"]["identity"]["quote"]):
            raise StateError(422, "notification_identity_not_supported")
        for field in ["issued_on", "effective_from"]:
            try:
                supported_date = english_date(review["anchors"][field]["quote"])
            except ValueError:
                raise StateError(422, "review_date_evidence_ambiguous") from None
            if supported_date != review[field]:
                raise StateError(422, "review_date_not_supported")
        if review["amends"]:
            anchor = review["anchors"]["amends"]
            if not anchor or review["amends"] not in references(anchor["quote"]) or review["amends"] == key:
                raise StateError(422, "amendment_target_not_supported")
        elif review["anchors"]["amends"]:
            raise StateError(422, "amendment_anchor_without_target")
        tokenizer, records, seen = self.tokenizer_factory(), [], set()
        review_hash = digest(encoded(review))
        for clause in review["clauses"]:
            if clause["id"] in seen or len(set(clause["source_refs"])) != len(clause["source_refs"]):
                raise StateError(422, "duplicate_clause_or_source_reference")
            seen.add(clause["id"])
            if any(ref not in items for ref in clause["source_refs"]):
                raise StateError(422, "unknown_clause_source_reference")
            if any(not items[ref]["pages"] or any(type(p) is not int or not 1 <= p <= manifest["page_count"]
                                                  for p in items[ref]["pages"]) for ref in clause["source_refs"]):
                raise StateError(422, "clause_source_missing_page_provenance")
            spans = list(anchors) + [{k: items[ref][k] for k in ["source_ref", "pages"]} | {"quote": items[ref]["text"]}
                                     for ref in clause["source_refs"]]
            text = "\n\n".join(dict.fromkeys(span["quote"] for span in spans))
            heading = f"Notification {candidate['number']}/{candidate['year']} {SERIES[candidate['series']]}"
            embedding = f"{heading} | issued {review['issued_on']} | effective {review['effective_from']}\n{clause['subject']}\n{text}"
            count = len(tokenizer.encode(embedding, add_special_tokens=False))
            if count > 512:
                raise StateError(422, "complete_reviewed_clause_exceeds_512_tokens")
            records.append({"chunk_id": f"{manifest['document_id']}:publication-v1:{review_hash[:16]}:{clause['id']}",
                "document_id": manifest["document_id"], "source_type": "notification", "plan_required": "plus",
                "variant": "reviewed_notification_publication_v1", "text": text, "embedding_text": embedding,
                "headings": [heading, clause["subject"]], "token_count": count,
                "pages": sorted({p for span in spans for p in span["pages"]}),
                "source_refs": list(dict.fromkeys(span["source_ref"] for span in spans)), "evidence_spans": spans,
                "notification": {"key": key, "issued_on": review["issued_on"], "effective_from": review["effective_from"],
                    "effective_to": None, "amends": review["amends"], "topic_id": clause["topic_id"],
                    "provisions": clause["provisions"], "operative_change": clause["operative_change"],
                    "conditions": "Full selected source items retained; admin attests clause completeness",
                    "exceptions": "Selected clauses only; no global absence-of-exceptions claim",
                    "chain_complete": False, "supersession_status": "not_established", "rate_scope": "cgst_only",
                    "review_status": "admin_source_reviewed_not_answer_approved", "source_url": candidate["pdf_url"],
                    "reviewer_id": reviewer_id, "review_sha256": review_hash}})
        return records

    def review(self, version_id, body, actor):
        require_admin(actor)
        payload = body.model_dump(mode="json") if isinstance(body, NotificationReview) else NotificationReview.model_validate(body).model_dump(mode="json")
        with self.registry(mutate=True) as registry:
            version, staged, manifest, directory, _ = self._stage(registry, version_id)
            if manifest["source_type"] != "notification":
                raise StateError(422, "use_book_source_review")
            self._not_published(staged["document_id"])
            old = self._review(registry, version_id)
            if payload["revision"] != (old["revision"] if old else 0):
                raise StateError(409, "stale_source_review_revision")
            if payload["stage_sha256"] != version["stage_sha256"]:
                raise StateError(409, "stale_stage_digest")
            records = self._records(staged, manifest, directory, payload, actor["id"])
            document = {"decision": "approved", "payload": payload, "records": records,
                        "docling_sha256": staged["docling_sha256"], "source_sha256": version["sha256"]}
            return self._save_review(registry, version_id, (old["revision"] if old else 0) + 1, document,
                                     version["stage_sha256"], actor)

    def reject(self, version_id, body, actor):
        require_admin(actor)
        with self.registry(mutate=True) as registry:
            version, staged, _, _, _ = self._stage(registry, version_id)
            self._not_published(staged["document_id"])
            old = self._review(registry, version_id)
            if body.revision != (old["revision"] if old else 0) or body.stage_sha256 != version["stage_sha256"]:
                raise StateError(409, "stale_source_review_revision_or_stage")
            return self._save_review(registry, version_id, body.revision + 1,
                                     {"decision": "rejected", "reason": body.reason}, version["stage_sha256"], actor)

    def _not_published(self, document_id):
        path = self.root / "data/app/corpus.json"
        if path.exists():
            try:
                bundle = read_json(path)
                if any(r["document_id"] == document_id for r in bundle["sources"]):
                    raise StateError(409, "active_source_review_frozen_requires_revision_policy")
            except (OSError, KeyError, ValueError):
                raise StateError(503, "active_corpus_unavailable") from None

    @staticmethod
    def _save_review(registry, version_id, revision, document, stage_sha, actor):
        checksum, status = digest(encoded(document)), document["decision"]
        registry.db.execute("""INSERT INTO source_reviews VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(version_id) DO UPDATE SET
            revision=excluded.revision,status=excluded.status,actor_id=excluded.actor_id,saved_at=excluded.saved_at,
            stage_sha256=excluded.stage_sha256,review_json=excluded.review_json,review_sha256=excluded.review_sha256""",
            (version_id, revision, status, actor["id"], now(), stage_sha, json.dumps(document), checksum))
        registry.db.execute("INSERT INTO source_review_events(version_id,revision,action,actor_id,created_at,review_sha256) VALUES(?,?,?,?,?,?)",
                            (version_id, revision, status, actor["id"], now(), checksum))
        registry.db.commit()
        return {"version_id": version_id, "revision": revision, "status": status, "review_sha256": checksum,
                "actor_id": actor["id"], "answer_approval_performed": False}

    def _approved(self, registry, version_id, expected_review_sha=None):
        version, staged, manifest, directory, pdf = self._stage(registry, version_id)
        review = self._review(registry, version_id)
        if (not review or review["status"] != "approved" or review["stage_sha256"] != version["stage_sha256"]
                or (expected_review_sha and review["review_sha256"] != expected_review_sha)):
            raise StateError(409, "source_review_missing_or_changed")
        document = json.loads(review["review_json"])
        if (digest(encoded(document)) != review["review_sha256"] or document["docling_sha256"] != staged["docling_sha256"]
                or document["source_sha256"] != version["sha256"]):
            raise StateError(409, "approved_review_integrity_failed")
        return version, staged, manifest, pdf, document["records"], review["review_sha256"]

    def _folder(self, publication_id):
        return self.root / "data/app/publications" / identifier(publication_id)

    def _publication(self, registry, publication_id):
        row = registry.db.execute("SELECT * FROM publications WHERE id=?", (identifier(publication_id),)).fetchone()
        if not row:
            raise StateError(404, "publication_not_found")
        row = dict(row)
        path = self._folder(publication_id) / "corpus.json"
        try:
            raw = path.read_bytes()
            if digest(raw) != row["snapshot_sha256"]:
                raise StateError(409, "publication_snapshot_changed")
            if digest((path.parent / "base.json").read_bytes()) != row["base_sha256"]:
                raise StateError(409, "publication_backup_changed")
            bundle = json.loads(raw)
            if Snapshot(bundle).corpus_id != publication_id:
                raise StateError(409, "publication_snapshot_changed")
        except (OSError, KeyError, ValueError):
            raise StateError(409, "publication_snapshot_unavailable") from None
        return row, bundle

    def active(self, actor):
        require_admin(actor)
        raw = (self.root / "data/app/corpus.json").read_bytes()
        bundle = json.loads(raw)
        return {"base_sha256": digest(raw), "corpus_id": Snapshot(bundle).corpus_id,
                "records": len(bundle["records"]), "sources": len(bundle["sources"])}

    def prepare(self, version_ids, base_sha256, actor):
        require_admin(actor)
        if not version_ids or len(version_ids) > 10 or len(set(version_ids)) != len(version_ids):
            raise StateError(422, "invalid_publication_versions")
        with self.registry(mutate=True) as registry:
            raw = (self.root / "data/app/corpus.json").read_bytes()
            if digest(raw) != base_sha256:
                raise StateError(409, "active_corpus_changed")
            bundle = json.loads(raw)
            self._validate_bundle(bundle)
            replaced = set()
            refs = {}
            for version_id in sorted(version_ids):
                version, staged, manifest, pdf, records, review_sha = self._approved(registry, version_id)
                metadata = json.loads(version["metadata_json"])
                replacement = metadata.get("replaces_document_id")
                if replacement:
                    target = next((s for s in bundle["sources"] if s["document_id"] == replacement), None)
                    if (replacement in replaced or not target or target.get("archived")
                            or target["sha256"] != metadata.get("replaces_sha256")
                            or target["source_type"] != manifest["source_type"]):
                        raise StateError(409, "replacement_target_changed")
                    if manifest["source_type"] == "notification":
                        old_keys = {r["notification"]["key"] for r in bundle["records"] if r["document_id"] == replacement}
                        if old_keys != {r["notification"]["key"] for r in records}:
                            raise StateError(409, "replacement_notification_identity_changed")
                    bundle["records"] = [r for r in bundle["records"] if r["document_id"] != replacement]
                    target.update(archived=True, replaced_by=manifest["document_id"])
                    replaced.add(replacement)
                keys = {r["notification"]["key"] for r in bundle["records"] if r["source_type"] == "notification"}
                if any(r["source_type"] == "notification" and r["notification"]["key"] in keys for r in records):
                    raise StateError(409, "notification_already_present_requires_revision_policy")
                if any(source["document_id"] == manifest["document_id"] for source in bundle["sources"]):
                    raise StateError(409, "document_identity_already_registered")
                folder = "notifications" if manifest["source_type"] == "notification" else "books"
                target = self.root / "data/sources" / folder / (version["sha256"] + ".pdf")
                if target.exists() and digest(target.read_bytes()) != version["sha256"]:
                    raise StateError(409, "registered_pdf_integrity_failed")
                if not target.exists():
                    atomic_write(target, pdf.read_bytes())
                bundle["sources"].append({"document_id": manifest["document_id"], "source_type": manifest["source_type"],
                    "name": staged["candidate"]["label"], "page_count": manifest["page_count"], "sha256": version["sha256"],
                    "pdf_path": target.relative_to(self.root).as_posix()})
                bundle["records"].extend(records)
                refs[version_id] = review_sha
            bundle["links"] = candidate_links(bundle["records"])
            bundle["version"] = "app-reviewed-notification-publication-v1"
            self._validate_bundle(bundle)
            publication_id = Snapshot(bundle).corpus_id
            folder = self._folder(publication_id)
            body = encoded(bundle)
            existing = registry.db.execute("SELECT * FROM publications WHERE id=?", (publication_id,)).fetchone()
            if existing:
                self._publication(registry, publication_id)
                return dict(existing)
            atomic_write(folder / "base.json", raw)
            atomic_write(folder / "corpus.json", body)
            registry.db.execute("""INSERT INTO publications(id,base_sha256,snapshot_sha256,review_refs,state,actor_id,created_at)
                VALUES(?,?,?,?,'prepared',?,?)""", (publication_id, base_sha256, digest(body), json.dumps(refs), actor["id"], now()))
            registry.db.commit()
            return dict(registry.db.execute("SELECT * FROM publications WHERE id=?", (publication_id,)).fetchone())

    def _validate_bundle(self, bundle):
        corpus = Corpus(self.root, bundle=bundle)
        Snapshot(bundle)
        for document_id in corpus.sources:
            corpus.pdf_path(document_id)
        for record in corpus.records:
            pages = record.get("pages", [])
            if (not pages or any(type(p) is not int or not 1 <= p <= corpus.sources[record["document_id"]]["page_count"] for p in pages)
                    or record.get("eligible_for_retrieval") is False):
                raise StateError(409, "invalid_published_source_provenance")

    def _fresh_reviews(self, registry, row):
        for version_id, review_sha in json.loads(row["review_refs"]).items():
            self._approved(registry, version_id, review_sha)

    def index(self, publication_id, mode, index_name=DEFAULT_INDEX, store_factory=PineconeStore, jina_factory=app_jina):
        """Trusted local-operator command, not an HTTP route. No automatic creation."""
        if mode not in {"bm25", "jina", "pinecone"}:
            raise StateError(422, "invalid_publication_mode")
        with self.registry(mutate=True) as registry:
            row, bundle = self._publication(registry, publication_id)
            if row["state"] == "active":
                raise StateError(409, "publication_already_active")
            self._fresh_reviews(registry, row)
            self._validate_bundle(bundle)
            if digest((self.root / "data/app/corpus.json").read_bytes()) != row["base_sha256"]:
                raise StateError(409, "active_corpus_changed")
            try:
                snapshot = Snapshot(bundle)
                embeddings, embedding_sha = None, None
                counts = {kind: sum(r["source_type"] == kind for r in bundle["records"]) for kind in ["icai_book", "firm_book", "notification"]}
                if mode == "bm25":
                    BM25(bundle["records"])
                else:
                    jina = jina_factory(self.root)
                    array = jina.encode([r["embedding_text"] for r in snapshot.records], "retrieval.passage")
                    embeddings = [PineconeStore.vector(vector) for vector in array]
                    if len(embeddings) != len(snapshot.records):
                        raise StateError(409, "publication_embedding_count_mismatch")
                    raw = encoded(embeddings)
                    atomic_write(self._folder(publication_id) / "embeddings.json", raw)
                    embedding_sha = digest(raw)
                    if mode == "pinecone":
                        remote = store_factory(snapshot, index_name)
                        remote.connect()
                        remote.upsert(embeddings)
                        for attempt in range(6):
                            try:
                                counts = remote.verify_records(embeddings)
                                break
                            except ValueError as exc:
                                if "not yet visible" not in str(exc) or attempt == 5:
                                    raise
                                time.sleep(2)
                registry.db.execute("""UPDATE publications SET state='verified',mode=?,index_name=?,embeddings_sha256=?,
                    verified_counts=?,error=NULL WHERE id=?""", (mode, index_name if mode == "pinecone" else None,
                                                              embedding_sha, json.dumps(counts), publication_id))
                registry.db.commit()
            except Exception:
                registry.db.execute("UPDATE publications SET state='verification_failed',error='snapshot_verification_failed' WHERE id=?", (publication_id,))
                registry.db.commit()
                raise StateError(409, "snapshot_verification_failed") from None
            return {"publication_id": publication_id, "state": "verified", "mode": mode,
                    "verified_counts": counts, "active_corpus_changed": False}

    def activate(self, publication_id, base_sha256, actor, mode, index_name=DEFAULT_INDEX, store_factory=PineconeStore):
        require_admin(actor)
        with self.registry(mutate=True) as registry:
            row, bundle = self._publication(registry, publication_id)
            if row["state"] not in {"verified", "active"} or row["mode"] != mode or (mode == "pinecone" and row["index_name"] != index_name):
                raise StateError(409, "publication_not_verified_for_current_retriever")
            if row["base_sha256"] != base_sha256:
                raise StateError(409, "publication_base_digest_mismatch")
            self._fresh_reviews(registry, row)
            self._validate_bundle(bundle)
            active = self.root / "data/app/corpus.json"
            current = digest(active.read_bytes())
            if current not in {base_sha256, row["snapshot_sha256"]}:
                raise StateError(409, "active_corpus_changed")
            try:
                if mode != "bm25":
                    path = self._folder(publication_id) / "embeddings.json"
                    raw = path.read_bytes()
                    if digest(raw) != row["embeddings_sha256"]:
                        raise ValueError("changed embeddings")
                    embeddings = [PineconeStore.vector(v) for v in json.loads(raw)]
                    if len(embeddings) != len(bundle["records"]):
                        raise ValueError("embedding count")
                    if mode == "pinecone":
                        remote = store_factory(Snapshot(bundle), index_name)
                        remote.connect()
                        remote.verify_records(embeddings)
            except Exception:
                raise StateError(409, "activation_verification_failed") from None
            # Recheck immediately before replacing; all app publication commands
            # share this lock. Arbitrary external file edits remain unsupported.
            if digest(active.read_bytes()) != current:
                raise StateError(409, "active_corpus_changed")
            if current != row["snapshot_sha256"]:
                # Publish the exact in-memory bundle we verified, not a second
                # potentially changed read of the candidate file.
                body = encoded(bundle)
                if digest(body) != row["snapshot_sha256"]:
                    raise StateError(409, "publication_serialization_mismatch")
                atomic_write(active, body)
            registry.db.execute("UPDATE publications SET state='superseded' WHERE state='active' AND id<>?", (publication_id,))
            registry.db.execute("UPDATE publications SET state='active',activated_at=?,activated_by=? WHERE id=?", (now(), actor["id"], publication_id))
            registry.db.commit()
            return {"publication_id": publication_id, "state": "active", "records": len(bundle["records"]),
                    "restart_required": False, "answer_approval_performed": False}

    def list_publications(self, actor):
        require_admin(actor)
        with self.registry() as registry:
            return [dict(r) for r in registry.db.execute("SELECT id,state,mode,index_name,base_sha256,actor_id,created_at,activated_at,activated_by,error FROM publications ORDER BY created_at DESC LIMIT 50")]


def candidate_links(records):
    by_key = {r["notification"]["key"]: r["document_id"] for r in records if r["source_type"] == "notification"}
    return [{"book_document_id": book["document_id"], "book_chunk_id": book["chunk_id"], "book_source_type": book["source_type"],
             "notification_key": key, "notification_document_id": by_key[key],
             "status": "candidate_pending_admin_review", "basis": "explicit_number_and_series_reference"}
            for book in records if book["source_type"] in {"icai_book", "firm_book"}
            for key in sorted(references(book["text"]) & set(by_key))]


def main(argv=None):
    """Index only after authenticated source review and candidate preparation.

    Local operator privileges are trusted. Dry run by default; --apply enables
    provider calls/writes. There is deliberately no source-approval CLI bypass.
    """
    import argparse
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="Verify/index a prepared snapshot; no active corpus replacement")
    index.add_argument("publication_id")
    index.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    index.add_argument("--mode", required=True, choices=["bm25", "jina", "pinecone"])
    index.add_argument("--index-name")
    index.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        publisher = Publications(args.root)
        if not args.apply:
            with publisher.registry() as registry:
                row, bundle = publisher._publication(registry, args.publication_id)
                publisher._fresh_reviews(registry, row)
                publisher._validate_bundle(bundle)
                result = {"publication_id": args.publication_id, "mode": args.mode,
                          "records_to_verify": len(bundle["records"]), "dry_run": True,
                          "provider_calls_made": False, "active_corpus_changed": False}
        else:
            if args.mode != "bm25":
                from dotenv import load_dotenv
                load_dotenv(args.root / ".env", override=False)
            result = publisher.index(args.publication_id, args.mode, args.index_name or os.environ.get("PINECONE_INDEX_NAME", DEFAULT_INDEX))
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": exc.code if isinstance(exc, StateError) else "publication_operation_failed",
                          "provider_details_omitted": True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
