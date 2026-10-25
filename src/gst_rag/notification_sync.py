"""One-shot official-notification discovery/download/Docling staging.

Staged sources NEVER mutate corpus.json, experiments, Pinecone or public answers.
Hosted jobs and reviewed publication live in separate modules; this command only stages.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .notification_feed import COVERAGE, OfficialClient, SOURCES, SyncError, discover


DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data/app/notification_sync"


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive_run(root):
    """OS-managed SQLite lock releases after a crash; no expiring lease to race."""
    root.mkdir(parents=True, exist_ok=True)
    lock = sqlite3.connect(root / "run-lock.sqlite3", timeout=0)
    try:
        try:
            lock.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise SyncError("sync_already_running") from exc
        yield
    finally:
        lock.rollback()
        lock.close()


class Registry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "registry.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, mode TEXT NOT NULL, started_at TEXT NOT NULL,
              finished_at TEXT, status TEXT NOT NULL, report_json TEXT);
            CREATE TABLE IF NOT EXISTS candidates (
              identity TEXT PRIMARY KEY, metadata_json TEXT NOT NULL,
              first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
              last_checked TEXT, last_error TEXT);
            CREATE TABLE IF NOT EXISTS versions (
              id TEXT PRIMARY KEY, identity TEXT NOT NULL REFERENCES candidates(identity),
              sha256 TEXT NOT NULL, pdf_path TEXT NOT NULL, metadata_json TEXT NOT NULL,
              downloaded_from TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
              stage_path TEXT, stage_sha256 TEXT, created_at TEXT NOT NULL,
              UNIQUE(identity, sha256));
        """)

    def close(self):
        self.db.close()

    def start(self, mode):
        run_id = uuid.uuid4().hex
        # Only called under the exclusive job lock: previous running rows were interrupted.
        self.db.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'", (now(),))
        self.db.execute("INSERT INTO runs(id,mode,started_at,status) VALUES(?,?,?,'running')", (run_id, mode, now()))
        self.db.commit()
        return run_id

    def finish(self, run_id, report):
        self.db.execute("UPDATE runs SET status=?,finished_at=?,report_json=? WHERE id=?",
                        ("completed_with_errors" if report["errors"] else "completed", now(), json.dumps(report), run_id))
        self.db.commit()

    def observe(self, candidate):
        timestamp = now()
        self.db.execute("""INSERT INTO candidates(identity,metadata_json,first_seen,last_seen) VALUES(?,?,?,?)
            ON CONFLICT(identity) DO UPDATE SET metadata_json=excluded.metadata_json,last_seen=excluded.last_seen""",
                        (candidate["identity"], json.dumps(candidate), timestamp, timestamp))
        self.db.commit()

    def checked(self, identity, error=None):
        self.db.execute("UPDATE candidates SET last_checked=?,last_error=? WHERE identity=?", (now(), error, identity))
        self.db.commit()

    def add_version(self, candidate, body, final_url):
        sha = digest(body)
        version_id = digest((candidate["identity"] + ":" + sha).encode())
        path = self.path("pdfs/" + sha + ".pdf")
        if path.exists():
            if digest(path.read_bytes()) != sha:
                raise SyncError("stored_pdf_integrity_failed")
        else:
            atomic_write(path, body)
        previous = self.db.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
        if not previous:
            self.db.execute("""INSERT INTO versions(id,identity,sha256,pdf_path,metadata_json,
                downloaded_from,status,created_at) VALUES(?,?,?,?,?,?,'downloaded',?)""",
                            (version_id, candidate["identity"], sha, path.relative_to(self.root).as_posix(),
                             json.dumps(candidate), final_url, now()))
            self.db.commit()
        return dict(self.db.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()), previous is None

    def path(self, relative):
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root):
            raise SyncError("registry_path_outside_storage")
        return target

    def set_version(self, version_id, status, error=None, stage_path=None, stage_sha=None):
        self.db.execute("UPDATE versions SET status=?,error=?,stage_path=?,stage_sha256=? WHERE id=?",
                        (status, error, stage_path, stage_sha, version_id))
        self.db.commit()

    def summary(self):
        return {"root": str(self.root), "coverage": COVERAGE, "active_corpus_changed": False,
                "version_counts": dict(self.db.execute("SELECT status,COUNT(*) FROM versions GROUP BY status")),
                "candidates": self.db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
                "versions": [dict(row) for row in self.db.execute(
                    "SELECT id,identity,sha256,status,error,pdf_path,stage_path FROM versions ORDER BY created_at DESC LIMIT 30")],
                "runs": [dict(row) for row in self.db.execute(
                    "SELECT id,mode,started_at,finished_at,status FROM runs ORDER BY started_at DESC LIMIT 10")]}


def docling_stage(pdf, directory, metadata):
    """Unreviewed generic HybridChunker drafts, NOT approved operative clauses.

    Full source parse is retained; dates/topics/amendment targets remain unknown.
    Only the tokenizer runs: there are no Jina embedding/Gemini/Pinecone calls.
    """
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from docling_core.types.doc import DoclingDocument
    from transformers import AutoTokenizer
    from .ingestion import parse_pdf

    manifest = parse_pdf(pdf, directory, "notification", False, False)
    document = DoclingDocument.load_from_json(directory / "docling.json")
    # Retain the project's verified original XLM-R tokenizer. The offline
    # Mistral-warning heuristic is not a reason to replace its regex/backend.
    tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True, fix_mistral_regex=False)
    tokenizer.model_max_length = 10**9
    chunker = HybridChunker(tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=512), merge_peers=True)
    records = []
    for index, chunk in enumerate(chunker.chunk(dl_doc=document)):
        pages = sorted({p.page_no for item in chunk.meta.doc_items for p in item.prov})
        refs = [item.self_ref for item in chunk.meta.doc_items]
        if not pages or not refs or not all(1 <= p <= manifest["page_count"] for p in pages):
            raise SyncError("staged_chunk_missing_valid_provenance")
        embedding_text = chunker.contextualize(chunk)
        records.append({"chunk_id": f"{manifest['document_id']}:sync-draft-hybrid-v1:{index:04d}",
                        "document_id": manifest["document_id"], "source_type": "notification", "plan_required": "plus",
                        "text": chunk.text, "embedding_text": embedding_text, "pages": pages, "source_refs": refs,
                        "headings": list(chunk.meta.headings or []),
                        "token_count": len(tokenizer.encode(embedding_text, add_special_tokens=False)),
                        "eligible_for_retrieval": False})
    if not records:
        raise SyncError("no_staged_notification_chunks")
    return {"schema": "notification-staging-v1", "document_id": manifest["document_id"],
            "source_sha256": manifest["sha256"], "page_count": manifest["page_count"], "candidate": metadata,
            "docling_sha256": digest((directory / "docling.json").read_bytes()),
            "review_status": "pending_source_metadata_review", "eligible_for_retrieval": False,
            "issued_on": None, "effective_from": None, "amends": None, "topic_ids": [],
            "warnings": ["Generic draft chunks are not audited complete operative clauses.",
                         "Dates, identity, topics, corrigenda and amendment effects require source review.",
                         "Staging does not add this document to the active corpus or prove current law."],
            "over_token_budget": sum(r["token_count"] > 512 for r in records), "records": records}


def stage_version(registry, version, parser=docling_stage):
    pdf = registry.path(version["pdf_path"])
    if not pdf.is_file() or digest(pdf.read_bytes()) != version["sha256"]:
        raise SyncError("stored_pdf_integrity_failed")
    if version["status"] == "pending_source_metadata_review":
        path = registry.path(version["stage_path"])
        if not path.is_file() or digest(path.read_bytes()) != version["stage_sha256"]:
            raise SyncError("stored_staging_integrity_failed")
        return False
    directory = registry.path("staging/" + version["id"])
    registry.set_version(version["id"], "parsing")
    result = parser(pdf, directory, json.loads(version["metadata_json"]))
    if (result.get("source_sha256") != version["sha256"] or result.get("eligible_for_retrieval") is not False
            or result.get("review_status") != "pending_source_metadata_review" or not result.get("records")
            or any(r.get("eligible_for_retrieval") is not False for r in result["records"])):
        raise SyncError("unsafe_or_incomplete_staging_result")
    body = json.dumps(result, indent=2, ensure_ascii=False).encode()
    path = directory / "staged.json"
    atomic_write(path, body)
    registry.set_version(version["id"], "pending_source_metadata_review", stage_path=path.relative_to(registry.root).as_posix(),
                         stage_sha=digest(body))
    return True


def run(root, client=None, sources=None, max_pages=1, since_year=2025, max_documents=2,
        parse=False, stage_only=False, parser=docling_stage):
    root = Path(root).resolve()
    if not 1 <= max_documents <= 20:
        raise SyncError("invalid_document_limit")
    with exclusive_run(root):
        registry = Registry(root)
        run_id = registry.start("stage" if stage_only else "sync")
        report = {"run_id": run_id, "coverage": COVERAGE, "active_corpus_changed": False,
                  "published": 0, "downloaded_new_versions": 0, "unchanged_versions": 0,
                  "staged_versions": 0, "deferred_documents": 0, "errors": []}
        try:
            if stage_only:
                versions = [dict(v) for v in registry.db.execute(
                    "SELECT * FROM versions WHERE status IN ('downloaded','parsing','parse_failed') AND COALESCE(json_extract(metadata_json,'$.origin'),'')<>'admin_upload' ORDER BY created_at LIMIT ?",
                    (max_documents,))]
            else:
                if client is None:
                    raise SyncError("official_client_required")
                discovered = discover(client, sources if sources is not None else list(SOURCES), max_pages, since_year)
                report["discovery"] = discovered
                report["errors"].extend(discovered["errors"])
                versions = []
                for row in discovered["candidates"]:
                    registry.observe(row)
                # Do not process a page set whose structure/transport has failed.
                if not discovered["errors"]:
                    checked = {row[0]: row[1] for row in registry.db.execute("SELECT identity,last_checked FROM candidates")}
                    # New entries first, then least-recently checked. A bounded job
                    # must not repeatedly fetch only the first two listing rows.
                    ordered = sorted(discovered["candidates"], key=lambda row: checked[row["identity"]] or "")
                    selected = ordered[:max_documents]
                    report["deferred_documents"] = len(discovered["candidates"]) - len(selected)
                    for row in selected:
                        try:
                            body, final_url = client.get(row["pdf_url"], "pdf")
                            version, created = registry.add_version(row, body, final_url)
                            versions.append(version)
                            report["downloaded_new_versions" if created else "unchanged_versions"] += 1
                            registry.checked(row["identity"])
                        except Exception as exc:
                            code = str(exc) if isinstance(exc, SyncError) else f"download_failed:{type(exc).__name__}"
                            registry.checked(row["identity"], code)
                            report["errors"].append({"identity": row["identity"], "error": code})
            if parse or stage_only:
                for version in versions:
                    try:
                        report["staged_versions"] += int(stage_version(registry, version, parser))
                    except Exception as exc:
                        code = str(exc) if isinstance(exc, SyncError) else f"parse_failed:{type(exc).__name__}"
                        registry.set_version(version["id"], "parse_failed", code)
                        report["errors"].append({"version_id": version["id"], "error": code})
            registry.finish(run_id, report)
            return report
        except Exception as exc:
            report["errors"].append({"error": str(exc) if isinstance(exc, SyncError) else f"run_failed:{type(exc).__name__}"})
            registry.finish(run_id, report)
            raise
        finally:
            registry.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["discover", "sync", "stage", "status"]:
        sub = commands.add_parser(name)
        sub.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="App-owned staging storage, never an experiment directory")
        if name in {"discover", "sync"}:
            sub.add_argument("--source", action="append", choices=list(SOURCES))
            sub.add_argument("--max-pages", type=int, default=1, help="Per source; truncated scans are explicitly reported")
            sub.add_argument("--since-year", type=int, default=2025, help="Listing identity year, NOT an effective-date filter")
        if name in {"sync", "stage"}:
            sub.add_argument("--max-documents", type=int, default=2)
        if name == "sync":
            sub.add_argument("--parse", action="store_true", help="Parse/chunk into PRIVATE staging; never publish")
    args = parser.parse_args(argv)
    client = None
    try:
        if args.command == "status":
            if not (args.root / "registry.sqlite3").is_file():
                result = {"status": "no_ingestion_registry", "active_corpus_changed": False}
            else:
                registry = Registry(args.root)
                try:
                    result = registry.summary()
                finally:
                    registry.close()
        elif args.command == "stage":
            result = run(args.root, stage_only=True, max_documents=args.max_documents)
        else:
            client = OfficialClient()
            if args.command == "discover":
                result = discover(client, args.source or list(SOURCES), args.max_pages, args.since_year)
                result["storage_changed"] = False
            else:
                result = run(args.root, client, args.source, args.max_pages, args.since_year,
                             args.max_documents, parse=args.parse)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 1 if result.get("errors") else 0
    except (SyncError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, SyncError) else "registry_database_error"}))
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
