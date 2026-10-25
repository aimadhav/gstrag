"""Page views must not renumber citations or reuse another view's item IDs."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from gst_rag.ingestion import checked_page_range, source_view_id, parse_pdf


class PageRangeContracts(unittest.TestCase):
    def test_range_validation(self):
        self.assertEqual(checked_page_range([70, 79]), (70, 79))
        for value in [(0, 10), (79, 70), (True, 79), (70,), (70, 79.0)]:
            with self.assertRaises(ValueError):
                checked_page_range(value)

    def test_partial_view_id_is_distinct_from_full_document(self):
        checksum = "a" * 64
        self.assertEqual(source_view_id("icai_book", checksum, None), "icai_book-" + "a" * 16)
        self.assertNotEqual(source_view_id("icai_book", checksum, (70, 79)), source_view_id("icai_book", checksum, None))
        self.assertNotEqual(source_view_id("icai_book", checksum, (70, 79)), source_view_id("icai_book", checksum, (71, 79)))

    def test_cached_view_requires_the_same_range(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "example.pdf"
            pdf.write_bytes(b"%PDF-test-only")
            settings = {"ocr": False, "table_structure": True, "device": "cpu", "threads": 4, "page_range": [70, 79]}
            manifest = {"sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "source_type": "icai_book", "settings": settings}
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "docling.json").write_text("{}", encoding="utf-8")
            (root / "document.md").write_text("test placeholder", encoding="utf-8")
            self.assertTrue(parse_pdf(pdf, root, "icai_book", False, False, (70, 79))["cached"])
            with self.assertRaises(ValueError):
                parse_pdf(pdf, root, "icai_book", False, False, (71, 79))
            with self.assertRaises(ValueError):
                parse_pdf(pdf, root, "icai_book", False, False)


if __name__ == "__main__":
    unittest.main()
