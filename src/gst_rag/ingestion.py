"""Docling conversion; preserve raw artifacts before applying chunk filters."""

import hashlib
import importlib.metadata
import json
import platform
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def checked_page_range(page_range):
    if page_range is None:
        return None
    if len(page_range) != 2 or any(type(n) is not int for n in page_range) or not 1 <= page_range[0] <= page_range[1]:
        raise ValueError("Page range must be two positive, increasing PDF page positions")
    return tuple(page_range)


def source_view_id(source_type, checksum, page_range):
    """A partial view shares the PDF fingerprint, not parse-relative item IDs."""
    suffix = f"-p{page_range[0]}-{page_range[1]}" if page_range else ""
    return f"{source_type}-{checksum[:16]}{suffix}"


def parse_pdf(pdf: Path, output: Path, source_type: str, ocr: bool, force: bool, page_range=None):
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise ValueError("Supply an existing PDF file")
    with pdf.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    settings = {"ocr": ocr, "table_structure": True, "device": "cpu", "threads": 4}
    page_range = checked_page_range(page_range)
    if page_range:
        settings["page_range"] = list(page_range)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and not force:
        previous = read_json(manifest_path)
        if (previous["sha256"], previous["source_type"], previous["settings"]) != (checksum, source_type, settings):
            raise ValueError("Input/settings differ from cached parse; choose a new output directory or --force")
        if not all((output / name).is_file() for name in ["docling.json", "document.md"]):
            raise ValueError("Incomplete cached conversion; rerun with --force")
        return {"cached": True, **previous}

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import AcceleratorOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
    options.accelerator_options = AcceleratorOptions(num_threads=4, device="cpu")
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    started = time.perf_counter()
    result = converter.convert(pdf, **({"page_range": page_range} if page_range else {}))
    status = str(result.status.value)
    if status != "success":
        raise RuntimeError(f"Conversion did not complete successfully: {status}. No valid parse manifest written.")
    doc = result.document
    converted_pages = sorted(doc.pages)
    if page_range and converted_pages != list(range(page_range[0], page_range[1] + 1)):
        raise ValueError("Converted pages do not match the requested original PDF page positions")
    output.mkdir(parents=True, exist_ok=True)
    doc.save_as_json(output / "docling.json")
    doc.save_as_markdown(output / "document.md")
    items = [item for item, _ in doc.iterate_items()]
    labels = Counter(str(item.label.value) for item in items if hasattr(item, "label"))
    manifest = {
        "schema_version": "1.1", "document_id": source_view_id(source_type, checksum, page_range),
        "source_document_id": source_view_id(source_type, checksum, None),
        "filename": pdf.name, "sha256": checksum, "source_type": source_type,
        "plan_required": "pro" if source_type == "firm_book" else "plus",
        "page_count": result.input.page_count, "parsed_page_count": len(doc.pages),
        "converted_pdf_pages": converted_pages, "settings": settings, "status": status,
        "parse_seconds": round(time.perf_counter() - started, 3),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "versions": {name: importlib.metadata.version(name) for name in ["docling", "docling-core", "torch", "transformers"]},
        "body_labels": dict(labels),
        "note": "PDF page positions are provenance, not verified printed-page labels. No publication date inferred.",
    }
    write_json(manifest_path, manifest)
    return manifest
