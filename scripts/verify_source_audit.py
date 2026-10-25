"""Check audit artifacts and expose unresolved ingestion defects without API calls.

The checks verify recorded evidence and known structural failures. They do not
automatically establish semantic sufficiency, current law, or answer quality.
Use --require-ready to make any unresolved source check fail the command.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from gst_rag.benchmark import normalize
from gst_rag.chunking import heading_number
from gst_rag.experiment_history import frozen_code_preserved

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/chapter7"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--directory", type=Path, default=DATA)
    parser.add_argument("--require-regressions", action="store_true", help="Also require completed dense retrieval regressions")
    args = parser.parse_args()
    directory = args.directory
    labels_path = ROOT / "data/benchmark/chapter7_questions.source_audited_v2.json"
    labels = load(labels_path)
    original = load(ROOT / "data/benchmark/chapter7_questions.json")
    manifest = load(directory / "manifest.json")
    doc = load(directory / "docling.json")
    units = load(directory / "units.json")
    parents = load(directory / "parents.json")
    source = Path.home() / "Downloads" / manifest["filename"]
    checks = []

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    check("source_identity", hashlib.sha256(source.read_bytes()).hexdigest() == manifest["sha256"] == labels["source_audit"]["source_sha256"], "Original PDF checksum matches parse and audited labels.")
    check("page_review_record", labels["source_audit"]["pages_read_as_text_and_images"] == list(range(1, 46)) and all(
        (ROOT / f"data/audit/pages/page{i:02d}.txt").exists() and (ROOT / f"data/audit/render/page-{i:02d}.png").exists() for i in range(1, 46)),
        "Assistant recorded all 45 pages read; independent page extracts and renders exist. File existence alone cannot prove reading.")
    check("query_and_split_integrity", [(q["id"], q["question"], q["split"], q["expected"]) for q in labels["questions"]] == [
        (q["id"], q["question"], q["split"], q["expected"]) for q in original["questions"]], "No query wording, split, or expected behavior changed during label audit.")
    invalid = []
    for q in labels["questions"]:
        for group in q["evidence_groups"]:
            for alt in group:
                valid_sources = []
                for ref in alt["source_refs"]:
                    if ref.startswith("#/texts/"):
                        valid_sources.append(doc["texts"][int(ref.rsplit("/", 1)[1])]["text"])
                    else:
                        valid_sources.extend(u["text"] for u in units if ref in u["source_refs"])
                if not any(normalize(alt["quote"]) in normalize(s) for s in valid_sources):
                    invalid.append(q["id"])
    check("individual_source_excerpts", not invalid, {"invalid_question_ids": invalid})
    missing = []
    for number in ["7.2.10", "7.2.11"]:
        if not any(any(re.match(rf"^{re.escape(number)}\.?\s", h) for h in p["headings"]) for p in parents):
            missing.append(number)
    check("trailing_dot_numbered_parents", not missing, {"missing_subsections": missing, "expected": "Each numbered subsection must have its own parent, not be nested under 7.2.9."})
    parent_by_id = {p["parent_id"]: p for p in parents}
    wrong_ownership, checked = [], 0
    for number in ["7.2.10", "7.2.11"]:
        start = next(i for i, text in enumerate(doc["texts"]) if text["label"] == "section_header" and heading_number(text["text"]) == number)
        end = next((i for i in range(start + 1, len(doc["texts"])) if doc["texts"][i]["label"] == "section_header" and (n := heading_number(doc["texts"][i]["text"])) and len(n.split(".")) <= len(number.split("."))), len(doc["texts"]))
        refs = {f"#/texts/{i}" for i in range(start + 1, end)}
        for unit in units:
            if refs & set(unit["source_refs"]):
                checked += 1
                owner = parent_by_id[unit["parent_id"]]
                if heading_number(owner["headings"][-1]) != number:
                    wrong_ownership.append(unit["unit_id"])
    check("rebuilt_subsection_membership", checked > 0 and not wrong_ownership, {"units_checked": checked, "incorrect_unit_ids": wrong_ownership})
    indexed = {ref for u in units for ref in u["source_refs"]}
    transcription = load(ROOT / "data/audit/chapter7_picture_transcriptions.json")["pictures"][0]
    diagram_units = [u for u in units if "#/pictures/1" in u["source_refs"]]
    check("page21_flowchart_searchable", bool(diagram_units) and any(normalize(transcription["text"]) in normalize(u["text"]) and u["pages"] == [21] for u in diagram_units), "Complete reviewed diagram text is present in canonical source with original picture reference and PDF page 21.")
    original_refs = {ref for u in load(DATA / "units.json") for ref in u["source_refs"]}
    check("no_original_source_refs_lost", original_refs <= indexed, {"missing_refs": sorted(original_refs - indexed)})
    variants_ok = True
    for variant in ["fixed", "hierarchical", "hybrid"]:
        chunks = [json.loads(line) for line in (directory / f"chunks_{variant}.jsonl").read_text(encoding="utf-8").splitlines()]
        variants_ok &= {r for c in chunks for r in c["source_refs"]} == indexed
        variants_ok &= all(c["pages"] and c["plan_required"] == "pro" for c in chunks)
        if diagram_units:
            variants_ok &= any("#/pictures/1" in c["source_refs"] and 21 in c["pages"] and "Highest rate of tax" in c["text"] for c in chunks)
    check("all_variants_preserve_source_and_access", variants_ok, "Every variant covers all canonical refs, has page provenance, and keeps the firm book Pro-only; diagram evidence is included when present.")
    if args.require_regressions:
        run_path = directory / "benchmark_jina_dev_child_pro_all_source_regressions.json"
        successful = False
        detail = {"result_file": run_path.name}
        if run_path.exists():
            run = load(run_path)
            expected_hash = hashlib.sha256((ROOT / "data/benchmark/chapter7_source_regressions.json").read_bytes()).hexdigest()
            hybrid = run["variants"]["hybrid"]
            successful = run["question_set_sha256"] == expected_hash and run["config_id"] == load(directory / "chunk_report.json")["config_id"] and hybrid["questions"] == 6 and all(r["complete_at_10"] and r["context_evidence_recall"] == 1 for r in hybrid["rows"])
            detail["hybrid_incomplete_ids"] = [r["question_id"] for r in hybrid["rows"] if not r["complete_at_10"] or r["context_evidence_recall"] != 1]
        check("dense_targeted_development_regressions", successful, detail)
    heldout_paths = list(directory.glob("benchmark_*heldout*.json"))
    if heldout_paths:
        valid = len(heldout_paths) == 1 and (directory / "experiment_freeze.json").exists()
        if valid:
            freeze = load(directory / "experiment_freeze.json")
            run = load(heldout_paths[0])
            valid &= run["config_id"] == freeze["config_id"]
            valid &= run["question_set_sha256"] == freeze["question_set_sha256"] == hashlib.sha256(labels_path.read_bytes()).hexdigest()
            valid &= all(hashlib.sha256((directory / name).read_bytes()).hexdigest() == checksum for name, checksum in freeze["artifact_sha256"].items())
            valid &= frozen_code_preserved(directory, freeze, ROOT / "src/gst_rag")
            settings = freeze["heldout_settings"]
            valid &= all(run[key] == settings[key] for key in ["retriever", "context_mode", "context_budget", "plan", "top_k"])
            valid &= settings["variant"] == "all" and set(run["variants"]) == {"fixed", "hierarchical", "hybrid"}
        check("completed_heldout_matches_unchanged_freeze", valid, {"heldout_score_files": [p.name for p in heldout_paths]})
    else:
        check("heldout_not_scored_during_audit", True, {"heldout_score_files": []})
    output = {"status": ("verified_and_evaluated" if heldout_paths else "ready_for_next_evaluation") if all(c["passed"] for c in checks) else "verification_failed",
        "checks": checks, "note": "Even all source checks passing would not constitute independent legal validation or establish correct generated answers."}
    path = directory / "source_audit_verification.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    if args.require_ready and not all(c["passed"] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
