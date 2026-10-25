"""Regression tests for source-audit defects, without model downloads or APIs."""

from types import SimpleNamespace
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from gst_rag.chunking import heading_number, parent_headings_for, load_picture_transcriptions, restore_heading_depth
from gst_rag.benchmark import verify_heldout_freeze


class HeadingRepairs(unittest.TestCase):
    def test_trailing_dot_subsections_are_peers_not_nested_notes(self):
        headings = [SimpleNamespace(label="section_header", text=text, level=1, self_ref=f"h{i}", prov=[])
                    for i, text in enumerate(["7.2.9 Ice creams", "7.2.10. Solar EPC", "7.2.11. Various clarifications"])]
        doc = SimpleNamespace(iterate_items=lambda: ((h, 0) for h in headings))
        restore_heading_depth(doc)
        self.assertEqual([h.level for h in headings], [3, 3, 3])


    def test_numbering_accepts_terminal_dot_and_rejects_inline_mentions(self):
        for text in ["7.2.10 Solar", "7.2.10. Solar", " 7.2.10. Solar", "7.2.10."]:
            self.assertEqual(heading_number(text), "7.2.10")
        for text in ["See 7.2.10 for details", "Solar 7.2.10", "7.2.10.. Solar", "7.2.10x Solar", "No number"]:
            self.assertIsNone(heading_number(text))

    def test_parent_boundary_uses_same_numbering_rule(self):
        headings = ["Chapter", "7.2 Composite", "7.2.10. Solar", "Author note"]
        self.assertEqual(parent_headings_for(headings), headings[:3])


class PictureTranscriptionRepairs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "pictures.json"
        self.manifest = {"document_id": "doc", "sha256": "checksum"}
        self.doc = SimpleNamespace(pictures=[SimpleNamespace(self_ref="#/pictures/1", prov=[SimpleNamespace(page_no=21)])])
        self.payload = {**self.manifest, "source_sha256": "checksum", "pictures": [{
            "source_ref": "#/pictures/1", "pages": [21], "text": "Both diagram branches preserved.",
            "review_status": "source_audited", "reviewer_type": "assistant"}]}

    def load(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        return load_picture_transcriptions(self.path, self.manifest, self.doc)

    def test_picture_text_keeps_original_ref_and_page(self):
        self.assertEqual(self.load()["#/pictures/1"]["pages"], [21])

    def test_transcription_for_wrong_pdf_is_rejected(self):
        self.payload["source_sha256"] = "other-pdf"
        with self.assertRaises(ValueError):
            self.load()

    def test_unreviewed_or_empty_transcription_is_rejected(self):
        self.payload["pictures"][0]["review_status"] = "draft"
        with self.assertRaises(ValueError):
            self.load()
        self.payload["pictures"][0].update(review_status="source_audited", text=" ")
        with self.assertRaises(ValueError):
            self.load()

    def test_invented_ref_or_wrong_page_is_rejected(self):
        self.payload["pictures"][0]["pages"] = [20]
        with self.assertRaises(ValueError):
            self.load()
        self.payload["pictures"][0].update(pages=[21], source_ref="#/pictures/999")
        with self.assertRaises(ValueError):
            self.load()


class FrozenEvaluationContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.questions = self.root / "questions.json"
        self.questions.write_text("{}", encoding="utf-8")
        self.artifact = self.root / "chunks.jsonl"
        self.artifact.write_text("original", encoding="utf-8")
        self.settings = dict(retriever="jina", context_mode="child", context_budget=2048, plan="pro", top_k=10, variant="all")
        self.args = SimpleNamespace(directory=self.root, questions=self.questions, split="heldout", **self.settings)
        self.report = {"config_id": "fixed-config"}
        self.freeze = {"config_id": "fixed-config", "question_set_sha256": hashlib.sha256(self.questions.read_bytes()).hexdigest(),
            "artifact_sha256": {"chunks.jsonl": hashlib.sha256(self.artifact.read_bytes()).hexdigest()}, "heldout_settings": self.settings}

    def save(self):
        (self.root / "experiment_freeze.json").write_text(json.dumps(self.freeze), encoding="utf-8")

    def test_heldout_requires_freeze(self):
        with self.assertRaises(ValueError):
            verify_heldout_freeze(self.args, self.report)

    def test_frozen_run_accepts_matching_inputs(self):
        self.save()
        verify_heldout_freeze(self.args, self.report)

    def test_changed_artifacts_or_settings_are_rejected(self):
        self.save()
        self.args.context_budget = 4096
        with self.assertRaises(ValueError):
            verify_heldout_freeze(self.args, self.report)
        self.args.context_budget = 2048
        self.artifact.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            verify_heldout_freeze(self.args, self.report)

    def test_existing_heldout_result_cannot_be_overwritten(self):
        self.save()
        (self.root / "benchmark_jina_heldout_child_pro_all.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            verify_heldout_freeze(self.args, self.report)


if __name__ == "__main__":
    unittest.main()
