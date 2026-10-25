"""Layout regressions: no external models, credentials, or network calls."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest

from docling_core.types.doc import DoclingDocument, DocItemLabel, ProvenanceItem, BoundingBox

from gst_rag.chunking import heading_number, parent_headings_for, restore_heading_depth, build_variants
from gst_rag.benchmark import verify_heldout_freeze
from gst_rag.structure import repeated_edge_headers, apply_outline_review
from gst_rag.experiment_history import frozen_code_preserved


class HeaderDetection(unittest.TestCase):
    def doc(self, ys=(92, 92, 92), text="BOOK TITLE", origin="BOTTOMLEFT", xs=(10, 10, 10)):
        items = [NS(label="section_header", text=text, self_ref=f"h{i}", prov=[NS(page_no=i + 1,
                    bbox=NS(t=y, b=y - 2 if origin == "BOTTOMLEFT" else y + 2, l=x, coord_origin=origin))])
                 for i, (x, y) in enumerate(zip(xs, ys))]
        return NS(iterate_items=lambda: ((i, 0) for i in items),
                  pages={i + 1: NS(size=NS(height=100, width=100)) for i in range(len(items))})

    def test_repeated_top_margin_heading_is_furniture(self):
        self.assertEqual(repeated_edge_headers(self.doc()), {"h0", "h1", "h2"})

    def test_top_left_coordinate_origin(self):
        self.assertEqual(len(repeated_edge_headers(self.doc(ys=(8, 8, 8), origin="TOPLEFT"))), 3)

    def test_repeated_body_heading_is_not_furniture(self):
        self.assertFalse(repeated_edge_headers(self.doc(ys=(60, 60, 60))))

    def test_unique_or_twice_repeated_heading_is_kept(self):
        self.assertFalse(repeated_edge_headers(self.doc(ys=(92,))))
        self.assertFalse(repeated_edge_headers(self.doc(ys=(92, 92))))

    def test_numbered_top_margin_section_is_kept(self):
        self.assertFalse(repeated_edge_headers(self.doc(text="4. Actual section")))

    def test_unstable_horizontal_location_is_kept(self):
        self.assertFalse(repeated_edge_headers(self.doc(xs=(10, 30, 10))))


class IntegerOutline(unittest.TestCase):
    def headings(self, texts):
        items = [NS(label="section_header", text=t, level=1, self_ref=str(i), prov=[]) for i, t in enumerate(texts)]
        return items, NS(iterate_items=lambda: ((i, 0) for i in items))

    def test_integer_and_multipart_numbers_share_parser(self):
        self.assertEqual(heading_number("4. Actual section"), "4")
        self.assertEqual(heading_number("1. Local clarification"), "1")
        self.assertEqual(heading_number("7.2.10. Solar"), "7.2.10")
        self.assertIsNone(heading_number("4.. Invalid"))
        self.assertIsNone(heading_number("Example mentions 4."))

    def test_integer_restart_requires_review_not_guessing(self):
        _, doc = self.headings(["4. Main section", "1. Local topic", "2. Another topic"])
        with self.assertRaisesRegex(ValueError, "outline-review"):
            restore_heading_depth(doc)

    def test_duplicate_integer_number_requires_review(self):
        _, doc = self.headings(["4. Main section", "4. Local topic"])
        with self.assertRaises(ValueError):
            restore_heading_depth(doc)

    def test_simple_flat_integer_outline_is_supported(self):
        items, doc = self.headings(["1. One", "2. Two"])
        restore_heading_depth(doc)
        self.assertEqual([i.level for i in items], [1, 1])

    def test_reviewed_boundary_beats_nearest_number(self):
        headings = ["4. Main section", "MIXED SUPPLIES", "Mixed supply means:"]
        self.assertEqual(parent_headings_for(headings, {"4. Main section", "MIXED SUPPLIES"}), headings[:2])


class OutlineReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw, self.path = self.root / "docling.json", self.root / "review.json"
        self.doc = DoclingDocument(name="review_fixture")
        def prov(page):
            return ProvenanceItem(page_no=page, charspan=(0, 1), bbox=BoundingBox(l=10, r=90, t=70, b=60, coord_origin="BOTTOMLEFT"))
        self.h1 = self.doc.add_heading("4. Section", prov=prov(1))
        self.text = self.doc.add_text(label=DocItemLabel.TEXT, text="definition", prov=prov(1))
        self.h2 = self.doc.add_heading("TOPIC", prov=prov(1))
        self.other = self.doc.add_text(label=DocItemLabel.TEXT, text="other page", prov=prov(2))
        self.doc.save_as_json(self.raw)
        self.manifest = {"document_id": "fixture", "sha256": "pdfhash"}
        self.review = {"document_id": "fixture", "source_sha256": "pdfhash",
            "docling_sha256": hashlib.sha256(self.raw.read_bytes()).hexdigest(),
            "review_status": "source_audited", "reviewer_type": "assistant", "headings": [
                {"source_ref": self.h1.self_ref, "text": self.h1.text, "pages": [1], "level": 1, "parent_boundary": True},
                {"source_ref": self.h2.self_ref, "text": self.h2.text, "pages": [1], "level": 2, "parent_boundary": True}],
            "reading_order_moves": [{"source_refs": [self.text.self_ref], "anchor": self.h2.self_ref,
                "position": "after", "page": 1, "reason": "Checked source image"}]}

    def apply(self):
        self.path.write_text(json.dumps(self.review), encoding="utf-8")
        return apply_outline_review(self.doc, self.manifest, self.path, self.raw)

    def test_review_changes_only_levels_and_order_preserving_refs_and_text(self):
        before = [(t.self_ref, t.text, t.prov) for t in self.doc.texts]
        audit = self.apply()
        self.assertEqual(self.h2.level, 2)
        self.assertEqual([r.cref for r in self.doc.body.children], [self.h1.self_ref, self.h2.self_ref, self.text.self_ref, self.other.self_ref])
        self.assertEqual(before, [(t.self_ref, t.text, t.prov) for t in self.doc.texts])
        self.assertEqual(audit["parent_boundaries"], {"4. Section", "TOPIC"})

    def test_wrong_pdf_rejected(self):
        self.review["source_sha256"] = "other"
        with self.assertRaises(ValueError): self.apply()

    def test_changed_parse_rejected(self):
        self.raw.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError): self.apply()

    def test_wrong_heading_text_rejected(self):
        self.review["headings"][0]["text"] = "Wrong heading"
        with self.assertRaises(ValueError): self.apply()

    def test_wrong_heading_page_rejected(self):
        self.review["headings"][0]["pages"] = [2]
        with self.assertRaises(ValueError): self.apply()

    def test_missing_or_duplicate_heading_rejected(self):
        self.review["headings"][1] = self.review["headings"][0]
        with self.assertRaises(ValueError): self.apply()

    def test_unreviewed_profile_rejected(self):
        self.review["review_status"] = "draft"
        with self.assertRaises(ValueError): self.apply()

    def test_cross_page_move_rejected_without_mutation(self):
        self.review["reading_order_moves"][0]["source_refs"] = [self.other.self_ref]
        before = [r.cref for r in self.doc.body.children]
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(before, [r.cref for r in self.doc.body.children])
        self.assertEqual(self.h2.level, 1)

    def test_self_anchored_move_rejected(self):
        self.review["reading_order_moves"][0]["anchor"] = self.text.self_ref
        with self.assertRaises(ValueError): self.apply()


class HistoryChecks(unittest.TestCase):
    def test_chunking_refuses_frozen_directory_before_loading_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "experiment_freeze.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen experiment"):
                build_variants(root)

    def test_archived_snapshot_cannot_authorize_scoring_with_changed_current_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            questions = root / "questions.json"
            questions.write_text("{}", encoding="utf-8")
            snapshot = root / "frozen_code"
            snapshot.mkdir()
            (snapshot / "chunking.py").write_text("original", encoding="utf-8")
            freeze = {"config_id": "config", "question_set_sha256": hashlib.sha256(questions.read_bytes()).hexdigest(),
                "artifact_sha256": {}, "code_sha256": {"chunking.py": hashlib.sha256(b"original").hexdigest()}}
            (root / "experiment_freeze.json").write_text(json.dumps(freeze), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Frozen implementation changed"):
                verify_heldout_freeze(NS(split="heldout", directory=root, questions=questions), {"config_id": "config"})

    def test_snapshot_must_match_original_freeze_even_when_current_code_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, current = root / "frozen_code", root / "current"
            snapshot.mkdir()
            current.mkdir()
            (snapshot / "chunking.py").write_text("original", encoding="utf-8")
            (current / "chunking.py").write_text("changed", encoding="utf-8")
            freeze = {"code_sha256": {"chunking.py": hashlib.sha256(b"original").hexdigest()}}
            self.assertTrue(frozen_code_preserved(root, freeze, current))
            (snapshot / "chunking.py").write_text("tampered", encoding="utf-8")
            self.assertFalse(frozen_code_preserved(root, freeze, current))


if __name__ == "__main__":
    unittest.main()
