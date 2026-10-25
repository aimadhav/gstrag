"""Check every ICAI canonical ref's reviewed parent, plus both-book integrity.

This check is independent of retrieval scores and never calls an API.
"""

import hashlib
import json
import argparse
from pathlib import Path

from gst_rag.benchmark import group_covered
from gst_rag.experiment_history import frozen_code_preserved
from gst_rag.ingestion import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed"
ICAI_BASE, ICAI = DATA / "icai_composite_mixed_p70_79", DATA / "icai_composite_mixed_p70_79_v03"
FIRM_BASE, FIRM = DATA / "chapter7_repaired", DATA / "chapter7_structure_v03"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref_owners(directory):
    return {ref: p["headings"] for p in read_json(directory / "parents.json") for ref in p["source_refs"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-retrieval", action="store_true", help="Also check saved development retrieval/access runs")
    args = parser.parse_args()
    checks, detail = {}, {}
    # Source-audited ownership, authored from visual topic boundaries, not scores.
    topic_refs = {
        None: [2], 3: [], 4: [5, 6, 10, 11],
        12: [*range(13, 35), *range(36, 67), 68],
        69: list(range(70, 76)), 79: [80, 92], 81: [82, 93],
        83: [84, 85, 86, 94], 87: [*range(88, 92), 101, *range(103, 110)],
        110: [98, 99, 100, *range(111, 126), 127, 128], 129: list(range(130, 140)),
    }
    doc = read_json(ICAI / "docling.json")
    expected = {f"#/texts/{i}": doc["texts"][title]["text"] if title is not None else None
                for title, refs in topic_refs.items() for i in refs}
    expected["#/tables/0"] = doc["texts"][3]["text"]
    before, after = ref_owners(ICAI_BASE), ref_owners(ICAI)
    missing = sorted(set(after) - set(expected))
    wrong = [r for r, headings in after.items() if r not in expected or (headings[-1] if headings else None) != expected[r]]
    checks["all_canonical_refs_have_reviewed_parent"] = not missing and not wrong
    detail["ownership"] = {"checked_refs": len(after), "missing_expectations": missing, "wrong_parent_refs": wrong,
                           "changed_owner_refs": sum(before.get(r) != h for r, h in after.items())}
    parents = read_json(ICAI / "parents.json")
    checks["running_headers_never_become_parents"] = not any("SUPPLY UNDER GST" in p["headings"] for p in parents)
    removed = read_json(ICAI / "exclusions.json")
    checks["exactly_five_mislabeled_headers_removed"] = {e["ref"] for e in removed if e["reason"] == "repeated_top_margin_heading"} == {f"#/texts/{n}" for n in [9, 35, 67, 102, 126]}
    root = doc["texts"][3]["text"]
    composite = doc["texts"][12]["text"]
    checks["local_integer_topics_stay_inside_section_four"] = all(
        after[f"#/texts/{ref}"][:2] == [root, composite] for ref in [70, 80, 82, 84, 88])
    for name, baseline, current, labels in [
        ("icai", ICAI_BASE, ICAI, ROOT / "data/benchmark/icai_topic_questions.json"),
        ("firm", FIRM_BASE, FIRM, ROOT / "data/benchmark/chapter7_questions.source_audited_v2.json")]:
        old_units, units = read_json(baseline / "units.json"), read_json(current / "units.json")
        report, manifest = read_json(current / "chunk_report.json"), read_json(current / "manifest.json")
        refs = {r for u in units for r in u["source_refs"]}
        checks[f"{name}_parse_and_manifest_unchanged"] = all(digest(baseline / f) == digest(current / f) for f in ["docling.json", "manifest.json"])
        checks[f"{name}_all_refs_and_unit_text_preserved"] = refs == {r for u in old_units for r in u["source_refs"]} and sorted((tuple(u["source_refs"]), u["text"], tuple(u["pages"])) for u in old_units) == sorted((tuple(u["source_refs"]), u["text"], tuple(u["pages"])) for u in units)
        source_labels = read_json(labels)
        checks[f"{name}_all_label_alternatives_present"] = all(group_covered([a], units) for q in source_labels["questions"] for g in q["evidence_groups"] for a in g)
        parent_by_id = {p["parent_id"]: p for p in read_json(current / "parents.json")}
        checks[f"{name}_every_unit_parent_consistent"] = all(
            u["parent_id"] in parent_by_id and u["source_refs"] and all(r in parent_by_id[u["parent_id"]]["source_refs"] for r in u["source_refs"])
            for u in units)
        for variant in ["fixed", "hierarchical", "hybrid"]:
            chunks = [json.loads(line) for line in (current / f"chunks_{variant}.jsonl").read_text(encoding="utf-8").splitlines()]
            checks[f"{name}_{variant}_coverage_access_pages_cap"] = refs == {r for c in chunks for r in c["source_refs"]} and all(
                c["pages"] and c["plan_required"] == manifest["plan_required"] and c["source_type"] == manifest["source_type"]
                and (variant == "hierarchical" or c["token_count"] <= 512) for c in chunks)
            if name == "icai":
                checks[f"icai_{variant}_no_header_in_heading_prefix"] = all("SUPPLY UNDER GST" not in c["headings"] for c in chunks)
        detail[name] = {"old_config_id": read_json(baseline / "chunk_report.json")["config_id"], "new_config_id": report["config_id"],
                        "old_parents": len(read_json(baseline / "parents.json")), "new_parents": len(read_json(current / "parents.json")),
                        "refs": len(refs), "chunks": {k: v["chunks"] for k, v in report["variants"].items()}}
    # Firm heading ownership and text serialization must not change in this fix.
    checks["firm_parent_ownership_unchanged"] = ref_owners(FIRM_BASE) == ref_owners(FIRM)
    checks["firm_chunk_content_unchanged"] = all(
        [{k: r[k] for k in ["text", "embedding_text", "headings", "source_refs", "pages", "parent_ids", "token_count"]} for r in map(json.loads, (FIRM_BASE / f"chunks_{v}.jsonl").read_text(encoding="utf-8").splitlines())]
        == [{k: r[k] for k in ["text", "embedding_text", "headings", "source_refs", "pages", "parent_ids", "token_count"]} for r in map(json.loads, (FIRM / f"chunks_{v}.jsonl").read_text(encoding="utf-8").splitlines())]
        for v in ["fixed", "hierarchical", "hybrid"])
    freeze = read_json(FIRM_BASE / "experiment_freeze.json")
    checks["original_freeze_artifacts_and_snapshot_preserved"] = all(digest(FIRM_BASE / name) == value for name, value in freeze["artifact_sha256"].items()) and frozen_code_preserved(FIRM_BASE, freeze, ROOT / "src/gst_rag")
    if args.require_retrieval:
        plus = read_json(ICAI / "benchmark_jina_dev_child_plus_all_icai_v03.json")
        pro = read_json(ICAI / "benchmark_jina_dev_child_pro_hybrid_icai_v03.json")
        parent = read_json(ICAI / "benchmark_jina_dev_parent_plus_hybrid_icai_v03.json")
        neighbors = read_json(ICAI / "benchmark_jina_dev_neighbors_plus_hybrid_icai_v03.json")
        old_run = read_json(ICAI_BASE / "benchmark_jina_dev_child_plus_all_icai_v02.json")
        checks["same_icai_development_labels_before_after"] = all(r["question_set_sha256"] == old_run["question_set_sha256"] == digest(ROOT / "data/benchmark/icai_topic_questions.json") for r in [plus, pro, parent, neighbors])
        checks["retrieval_runs_use_new_config_and_same_budget"] = all(r["config_id"] == detail["icai"]["new_config_id"] and r["split"] == "dev" and r["context_budget"] == 2048 and r["top_k"] == 10 for r in [plus, pro, parent, neighbors])
        checks["plus_pro_hybrid_hits_and_context_match"] = all(a["hits"] == b["hits"] and a["context"] == b["context"] for a, b in zip(plus["variants"]["hybrid"]["rows"], pro["variants"]["hybrid"]["rows"], strict=True))
        checks["hybrid_child_and_parent_complete_on_13_answerable"] = all(
            len(rows := [r for r in run["variants"]["hybrid"]["rows"] if r["expected"] == "answer"]) == 13
            and all(r["complete_at_10"] and r["context_evidence_recall"] == 1 for r in rows) for run in [plus, parent])
        checks["mixed_access_smoke_passed"] = read_json(ICAI / "mixed_access_smoke.json")["status"] == "passed"
        old_firm = read_json(FIRM_BASE / "benchmark_jina_dev_child_pro_all_source_regressions.json")
        firm = read_json(FIRM / "benchmark_jina_dev_child_pro_all_source_regressions.json")
        fields = ["question_id", "evidence_recall_at_5", "evidence_recall_at_10", "complete_at_10", "context_evidence_recall"]
        checks["firm_targeted_development_scores_unchanged"] = firm["question_set_sha256"] == old_firm["question_set_sha256"] and all(
            [{f: r[f] for f in fields} for r in firm["variants"][v]["rows"]] == [{f: r[f] for f in fields} for r in old_firm["variants"][v]["rows"]]
            for v in ["fixed", "hierarchical", "hybrid"])
        detail["retrieval_context_complete"] = {name: {v: sum(row["context_evidence_recall"] == 1 for row in stats["rows"]) for v, stats in run["variants"].items()}
            for name, run in [("child", plus), ("parent", parent), ("neighbors", neighbors)]}
    result = {"status": "passed" if all(checks.values()) else "failed", "checks": checks, "detail": detail,
              "scope": "Known-layout structure/integrity checks; source-reviewed manual outline, not automatic generalization, legal validation, or answer accuracy."}
    write_json(ICAI / "structure_repair_verification.json", result)
    print(json.dumps(result, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
