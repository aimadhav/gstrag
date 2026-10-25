"""Bounded admin uploads -> durable private parsing -> reviewed publication.

Reuse the ingestion registry, immutable source artifacts and publication gates.
No upload, parse or review automatically indexes vectors or activates a source.
"""
from contextlib import contextmanager
from io import BytesIO
import json
import sqlite3
import threading

from .ingestion import parse_pdf, read_json
from .models import BookReview, UploadReservation
from .notification_publication import encoded, require_admin
from .notification_sync import Registry, atomic_write, digest, exclusive_run, now, stage_version
from .notifications import source_items
from .service import Corpus
from .store import StateError

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 500


def parse_upload(pdf, directory, metadata):
    """Local Docling + HybridChunker, conservative furniture filtering for books.

    No automatic outline-depth restoration or case extraction for unknown layouts.
    Admin must inspect chunk/page/heading quality; originals remain untouched.
    """
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from docling_core.types.doc import DoclingDocument
    from transformers import AutoTokenizer
    from .chunking import filter_document

    kind = metadata["source_type"]
    manifest = parse_pdf(pdf, directory, kind, False, True)
    if (manifest["converted_pdf_pages"] != list(range(1, manifest["page_count"] + 1))
            or manifest["parsed_page_count"] != manifest["page_count"]):
        raise ValueError("incomplete_full_pdf_conversion")
    original = DoclingDocument.load_from_json(directory / "docling.json")
    document, excluded = filter_document(original) if kind != "notification" else (original, [])
    tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True, fix_mistral_regex=False)
    tokenizer.model_max_length = 10**9
    chunker = HybridChunker(tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=512), merge_peers=True)
    records = []
    for index, chunk in enumerate(chunker.chunk(dl_doc=document)):
        pages = sorted({p.page_no for item in chunk.meta.doc_items for p in item.prov})
        refs = list(dict.fromkeys(item.self_ref for item in chunk.meta.doc_items))
        text = chunker.contextualize(chunk)
        if not pages or not refs or any(not 1 <= p <= manifest["page_count"] for p in pages):
            raise ValueError("missing_provenance")
        records.append({"chunk_id": f"{manifest['document_id']}:admin-hybrid-v1:{index:05d}",
            "document_id": manifest["document_id"], "source_type": kind,
            "plan_required": "pro" if kind == "firm_book" else "plus",
            "text": chunk.text, "embedding_text": text, "headings": list(chunk.meta.headings or []),
            "pages": pages, "source_refs": refs, "token_count": len(tokenizer.encode(text, add_special_tokens=False)),
            "eligible_for_retrieval": False})
    if not records:
        raise ValueError("no_searchable_content")
    return {"schema": "admin-upload-staging-v1", "source_sha256": manifest["sha256"],
            "document_id": manifest["document_id"], "page_count": manifest["page_count"],
            "candidate": metadata, "docling_sha256": digest((directory / "docling.json").read_bytes()),
            "review_status": "pending_source_metadata_review", "eligible_for_retrieval": False,
            "excluded_items": excluded, "over_token_budget": sum(r["token_count"] > 512 for r in records),
            "warnings": ["Unknown layout: check headings, reading order, tables, diagrams, completeness and original PDF pages.",
                         "No OCR or automatic case/outline/legal-precedence inference. No provider calls or publication."],
            "records": records}


def validate_pdf(body):
    """Structural check only, not malware scanning or legal/source authenticity."""
    from pypdf import PdfReader
    if not body.startswith(b"%PDF-") or b"%%EOF" not in body[-2048:]:
        raise StateError(422, "invalid_uploaded_pdf")
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted:
            raise StateError(422, "encrypted_pdf_not_supported")
        pages = len(reader.pages)
        if not 1 <= pages <= MAX_PAGES:
            raise StateError(422, "uploaded_pdf_page_limit")
        # Reject active/embedded content. Parsing is still not a security sandbox.
        def check(obj, seen):
            if hasattr(obj, "idnum"):
                key = (obj.idnum, obj.generation)
                if key in seen:
                    return
                seen.add(key); obj = obj.get_object()
            if isinstance(obj, dict):
                if any(str(k) in {"/JS", "/JavaScript", "/OpenAction", "/AA", "/EmbeddedFiles", "/Launch", "/RichMedia"} for k in obj):
                    raise StateError(422, "active_pdf_content_not_supported")
                for value in obj.values(): check(value, seen)
            elif isinstance(obj, list):
                for value in obj: check(value, seen)
        check(reader.trailer["/Root"], set())
        return pages
    except StateError:
        raise
    except Exception:
        raise StateError(422, "invalid_uploaded_pdf") from None


class Uploads:
    def __init__(self, root, publisher, parser=parse_upload):
        self.root, self.publisher, self.parser = root, publisher, parser
        self.sync_root = root / "data/app/notification_sync"
        with self.registry() as registry:
            registry.db.execute("""CREATE TABLE IF NOT EXISTS admin_uploads (
                version_id TEXT PRIMARY KEY REFERENCES versions(id), payload_sha TEXT NOT NULL,
                byte_count INTEGER NOT NULL, page_count INTEGER, actor_id TEXT NOT NULL, created_at TEXT NOT NULL)""")
            registry.db.commit()

    @contextmanager
    def registry(self):
        registry = Registry(self.sync_root)
        try: yield registry
        finally: registry.close()

    def reserve(self, body, actor):
        require_admin(actor)
        payload = body.model_dump(mode="json") if isinstance(body, UploadReservation) else UploadReservation.model_validate(body).model_dump(mode="json")
        kind, replacement = payload["source_type"], payload["replaces_document_id"]
        if kind == "notification":
            if any(payload[k] is None for k in ("series", "number", "year")):
                raise StateError(422, "notification_identity_required")
        elif any(payload[k] is not None for k in ("series", "number", "year")):
            raise StateError(422, "notification_fields_on_book")
        with exclusive_run(self.sync_root):
            corpus_path = self.root / "data/app/corpus.json"
            corpus = Corpus(self.root) if corpus_path.exists() else None
            sources = list(corpus.sources.values()) if corpus else []
            if any(s["sha256"] == payload["sha256"] and s["source_type"] != kind for s in sources):
                raise StateError(409, "source_hash_conflicting_classification")
            if any(s["sha256"] == payload["sha256"] for s in sources):
                raise StateError(409, "pdf_already_registered")
            previous = None
            if replacement:
                previous = next((s for s in sources if s["document_id"] == replacement), None)
                if not previous or previous.get("archived"):
                    raise StateError(409, "replacement_target_not_active")
                if previous["source_type"] != kind:
                    raise StateError(409, "replacement_source_type_mismatch")
                corpus.pdf_path(replacement)
            checksum = digest(encoded(payload))
            identity = "admin_upload:" + checksum
            version_id = digest((identity + ":" + payload["sha256"]).encode())
            metadata = payload | {"identity": identity, "origin": "admin_upload", "kind": "notification" if kind == "notification" else "book",
                "label": payload["title"], "subject": "Admin-uploaded PDF; identity and applicability require review",
                "language": "en", "pdf_url": "admin-upload:" + version_id,
                "replaces_sha256": previous["sha256"] if previous else None}
            with self.registry() as registry:
                conflict = registry.db.execute("SELECT 1 FROM versions WHERE sha256=? AND json_extract(metadata_json,'$.source_type') IS NOT NULL AND json_extract(metadata_json,'$.source_type')<>?",
                                               (payload["sha256"], kind)).fetchone()
                if conflict:
                    raise StateError(409, "source_hash_conflicting_classification")
                old = registry.db.execute("SELECT id FROM versions WHERE id=?", (version_id,)).fetchone()
                if not old:
                    registry.observe(metadata)
                    registry.db.execute("""INSERT INTO versions(id,identity,sha256,pdf_path,metadata_json,downloaded_from,status,created_at)
                        VALUES(?,?,?,?,?,?,'awaiting_upload',?)""", (version_id, identity, payload["sha256"],
                        "pdfs/" + payload["sha256"] + ".pdf", json.dumps(metadata), "admin_upload", now()))
                    registry.db.execute("INSERT INTO admin_uploads VALUES(?,?,?,NULL,?,?)",
                                        (version_id, checksum, payload["byte_count"], actor["id"], now()))
                    registry.db.commit()
            return self.get(version_id, actor)

    def get(self, version_id, actor):
        require_admin(actor)
        with self.registry() as registry:
            row = registry.db.execute("""SELECT v.*,u.byte_count,u.page_count,u.actor_id FROM versions v
                JOIN admin_uploads u ON v.id=u.version_id WHERE v.id=?""", (version_id,)).fetchone()
            if not row: raise StateError(404, "upload_not_found")
            data = dict(row); metadata = json.loads(data["metadata_json"])
            # Review tables are initialized by the publisher when first queried.
        with self.publisher.registry() as registry:
            review = self.publisher._review(registry, version_id)
        return {"id": data["id"], "title": metadata["title"], "source_type": metadata["source_type"],
            "sha256": data["sha256"], "stage_sha256": data["stage_sha256"], "status": data["status"],
            "error": data["error"], "byte_count": data["byte_count"], "page_count": data["page_count"],
            "replaces_document_id": metadata["replaces_document_id"], "created_at": data["created_at"],
            "revision": review["revision"] if review else 0, "review_status": review["status"] if review else None}

    def list(self, actor, limit=50, offset=0):
        require_admin(actor)
        with self.registry() as registry:
            ids = [r[0] for r in registry.db.execute("SELECT version_id FROM admin_uploads ORDER BY created_at DESC,version_id LIMIT ? OFFSET ?", (limit, offset))]
        return [self.get(version_id, actor) for version_id in ids]

    def receive(self, version_id, body, actor):
        upload = self.get(version_id, actor)
        if len(body) != upload["byte_count"] or digest(body) != upload["sha256"]:
            raise StateError(422, "upload_size_or_digest_mismatch")
        pages = validate_pdf(body)
        with exclusive_run(self.sync_root), self.registry() as registry:
            version = registry.db.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
            path = registry.path(version["pdf_path"])
            if path.exists() and digest(path.read_bytes()) != upload["sha256"]:
                raise StateError(409, "stored_pdf_integrity_failed")
            if not path.exists(): atomic_write(path, body)
            if version["status"] == "awaiting_upload":
                registry.db.execute("UPDATE versions SET status='uploaded_queued',error=NULL WHERE id=?", (version_id,))
            registry.db.execute("UPDATE admin_uploads SET page_count=? WHERE version_id=?", (pages, version_id))
            registry.db.commit()
        return self.get(version_id, actor)

    def recover(self):
        with exclusive_run(self.sync_root), self.registry() as registry:
            registry.db.execute("UPDATE versions SET status='uploaded_queued' WHERE status IN ('upload_parsing','parsing') AND id IN (SELECT version_id FROM admin_uploads)")
            registry.db.commit()

    def process_one(self):
        # Caller owns the upload worker lifetime lock; importer/publication use this same mutation lock.
        with exclusive_run(self.sync_root), self.registry() as registry:
            row = registry.db.execute("SELECT * FROM versions WHERE status='uploaded_queued' AND id IN (SELECT version_id FROM admin_uploads) ORDER BY created_at LIMIT 1").fetchone()
            if not row: return False
            version = dict(row)
            registry.db.execute("UPDATE versions SET status='upload_parsing',error=NULL WHERE id=?", (version["id"],)); registry.db.commit()
            try:
                # stage_version uses generated directories, validates source hash, then writes an ineligible stage.
                stage_version(registry, version, self.parser)
                staged = read_json(registry.path("staging/" + version["id"] + "/staged.json"))
                if any(r.get("source_type") != json.loads(version["metadata_json"])["source_type"]
                       or r.get("plan_required") != ("pro" if r.get("source_type") == "firm_book" else "plus") for r in staged["records"]):
                    raise ValueError("unsafe_stage_policy")
            except Exception:
                registry.set_version(version["id"], "upload_parse_failed", "upload_parse_failed")
            return True

    def retry(self, version_id, actor):
        self.get(version_id, actor)
        with exclusive_run(self.sync_root), self.registry() as registry:
            row = registry.db.execute("SELECT status FROM versions WHERE id=?", (version_id,)).fetchone()
            if row["status"] != "upload_parse_failed": raise StateError(409, "upload_not_retryable")
            registry.db.execute("UPDATE versions SET status='uploaded_queued',error=NULL WHERE id=?", (version_id,)); registry.db.commit()
        return self.get(version_id, actor)

    def detail(self, version_id, actor):
        upload = self.get(version_id, actor)
        with self.publisher.registry() as registry:
            _, staged, _, directory, _ = self.publisher._stage(registry, version_id)
        return {**upload, "document_id": staged["document_id"], "items": list(source_items(directory).values()),
            "draft_chunks": staged["records"], "warnings": staged.get("warnings", []),
            "excluded_items": staged.get("excluded_items", []), "over_token_budget": staged.get("over_token_budget", 0)}

    def review_book(self, version_id, body, actor):
        upload = self.get(version_id, actor)
        if upload["source_type"] == "notification": raise StateError(422, "use_notification_source_review")
        payload = body.model_dump(mode="json") if isinstance(body, BookReview) else BookReview.model_validate(body).model_dump(mode="json")
        with self.publisher.registry(mutate=True) as registry:
            version, staged, _, directory, _ = self.publisher._stage(registry, version_id)
            self.publisher._not_published(staged["document_id"])
            old = self.publisher._review(registry, version_id)
            if payload["revision"] != (old["revision"] if old else 0) or payload["stage_sha256"] != version["stage_sha256"]:
                raise StateError(409, "stale_source_review_revision_or_stage")
            records = []
            if payload["action"] == "approve":
                items = source_items(directory)
                if not staged["records"]: raise StateError(422, "empty_uploaded_source")
                for record in staged["records"]:
                    if (record.get("source_type") != upload["source_type"] or record.get("plan_required") != ("pro" if upload["source_type"] == "firm_book" else "plus")
                        or not record.get("text") or not record.get("embedding_text") or not record.get("pages")
                        or not record.get("source_refs") or any(ref not in items for ref in record["source_refs"])
                        or set(record["pages"]) != {p for ref in record["source_refs"] for p in items[ref]["pages"]}
                        or record.get("token_count", 100000) > 512):
                        raise StateError(422, "uploaded_chunk_review_failed")
                    records.append(record | {"eligible_for_retrieval": True, "variant": "admin_reviewed_upload_hybrid_v1"})
            document = {"decision": "approved" if payload["action"] == "approve" else "rejected", "payload": payload,
                        "reason": payload["reason"], "records": records, "docling_sha256": staged["docling_sha256"], "source_sha256": version["sha256"]}
            return self.publisher._save_review(registry, version_id, payload["revision"] + 1, document, version["stage_sha256"], actor)


class UploadWorker:
    def __init__(self, uploads):
        self.uploads = uploads
        self.stop, self.started, self.wake = threading.Event(), threading.Event(), threading.Event()
        self.thread = None; self.ready = False

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name="gst-pdf-uploads"); self.thread.start()
        if not self.started.wait(5) or not self.ready:
            self.stop.set(); raise RuntimeError("upload_worker_unavailable")

    def close(self):
        self.ready = False; self.stop.set(); self.wake.set()
        if self.thread: self.thread.join(timeout=2)

    def _loop(self):
        from .notification_feed import SyncError
        try:
            with exclusive_run(self.uploads.sync_root / "upload-worker"):
                recovered = False
                self.ready = True; self.started.set()
                while not self.stop.is_set():
                    self.wake.clear()
                    try:
                        if not recovered: self.uploads.recover(); recovered = True
                        if self.uploads.process_one(): continue
                    except SyncError:
                        pass  # importer/publication owns the shared mutation lock; retry later.
                    self.wake.wait(2)
        except Exception:
            pass  # Fail readiness closed; do not print raw parser/storage exception bodies.
        finally:
            self.ready = False; self.started.set()
