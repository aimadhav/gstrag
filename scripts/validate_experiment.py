"""Check actual artifacts and make a local, readable evidence-review sheet.

Does not embed, run retrieval, or expose any credentials.
"""

import json
import argparse
from pathlib import Path

from gst_rag.benchmark import group_covered
from gst_rag.ingestion import read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("data/processed/chapter7"))
    parser.add_argument("--questions", type=Path, default=Path("data/benchmark/chapter7_questions.source_audited_v2.json"))
    args = parser.parse_args()
    root = args.directory
    manifest = read_json(root / "manifest.json")
    report = read_json(root / "chunk_report.json")
    units = read_json(root / "units.json")
    parents = read_json(root / "parents.json")
    questions = read_json(args.questions)
    source_refs = {r for u in units for r in u["source_refs"]}
    permitted_pages = set(manifest.get("converted_pdf_pages", range(1, manifest["page_count"] + 1)))
    parent_ids = {p["parent_id"] for p in parents}
    assert questions["document_id"] == manifest["document_id"]
    for variant in ["fixed", "hierarchical", "hybrid"]:
        chunks = [json.loads(line) for line in (root / f"chunks_{variant}.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len({c["chunk_id"] for c in chunks}) == len(chunks)
        assert {r for c in chunks for r in c["source_refs"]} == source_refs
        for chunk in chunks:
            assert chunk["config_id"] == report["config_id"]
            assert chunk["pages"] and set(chunk["pages"]) <= permitted_pages
            assert set(chunk["parent_ids"]) <= parent_ids
            assert chunk["plan_required"] == manifest["plan_required"]
            if variant != "hierarchical":
                assert chunk["token_count"] <= report["config"]["max_tokens"]
    for parent in parents:
        assert set(parent["source_refs"]) <= source_refs
        assert parent["plan_required"] == manifest["plan_required"]
    for path in root.glob("benchmark_jina_dev_*.json"):
        run = read_json(path)
        assert run["config_id"] == report["config_id"]
        for variant in run["variants"].values():
            assert all(row["context_tokens"] <= run["context_budget"] for row in variant["rows"])
    lines = ["# Source audited question and evidence review", "",
             f"Label status: {questions['annotation_status']}; {len(questions['questions'])} questions. These are retrieval labels, not approved legal answers or an independent expert review.", "",
             "This source-label check does not score retrieval. Consult saved benchmark runs for split evaluation status; do not tune on held-out scores.", ""]
    for question in questions["questions"]:
        lines += [f"## {question['id']} ({question['split']}, {question['category']})", "", question["question"], "",
                  f"Expected behavior: `{question['expected']}`.", ""]
        for index, group in enumerate(question["evidence_groups"], 1):
            assert group_covered(group, units), f"Missing source excerpt for {question['id']}"
            lines += [f"Required evidence group {index}:", ""]
            for alternative in group:
                assert group_covered([alternative], units), f"Missing alternative for {question['id']}"
                pages = sorted({p for u in units if set(u["source_refs"]) & set(alternative["source_refs"]) for p in u["pages"]})
                lines += [f"PDF pages {pages}; source refs `{', '.join(alternative['source_refs'])}`.", "", f"> {alternative['quote']}", ""]
        lines += [f"Assistant source audit: {question.get('source_audit', {}).get('note', questions.get('annotation_note', 'See dataset annotation notes.'))}", ""]
    review_path = root / f"question_review_{args.questions.stem}.md"
    review_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": "passed", "canonical_refs": len(source_refs), "parents": len(parents),
                      "questions": len(questions["questions"]), "review_sheet": str(review_path)}, indent=2))


if __name__ == "__main__":
    main()
