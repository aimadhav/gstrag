"""Rebuild into new directories using an explicitly reviewed ICAI outline.

No fresh PDF conversion, no API calls, no rewriting historical chunks/scores.
This small source-specific review deliberately does not claim generic inference.
"""

import hashlib
import shutil
from pathlib import Path

from gst_rag.chunking import build_variants
from gst_rag.ingestion import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/processed/icai_composite_mixed_p70_79"
OUTPUT = ROOT / "data/processed/icai_composite_mixed_p70_79_v03"
FIRM_BASE = ROOT / "data/processed/chapter7_repaired"
FIRM_OUTPUT = ROOT / "data/processed/chapter7_structure_v03"
REVIEW = ROOT / "data/audit/icai_composite_mixed_outline_review.json"
EXPECTED_PARSE = "31ea20229d1b345d05371aca52acb1d93dc166c8c78bf263b984d95ba977914c"


def prepare(baseline, destination):
    destination.mkdir(parents=True, exist_ok=True)
    # Copy only immutable conversion inputs and the content-addressed API cache.
    for name in ["manifest.json", "docling.json", "document.md", "jina_cache.json"]:
        source, target = baseline / name, destination / name
        if source.exists() and not target.exists():
            shutil.copy2(source, target)
        elif source.exists() and name != "jina_cache.json" and source.read_bytes() != target.read_bytes():
            raise ValueError(f"Existing conversion input differs: {target}")


def create_review():
    if hashlib.sha256((BASE / "docling.json").read_bytes()).hexdigest() != EXPECTED_PARSE:
        raise ValueError("Reviewed anchors were authored for a different Docling parse")
    manifest, doc = read_json(BASE / "manifest.json"), read_json(BASE / "docling.json")
    # (Docling text index, outline level, starts a parent). Body headings only.
    # Main section=1, major topic=2, local clarification=3, subheading=3.
    outline = [(3, 1, True), (4, 2, True), (12, 2, True), (25, 3, False),
               (69, 3, True), (79, 3, True), (81, 3, True), (83, 3, True),
               (87, 3, True), (110, 2, True), (97, 3, False), (129, 2, True)]
    headings = [{"source_ref": f"#/texts/{i}", "text": doc["texts"][i]["text"],
                 "pages": sorted({p["page_no"] for p in doc["texts"][i]["prov"]}),
                 "level": level, "parent_boundary": boundary} for i, level, boundary in outline]
    moves = [
        {"source_refs": ["#/texts/97", "#/groups/5", "#/texts/100"], "anchor": "#/texts/110", "position": "after", "page": 77,
         "reason": "PDF image: mixed-supply definition sits below the mixed-supplies title, not before the cinema continuation."},
        {"source_refs": ["#/texts/101"], "anchor": "#/texts/110", "position": "before", "page": 77,
         "reason": "Footnote 38 is referenced by cinema text #/texts/109, not by the mixed-supply definition."},
    ]
    for footnote, next_heading in [(92, 81), (93, 83), (94, 87)]:
        moves.append({"source_refs": [f"#/texts/{footnote}"], "anchor": f"#/texts/{next_heading}",
                      "position": "before", "page": 76,
                      "reason": "Source-checked footnote marker binds this circular reference to the preceding food, bus-body, or retreading topic, not cinema."})
    review = {"document_id": manifest["document_id"], "source_sha256": manifest["sha256"], "docling_sha256": EXPECTED_PARSE,
              "review_status": "source_audited", "reviewer_type": "assistant", "review_date": "2026-10-21",
              "scope": "Complete visual/text review of PDF pages 70-79; manual outline and reading-order correction, not independent legal review or generic layout inference.",
              "headings": headings, "reading_order_moves": moves}
    if REVIEW.exists() and read_json(REVIEW) != review:
        raise ValueError("Existing outline review differs; inspect instead of silently replacing")
    write_json(REVIEW, review)


def main():
    create_review()
    prepare(BASE, OUTPUT)
    prepare(FIRM_BASE, FIRM_OUTPUT)
    for directory, kwargs in [(OUTPUT, {"outline_review": REVIEW}),
                              (FIRM_OUTPUT, {"picture_transcriptions": ROOT / "data/audit/chapter7_picture_transcriptions.json"})]:
        report = build_variants(directory, **kwargs)
        print(directory.name, report["config_id"], report["canonical_units"], "units", report["parents"], "parents",
              {k: v["chunks"] for k, v in report["variants"].items()})


if __name__ == "__main__":
    main()
