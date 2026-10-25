"""Check the actual ICAI run and distinguish hard failures from layout warnings."""

import hashlib
import json
from pathlib import Path

from gst_rag.benchmark import group_covered
from gst_rag.ingestion import read_json, write_json
from gst_rag.experiment_history import frozen_code_preserved

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/icai_composite_mixed_p70_79"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = read_json(DATA / "manifest.json")
    doc = read_json(DATA / "docling.json")
    units = read_json(DATA / "units.json")
    parents = read_json(DATA / "parents.json")
    report = read_json(DATA / "chunk_report.json")
    questions = read_json(ROOT / "data/benchmark/icai_topic_questions.json")
    checks = {}
    expected_pages = set(range(70, 80))
    refs = {r for u in units for r in u["source_refs"]}
    checks["original_page_positions_preserved"] = set(manifest["converted_pdf_pages"]) == expected_pages == set(map(int, doc["pages"])) and all(set(u["pages"]) <= expected_pages for u in units)
    source = ROOT / "data/sources/icai" / manifest["filename"]
    checks["original_pdf_checksum"] = digest(source) == manifest["sha256"]
    checks["source_policy_labels"] = manifest["source_type"] == "icai_book" and manifest["plan_required"] == "plus"
    checks["every_label_alternative_exists"] = all(group_covered([alt], units) for q in questions["questions"] for group in q["evidence_groups"] for alt in group)
    footnotes = {t["self_ref"] for t in doc["texts"] if t["label"] == "footnote"}
    checks["circular_reference_footnotes_preserved"] = len(footnotes) == 6 and footnotes <= refs
    for name in ["fixed", "hierarchical", "hybrid"]:
        chunks = [json.loads(line) for line in (DATA / f"chunks_{name}.jsonl").read_text(encoding="utf-8").splitlines()]
        checks[f"{name}_coverage_and_provenance"] = refs == {r for c in chunks for r in c["source_refs"]} and all(c["pages"] and set(c["pages"]) <= expected_pages and c["source_type"] == "icai_book" and c["plan_required"] == "plus" for c in chunks)
        if name != "hierarchical":
            checks[f"{name}_token_cap"] = all(c["token_count"] <= 512 for c in chunks)
    plus = read_json(DATA / "benchmark_jina_dev_child_plus_all_icai_v02.json")
    pro = read_json(DATA / "benchmark_jina_dev_child_pro_hybrid_icai_v02.json")
    checks["same_hybrid_hits_and_context_for_plus_and_pro_on_icai_only"] = all(a["hits"] == b["hits"] and a["context"] == b["context"] for a, b in zip(plus["variants"]["hybrid"]["rows"], pro["variants"]["hybrid"]["rows"], strict=True))
    checks["hybrid_answerable_evidence_complete"] = all(r["complete_at_10"] and r["context_evidence_recall"] == 1 for r in plus["variants"]["hybrid"]["rows"] if r["expected"] == "answer")
    checks["mixed_corpus_access_smoke"] = read_json(DATA / "mixed_access_smoke.json")["status"] == "passed"
    old = ROOT / "data/processed/chapter7_repaired"
    frozen = read_json(old / "experiment_freeze.json")
    checks["old_frozen_artifacts_and_implementation_preserved"] = all(digest(old / name) == value for name, value in frozen["artifact_sha256"].items()) and frozen_code_preserved(old, frozen, ROOT / "src/gst_rag")
    header_parents = [p["parent_id"] for p in parents if p["headings"] and p["headings"][0] == "SUPPLY UNDER GST"]
    warnings = [{"issue": "running_headers_used_as_parent_titles", "parent_ids": header_parents,
        "explanation": "Repeated page headers are section_header items in this parse, so the v0.2 chunker treats them as content headings."},
        {"issue": "single_integer_heading_scheme_not_supported_by_numbered_outline_helper",
         "explanation": "This book uses headings such as 4. and 1.; the existing helper was written for multi-part numbers such as 7.2.10. No heading fix or retrieval tuning was applied in this test."}]
    result = {"status": "passed_with_structure_warnings" if all(checks.values()) else "failed", "config_id": report["config_id"],
        "checks": checks, "structural_warnings": warnings, "reviewed_pdf_pages": sorted(expected_pages),
        "canonical_source_refs": len(refs), "footnotes_preserved": len(footnotes),
        "note": "A passing evidence test does not validate parent structure, current law, generated answers, or authenticated access. This is a development smoke test on a ten-page topic slice."}
    write_json(DATA / "pipeline_verification.json", result)
    print(json.dumps(result, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
