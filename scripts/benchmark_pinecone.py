"""Live transport/parity check on the EXISTING 12 development scenarios.

Not a new held-out benchmark, scale benchmark, or answer-accuracy evaluation.
Uses identical cached Jina vectors for local exact search and Pinecone search.
No index writes or generated legal answers.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import time

from dotenv import load_dotenv
import numpy as np
from transformers import AutoTokenizer

from gst_rag.benchmark import allowed
from gst_rag.ingestion import read_json, write_json
from gst_rag.notifications import check_updates, qualified_group_covered, update_context
from gst_rag.vector_store import DEFAULT_INDEX, PineconeStore, Snapshot, app_jina

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env", override=False)
    bundle = read_json(ROOT / "data/app/corpus.json")
    snapshot = Snapshot(bundle)
    questions = read_json(ROOT / "data/benchmark/notification_questions_v1.json")["questions"]
    if any(q["split"] != "dev" for q in questions):
        raise ValueError("This parity check must not use held-out questions")
    store = PineconeStore(snapshot, os.environ.get("PINECONE_INDEX_NAME", DEFAULT_INDEX))
    store.connect()
    jina = app_jina(ROOT)
    vectors = jina.encode([r["embedding_text"] for r in snapshot.records], "retrieval.passage")
    counts = store.verify_records(vectors)
    queries = jina.encode([q["question"] for q in questions], "retrieval.query")
    tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True)
    tokenizer.model_max_length = 10**9
    rows = []
    for q, vector in zip(questions, queries):
        start = time.perf_counter()
        local = sorted([(r, float(score)) for r, score in zip(snapshot.records, vectors @ vector) if allowed(r, q["plan"])],
                       key=lambda pair: (-pair[1], pair[0]["chunk_id"]))
        local_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        remote = store.search(vector, q["plan"])
        remote_ms = (time.perf_counter() - start) * 1000
        local_ids = [r["chunk_id"] for r, _ in local[:10]]
        remote_ids = [r["chunk_id"] for r, _ in remote[:10]]
        check = check_updates(snapshot.records, q["topic_ids"], q["as_of"], q["plan"], bundle["links"])
        local_context, _, _ = update_context(check, [r for r, _ in local if r["source_type"] != "notification"][:10], tokenizer, 2048, q["plan"])
        remote_context, used, packing = update_context(check, [r for r, _ in remote if r["source_type"] != "notification"][:10], tokenizer, 2048, q["plan"])
        groups = q["evidence_groups"]
        coverage = lambda ctx: sum(qualified_group_covered(g, ctx) for g in groups) / len(groups) if groups else None
        local_scores = {r["chunk_id"]: score for r, score in local}
        rows.append({"question_id": q["id"], "plan": q["plan"], "exact_top10_order": local_ids == remote_ids,
            "top10_set_overlap": len(set(local_ids) & set(remote_ids)) / len(local_ids),
            "max_score_error": max((abs(score - local_scores[r["chunk_id"]]) for r, score in remote), default=0),
            "local_context_recall": coverage(local_context), "pinecone_context_recall": coverage(remote_context),
            "identical_context_ids": [r["chunk_id"] for r in local_context] == [r["chunk_id"] for r in remote_context],
            "date_status_matches": check["status"] == q["expected_status"] and
                sorted({r["notification"]["key"] for r in check["candidates"]}) == sorted(q["expected_notification_keys"]),
            "all_hits_allowed": all(allowed(r, q["plan"]) for r, _ in remote), "context_tokens": used,
            "packing": packing, "local_search_ms": round(local_ms, 3), "pinecone_search_ms": round(remote_ms, 3)})
    measured = [r for r in rows if r["pinecone_context_recall"] is not None]
    checks = {"every_top10_set_matches": all(r["top10_set_overlap"] == 1 for r in rows),
        "all_scores_within_1e_5": all(r["max_score_error"] <= 1e-5 for r in rows),
        "all_context_evidence_matches_local": all(r["local_context_recall"] == r["pinecone_context_recall"] for r in rows),
        "all_access_checks": all(r["all_hits_allowed"] for r in rows),
        "all_date_checks": all(r["date_status_matches"] for r in rows),
        "all_context_budgets": all(r["context_tokens"] <= 2048 for r in rows)}
    report = {"scope": "Existing development scenarios; vector-storage parity, not held-out answer accuracy or scale testing",
        "index": store.name, "corpus_id": snapshot.corpus_id, "expected_verified_counts": counts,
        "questions": len(rows), "evidence_questions": len(measured), "checks": checks,
        "complete_pinecone_context": sum(r["pinecone_context_recall"] == 1 for r in measured),
        "exact_top10_order_count": sum(r["exact_top10_order"] for r in rows),
        "median_local_search_ms": round(float(np.median([r["local_search_ms"] for r in rows])), 3),
        "median_pinecone_search_ms": round(float(np.median([r["pinecone_search_ms"] for r in rows])), 3),
        "timing_scope": "Search only; excludes embedding, startup, notification packing and human review; sequential namespace requests",
        "pinecone_requests": store.requests, "pinecone_read_units": store.read_units,
        "jina_usage": {"requests": jina.requests, "tokens": jina.tokens}, "rows": rows}
    destination = ROOT / "data/app/pinecone" / ("parity_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    write_json(destination, report)
    print({"report": str(destination.relative_to(ROOT)), "checks": checks,
           "complete_context": f"{report['complete_pinecone_context']}/{len(measured)}", "jina_requests": jina.requests})
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Parity check stopped ({type(error).__name__}); provider details omitted.")
        raise SystemExit(1) from None
