"""Mixed-source development comparison: global top-K versus mandatory update check.

The supplied topic IDs are reviewed labels, not an implemented query classifier.
No Gemini answers, legal decisions, or approval are generated here.
"""

import argparse
import hashlib
import json

from gst_rag.benchmark import BM25, Jina, allowed, assemble_context
from gst_rag.ingestion import read_json, write_json
from gst_rag.notifications import check_updates, public_status, qualified_group_covered, update_context
from build_notification_sample import load_books, OUTPUT, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retriever", choices=["bm25", "jina"], default="bm25")
    parser.add_argument("--output-tag", choices=["", "budgetfix"], default="")
    args = parser.parse_args()
    suffix = "_" + args.output_tag if args.output_tag else ""
    destination = OUTPUT / f"benchmark_{args.retriever}_dev{suffix}.json"
    if destination.exists():
        raise ValueError("Saved development run already exists; preserve it and choose a new experiment directory")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True)
    tokenizer.model_max_length = 10**9
    books, notifications = load_books(), read_json(OUTPUT / "notification_records.json")
    records = books + notifications
    links = read_json(OUTPUT / "book_notification_links.json")
    labels_path = ROOT / "data/benchmark/notification_questions_v1.json"
    questions = read_json(labels_path)["questions"]
    for question in questions:
        permitted = [r for r in records if allowed(r, question["plan"])]
        for group in question["evidence_groups"]:
            for alternative in group:
                if not qualified_group_covered([alternative], permitted):
                    raise ValueError(f"Missing/inaccessible source evidence for {question['id']}; no API call made")
    seeded_conflicts = 0
    if args.retriever == "jina" and not (OUTPUT / "jina_cache.json").exists():
        # Reuse content-addressed passage vectors without modifying old caches.
        cache = {}
        for name in ["chapter7_structure_v03", "icai_composite_mixed_p70_79_v03"]:
            for key, vector in read_json(ROOT / "data/processed" / name / "jina_cache.json").items():
                seeded_conflicts += key in cache and cache[key] != vector
                cache.setdefault(key, vector)
        write_json(OUTPUT / "jina_cache.json", cache)
    jina = Jina(OUTPUT) if args.retriever == "jina" else None
    queries = jina.encode([q["question"] for q in questions], "retrieval.query") if jina else None
    pools = {}
    for plan in {q["plan"] for q in questions}:
        pool = [r for r in records if allowed(r, plan)]
        pools[plan] = (pool, jina.encode([r["embedding_text"] for r in pool], "retrieval.passage") if jina else BM25(pool))
    rows = []
    for i, question in enumerate(questions):
        pool, index = pools[question["plan"]]
        scores = (index @ queries[i]).tolist() if jina else index.scores(question["question"])
        ranked = [pool[j] for j in sorted(range(len(scores)), key=lambda j: (-scores[j], j))]
        hits = ranked[:10]
        baseline, used, _ = assemble_context(hits, [], [], tokenizer, 2048, "child", question["plan"])
        check = check_updates(records, question["topic_ids"], question["as_of"], question["plan"], links)
        chosen, chosen_tokens, packing = update_context(check, [r for r in ranked if r["source_type"] != "notification"][:10], tokenizer, 2048, question["plan"])
        expected_keys = set(question["expected_notification_keys"])
        actual_keys = {r["notification"]["key"] for r in check["candidates"]}
        groups = question["evidence_groups"]
        def coverage(context):
            return sum(qualified_group_covered(group, context) for group in groups) / len(groups) if groups else None
        rows.append({"question_id": question["id"], "question": question["question"], "plan": question["plan"], "as_of": question["as_of"],
            "expected_status": question["expected_status"], "actual_status": check["status"],
            "expected_notification_keys": sorted(expected_keys), "actual_notification_keys": sorted(actual_keys),
            "date_selection_matches_expectation": expected_keys == actual_keys and check["status"] == question["expected_status"],
            "global_top10_recall": coverage(hits), "global_context_recall": coverage(baseline),
            "checked_context_recall": coverage(chosen), "global_context_tokens": used, "checked_context_tokens": chosen_tokens,
            "packing": packing, "check_reason": check.get("reason"), "current_law_verified": check.get("current_law_verified", False),
            "public_payload": public_status(check), "global_context": baseline, "checked_context": chosen,
            "published_not_yet_effective": [r["chunk_id"] for r in check.get("published_not_yet_effective", [])]})
    measured = [r for r in rows if r["global_context_recall"] is not None]
    report = {"retriever": args.retriever, "scope": "Assistant-labeled mixed-source development experiment with supplied topic IDs, not answer accuracy or held-out legal validation",
        "packing_version": "retokenized_hard_cap_v2",
        "implementation_sha256": {name: hashlib.sha256((ROOT / "src/gst_rag" / name).read_bytes()).hexdigest() for name in ["benchmark.py", "notifications.py"]},
        "question_set_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        "notification_records_sha256": hashlib.sha256((OUTPUT / "notification_records.json").read_bytes()).hexdigest(),
        "questions": len(rows), "evidence_questions": len(measured), "context_budget": 2048, "top_k": 10,
        "summary": {"date_and_status_checks_passed": sum(r["date_selection_matches_expectation"] for r in rows),
            "global_context_complete": sum(r["global_context_recall"] == 1 for r in measured),
            "checked_context_complete": sum(r["checked_context_recall"] == 1 for r in measured),
            "global_context_mean_recall": sum(r["global_context_recall"] for r in measured) / len(measured),
            "checked_context_mean_recall": sum(r["checked_context_recall"] for r in measured) / len(measured)},
        "api_usage_this_run": {"tokens": jina.tokens, "requests": jina.requests, "seconds": round(jina.api_seconds, 3)} if jina else {"tokens": 0, "requests": 0, "seconds": 0},
        "seed_cache_conflicts_first_value_retained": seeded_conflicts, "rows": rows}
    write_json(destination, report)
    print(json.dumps({"saved": str(destination), "questions": report["questions"], "evidence_questions": report["evidence_questions"],
        "summary": report["summary"], "api_usage_this_run": report["api_usage_this_run"]}, indent=2))


if __name__ == "__main__":
    main()
