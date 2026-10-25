"""Parse the reviewed ICAI page range without modifying or renumbering its PDF."""

import json
from pathlib import Path

from gst_rag.ingestion import parse_pdf

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "data/sources/icai/ICAI_Intermediate_GST_Chapter_02_Supply_under_GST_May2026.pdf"
    result = parse_pdf(source, ROOT / "data/processed/icai_composite_mixed_p70_79", "icai_book", False, False, page_range=(70, 79))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
