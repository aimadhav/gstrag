"""Independent read-only PDF text extraction for the source audit, not ingestion."""

from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path.home() / "Downloads" / "VOL-1_CH07_Concept of Composite and Mixed supply in GST 220724 (1).pdf"


def main():
    output = ROOT / "data/audit/pages"
    output.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(SOURCE)
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text(extraction_mode="layout")
        (output / f"page{number:02d}.txt").write_text(f"PDF PAGE {number}\n\n{text}\n", encoding="utf-8")
    print(f"Extracted all {len(reader.pages)} pages for independent source reading")


if __name__ == "__main__":
    main()
