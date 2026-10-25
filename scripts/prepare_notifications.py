"""Download three original official PDFs and parse with the existing Docling flow.

Historical development corpus, not a complete or current-law notification feed.
No public redistribution and no external embedding call in this command.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from gst_rag.ingestion import parse_pdf, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = [
    {"slug": "ctr_24_2018", "number": "24/2018", "expected_pages": 4,
     "listing_url": "https://gstcouncil.gov.in/node/4494",
     "url": "https://gstcouncil.gov.in/sites/default/files/2024-05/download_2024-05-17t160748.759.pdf"},
    {"slug": "ctr_08_2021", "number": "8/2021", "expected_pages": 6,
     "listing_url": "https://www.gstcouncil.gov.in/en/node/4546",
     "url": "https://cbic-gst.gov.in/pdf/central-tax-rate/notfctn-08-2021-cgst-rate.pdf"},
    {"slug": "ctr_03_2023", "number": "3/2023", "expected_pages": 1,
     "listing_url": "https://www.gstcouncil.gov.in/en/node/4578",
     "url": "https://www.gstcouncil.gov.in/sites/default/files/2024-05/03_2023-ctr-eng.pdf"},
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    for sample in SAMPLES:
        source = ROOT / "data/sources/notifications" / (sample["slug"] + ".pdf")
        card_path = source.with_suffix(".source.json")
        if not source.exists():
            with urlopen(Request(sample["url"], headers={"User-Agent": "GST-RAG-Development/0.1"}), timeout=45) as response:
                content = response.read(20_000_001)
                if len(content) > 20_000_000 or not content.startswith(b"%PDF-"):
                    raise ValueError("Source is not a bounded original PDF")
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        if card_path.exists():
            if read_json(card_path)["sha256"] != checksum:
                raise ValueError("Notification download changed; review as a new source")
        else:
            write_json(card_path, {**sample, "sha256": checksum, "bytes": source.stat().st_size,
                "download_date": "2026-10-21", "source_type": "notification", "plan_required": "plus",
                "status": "downloaded_for_source_review", "usage_note": "Original official notification PDFs retained locally; no public redistribution rights inferred from availability. Not a complete current-law corpus."})
        if not args.download_only:
            result = parse_pdf(source, ROOT / "data/processed/notifications_v01" / sample["slug"], "notification", False, False)
            if result["page_count"] != sample["expected_pages"]:
                raise ValueError("Unexpected notification length; review source before proceeding")
            print(json.dumps({"slug": sample["slug"], "pages": result["page_count"], "document_id": result["document_id"], "status": result["status"]}))
        else:
            print(json.dumps({"slug": sample["slug"], "sha256": checksum, "bytes": source.stat().st_size}))


if __name__ == "__main__":
    main()
