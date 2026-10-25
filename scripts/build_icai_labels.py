"""Bind source-reviewed question requirements to actual Docling source IDs.

No retrieval scores are read. Failed quote mapping stops, rather than silently
weakening evidence labels. The private question specification was authored after
reading the original PDF, before retrieval scoring.
"""

import json
from pathlib import Path

from gst_rag.benchmark import normalize, group_covered
from gst_rag.ingestion import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/icai_composite_mixed_p70_79"


def main():
    spec = read_json(ROOT / "data/benchmark/icai_topic_question_spec.json")
    manifest = read_json(DATA / "manifest.json")
    doc = read_json(DATA / "docling.json")
    units = read_json(DATA / "units.json")
    texts = {t["self_ref"]: t["text"] for t in doc["texts"]}
    questions = []
    for q in spec["questions"]:
        groups = []
        for fact in q["required"]:
            alternatives = []
            seen = set()
            for unit in units:
                if not set(fact["pages"]) & set(unit["pages"]) or normalize(fact["quote"]) not in normalize(unit["text"]):
                    continue
                for ref in unit["source_refs"]:
                    original = texts.get(ref, unit["text"] if ref.startswith("#/tables/") else "")
                    if ref not in seen and normalize(fact["quote"]) in normalize(original):
                        alternatives.append({"source_refs": [ref], "quote": fact["quote"]})
                        seen.add(ref)
            if not alternatives:
                raise ValueError(f"Unmapped original PDF fact {q['id']}: {fact['quote']}")
            assert group_covered(alternatives, units)
            groups.append(alternatives)
        questions.append({"id": q["id"], "split": "dev", "category": q["category"], "expected": q["expected"],
            "question": q["question"], "evidence_groups": groups,
            "source_audit": {"reviewer_type": "assistant", "date": "2026-10-21", "pdf_pages": sorted({p for fact in q["required"] for p in fact["pages"]}),
                "note": "Source-faithful development check, not current-law advice or independently expert-labeled evidence."}})
    output = {"document_id": manifest["document_id"], "annotation_status": "source_audited", "annotation_version": "icai-topic-dev-v1",
        "annotation_note": spec["note"], "reviewed_pdf_pages": spec["reviewed_pdf_pages"], "questions": questions}
    path = ROOT / "data/benchmark/icai_topic_questions.json"
    write_json(path, output)
    print(json.dumps({"saved": str(path), "questions": len(questions), "answerable": sum(bool(q["evidence_groups"]) for q in questions)}, indent=2))


if __name__ == "__main__":
    main()
