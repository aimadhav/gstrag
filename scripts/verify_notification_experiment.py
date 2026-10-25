"""Verify saved notification sources, reviews, mixed access and date checks locally."""

import argparse
import hashlib
import json
from datetime import date

from transformers import AutoTokenizer

from gst_rag.benchmark import allowed
from gst_rag.ingestion import read_json, write_json
from gst_rag.notifications import qualified_group_covered, reviewed_records, source_items
from build_notification_sample import OUTPUT, ROOT, load_books
from prepare_notifications import SAMPLES


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-dense", action="store_true")
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True)
    tokenizer.model_max_length = 10**9
    checks, rebuilt = {}, []
    for sample in SAMPLES:
        slug = sample["slug"]
        source = ROOT / "data/sources/notifications" / (slug + ".pdf")
        directory = ROOT / "data/processed/notifications_v01" / slug
        manifest, doc = read_json(directory / "manifest.json"), read_json(directory / "docling.json")
        card = read_json(source.with_suffix(".source.json"))
        checks[f"{slug}_original_source_identity"] = digest(source) == manifest["sha256"] == card["sha256"]
        expected_pages = list(range(1, sample["expected_pages"] + 1))
        checks[f"{slug}_complete_conversion_original_pages"] = manifest["converted_pdf_pages"] == expected_pages == sorted(map(int, doc["pages"])) and manifest["status"] == "success"
        review_path = ROOT / "data/audit/notifications" / (slug + ".review.json")
        rebuilt += reviewed_records(directory, review_path, tokenizer)
        checks[f"{slug}_source_review_renders_exist"] = all((ROOT / "tmp/pdfs/notification_review" / f"{slug}-{n}.png").is_file() for n in expected_pages)
    stored = read_json(OUTPUT / "notification_records.json")
    checks["reviewed_records_rebuild_identically"] = rebuilt == stored
    checks["all_notification_chunks_plus_with_full_provenance_and_token_cap"] = all(
        r["source_type"] == "notification" and r["plan_required"] == "plus" and r["pages"] and r["evidence_spans"]
        and r["token_count"] <= 512 and not r["notification"]["chain_complete"] and r["notification"]["rate_scope"] == "cgst_only" for r in stored)
    continuation = next(r for r in stored if r["chunk_id"].endswith(":insert_new_entry"))
    checks["cross_page_entry_and_condition_kept_together"] = all(ref in continuation["source_refs"] for ref in ["#/tables/2", "#/tables/3"]) and all(
        term in continuation["text"] for term in ["Solar power based devices", "seventy per cent.", "remaining thirty per cent."])
    labels_path = ROOT / "data/benchmark/notification_questions_v1.json"
    questions = read_json(labels_path)["questions"]
    corpus = load_books() + stored
    checks["all_source_label_alternatives_present_and_accessible"] = all(
        qualified_group_covered([alt], [r for r in corpus if allowed(r, q["plan"])])
        for q in questions for group in q["evidence_groups"] for alt in group)
    links = read_json(OUTPUT / "book_notification_links.json")
    checks["automatic_links_are_candidates_not_approval"] = bool(links) and all(l["status"] == "candidate_pending_admin_review" and l["basis"] == "explicit_number_and_series_reference" for l in links)
    detail = {}
    for retriever in ["bm25", "jina"]:
        path = OUTPUT / f"benchmark_{retriever}_dev_budgetfix.json"
        if not path.exists():
            if retriever == "jina" and not args.require_dense:
                continue
            checks[f"{retriever}_run_present"] = False
            continue
        run = read_json(path)
        rows = run["rows"]
        checks[f"{retriever}_same_inputs_and_settings"] = run["question_set_sha256"] == digest(labels_path) and run["notification_records_sha256"] == digest(OUTPUT / "notification_records.json") and run["context_budget"] == 2048 and run["top_k"] == 10 and len(rows) == 12 and run["packing_version"] == "retokenized_hard_cap_v2"
        checks[f"{retriever}_implementation_hashes_match"] = all(digest(ROOT / "src/gst_rag" / name) == value for name, value in run["implementation_sha256"].items())
        checks[f"{retriever}_date_and_status_expectations"] = all(r["date_selection_matches_expectation"] for r in rows)
        checks[f"{retriever}_checked_evidence_complete"] = all(r["checked_context_recall"] == 1 for r in rows if r["checked_context_recall"] is not None)
        checks[f"{retriever}_context_budget_and_access"] = all(r["global_context_tokens"] <= 2048 and r["checked_context_tokens"] <= 2048 and all(allowed(c, r["plan"]) for c in r["global_context"] + r["checked_context"]) for r in rows)
        checks[f"{retriever}_no_premature_notification_in_checked_context"] = all(
            date.fromisoformat(c["notification"]["issued_on"]) <= date.fromisoformat(r["as_of"])
            and date.fromisoformat(c["notification"]["effective_from"]) <= date.fromisoformat(r["as_of"])
            for r in rows for c in r["checked_context"] if c["source_type"] == "notification")
        checks[f"{retriever}_no_unapproved_answer_or_pdf_link_in_public_payload"] = all(
            set(r["public_payload"]) == {"status", "message"} and r["public_payload"]["status"] in {"pending_review", "clarification_required"}
            and not r["current_law_verified"] for r in rows)
        detail[retriever] = {**run["summary"], "api_usage_this_run": run["api_usage_this_run"],
            "incomplete_global_context_ids": [r["question_id"] for r in rows if r["global_context_recall"] is not None and r["global_context_recall"] < 1],
            "global_contexts_with_premature_notifications": [r["question_id"] for r in rows if r["as_of"] and any(
                c["source_type"] == "notification" and c["notification"]["effective_from"] > r["as_of"] for c in r["global_context"])]}
    result = {"status": "passed" if all(checks.values()) else "failed", "checks": checks, "detail": detail,
              "note": "Local development checks only. Supplied topic IDs; partial notification corpus; no legal precedence determination, answer generation, persistent review queue, or authenticated source endpoints."}
    write_json(OUTPUT / "verification.json", result)
    print(json.dumps(result, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
