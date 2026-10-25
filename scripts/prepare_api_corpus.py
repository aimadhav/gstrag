"""Create an app snapshot without changing experimental artifacts or original PDFs."""

import hashlib
import shutil
from pathlib import Path

from gst_rag.ingestion import read_json, write_json
from build_notification_sample import load_books, ROOT, OUTPUT
from prepare_notifications import SAMPLES


def main():
    firm_dir = ROOT / "data/processed/chapter7_structure_v03"
    firm = read_json(firm_dir / "manifest.json")
    # The supplied original remains unchanged. Make an app-owned local copy so
    # the API can serve ONLY registered PDFs under its data/sources directory.
    original = Path.home() / "Downloads" / firm["filename"]
    target = ROOT / "data/sources/firm" / firm["filename"]
    if not target.exists():
        if hashlib.sha256(original.read_bytes()).hexdigest() != firm["sha256"]:
            raise ValueError("Original firm PDF does not match the audited conversion")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    sources = []
    def add(directory, pdf, name):
        manifest = read_json(directory / "manifest.json")
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != manifest["sha256"]:
            raise ValueError("Registered PDF no longer matches parsed evidence")
        sources.append({"document_id": manifest["document_id"], "source_type": manifest["source_type"], "name": name,
            "page_count": manifest["page_count"], "sha256": manifest["sha256"], "pdf_path": pdf.relative_to(ROOT).as_posix()})
    add(firm_dir, target, "Firm GST book - Chapter 7")
    icai = ROOT / "data/processed/icai_composite_mixed_p70_79_v03"
    add(icai, ROOT / "data/sources/icai" / read_json(icai / "manifest.json")["filename"], "ICAI GST - Supply under GST, Chapter 2")
    for sample in SAMPLES:
        add(ROOT / "data/processed/notifications_v01" / sample["slug"], ROOT / "data/sources/notifications" / (sample["slug"] + ".pdf"),
            f"Notification {sample['number']} Central Tax (Rate)")
    bundle = {"version": "api-corpus-v1", "records": load_books() + read_json(OUTPUT / "notification_records.json"),
              "links": read_json(OUTPUT / "book_notification_links.json"), "sources": sources}
    destination = ROOT / "data/app/corpus.json"
    if destination.exists() and read_json(destination) != bundle:
        raise ValueError("Existing app corpus differs; explicitly version/review the replacement")
    write_json(destination, bundle)
    print(f"App snapshot ready: {len(bundle['records'])} records, {len(sources)} registered PDFs. No experiment artifacts changed.")


if __name__ == "__main__":
    main()
