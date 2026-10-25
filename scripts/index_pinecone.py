"""Explicit one-time indexing; reruns upsert identical content-addressed IDs.

Never deletes existing data or changes billing. Set --create only to create a
missing project-owned index. Historical experiment files are read-only inputs.
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import time

from dotenv import load_dotenv

from gst_rag.ingestion import read_json, write_json
from gst_rag.service import Corpus
from gst_rag.vector_store import API_VERSION, DEFAULT_INDEX, DIMENSION, PineconeStore, Snapshot, app_jina

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", help="Create missing index in AWS us-east-1; no plan upgrade")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    corpus = Corpus(ROOT)
    # Verify every registered PDF still matches before sending any vectors.
    for document_id in corpus.sources:
        corpus.pdf_path(document_id)
    snapshot = Snapshot(read_json(ROOT / "data/app/corpus.json"))
    store = PineconeStore(snapshot, os.environ.get("PINECONE_INDEX_NAME", DEFAULT_INDEX))
    info = store.describe(missing_ok=True)
    created = info is None
    if created:
        if not args.create:
            raise ValueError("Index missing. Review --create to create this demo's index; no write made")
        store.create()
        print("Index creation accepted; checking readiness (bounded wait).", flush=True)
    deadline = time.monotonic() + 120
    while not info or not info.get("status", {}).get("ready"):
        if time.monotonic() >= deadline:
            raise RuntimeError("Index readiness timeout; index retained, rerun after it is ready")
        time.sleep(2)
        info = store.describe()
    store.connect()
    jina = app_jina(ROOT)
    embeddings = jina.encode([r["embedding_text"] for r in snapshot.records], "retrieval.passage")
    store.upsert(embeddings)
    print(f"Upsert acknowledged for {store.upserted} vectors; verifying every stored vector.", flush=True)
    deadline = time.monotonic() + 90
    while True:
        try:
            counts = store.verify_records(embeddings)
            break
        except ValueError as error:
            if "not yet visible" not in str(error) or time.monotonic() >= deadline:
                raise
            time.sleep(2)
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "index": store.name,
        "created_this_run": created, "api_version": API_VERSION, "embedding_model": jina.model,
        "dimension": DIMENSION, "metric": "cosine", "corpus_id": snapshot.corpus_id,
        "verified_expected_counts": counts, "upserted_vectors": store.upserted,
        "all_expected_metadata_and_vectors_verified": True, "pinecone_requests": store.requests,
        "pinecone_read_units": store.read_units, "jina_usage": {"requests": jina.requests, "tokens": jina.tokens},
        "raw_text_uploaded_to_pinecone": False, "deletion_performed": False}
    destination = ROOT / "data/app/pinecone" / ("index_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    write_json(destination, report)
    print({"report": str(destination.relative_to(ROOT)), "verified_counts": counts, "jina_requests": jina.requests}, flush=True)


if __name__ == "__main__":
    # Do not let provider/library tracebacks display keys or request bodies.
    try:
        main()
    except Exception as error:
        print(f"Indexing stopped ({type(error).__name__}); provider details omitted. Check configuration and rerun.")
        raise SystemExit(1) from None
