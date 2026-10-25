"""Pinecone -> mandatory updates -> private review packet, entirely offline."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from gst_rag.auth import Settings
from gst_rag.ingestion import write_json
from gst_rag.service import RetrievalService, Worker
from gst_rag.store import Store
from gst_rag.vector_store import PineconeStore, Snapshot
from test_retrieval_contracts import WordTokenizer
from test_vector_store import Session, VECTOR, bundle


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = bundle()
        for record in self.bundle["records"]:
            record.update(text=record["embedding_text"], headings=[], source_refs=["#/texts/0"], parent_ids=[])
        self.bundle["records"][2]["notification"] = {"key": "central_tax_rate:1/2023", "topic_id": "pencil_sharpeners",
            "issued_on": "2023-01-01", "effective_from": "2023-03-01"}
        self.bundle["sources"] = [{"document_id": r["document_id"], "source_type": r["source_type"], "name": r["source_type"],
                                  "page_count": 2} for r in self.bundle["records"]]
        write_json(self.root / "data/app/corpus.json", self.bundle)
        self.settings = Settings(self.root, self.root / "db", "x" * 32, retriever="pinecone", worker_enabled=False)
        self.remote = PineconeStore(Snapshot(self.bundle), key="synthetic", session=Session())
        self.remote.connect()
        self.remote.upsert([VECTOR] * 3)
        self.remote.session.calls.clear()
        self.jina_calls = []

        class FakeJina:
            def encode(inner, texts, task):
                self.jina_calls.append((texts, task))
                return np.array([VECTOR] * len(texts))

        self.enterContext(patch("transformers.AutoTokenizer.from_pretrained", return_value=WordTokenizer()))
        self.enterContext(patch("gst_rag.service.app_jina", return_value=FakeJina()))
        self.enterContext(patch("gst_rag.service.PineconeStore", return_value=self.remote))
        self.service = RetrievalService(self.settings)

    def test_service_only_embeds_question_and_enforces_plus(self):
        packet = self.service.retrieve("synthetic question", ["pencil_sharpeners"], "2023-03-01", "plus")
        self.assertEqual(self.jina_calls, [(["synthetic question"], "retrieval.query")])
        self.assertEqual({c["source_type"] for c in packet["citations"]}, {"icai_book", "notification"})
        self.assertEqual(packet["retriever"], "pinecone")
        self.assertEqual(packet["status"], "review_required")
        self.assertFalse(packet["current_law_verified"])
        self.assertFalse(packet["history_used_as_evidence"])

    def test_required_notification_included_even_when_search_omits_it(self):
        original = self.remote.search
        self.remote.search = lambda *a, **kw: [(r, score) for r, score in original(*a, **kw) if r["source_type"] != "notification"]
        packet = self.service.retrieve("synthetic", ["pencil_sharpeners"], "2023-03-01", "plus")
        self.assertEqual(packet["citations"][0]["source_type"], "notification")

    def test_future_notification_removed_even_if_semantically_retrieved(self):
        packet = self.service.retrieve("synthetic", ["pencil_sharpeners"], "2023-02-28", "pro")
        self.assertNotIn("notification", {c["source_type"] for c in packet["citations"]})
        self.assertEqual(packet["notification_keys"], [])

    def test_private_citations_keep_page_and_pdf_link(self):
        packet = self.service.retrieve("synthetic", ["pencil_sharpeners"], "2023-03-01", "pro")
        self.assertTrue(any(c["source_type"] == "firm_book" for c in packet["citations"]))
        self.assertTrue(all(c["pages"] == [1, 2] and c["pdf_url"].startswith("/admin/sources/") for c in packet["citations"]))
        self.assertLessEqual(packet["context_tokens"], 2048)

    def test_initialization_rejects_incomplete_snapshot(self):
        self.remote.session.rows["icai_books"].clear()
        with self.assertRaises(ValueError):
            RetrievalService(self.settings)

    def test_provider_failure_stays_private_without_keyword_fallback(self):
        self.remote.search = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("PRIVATE_PROVIDER_DETAIL"))
        store = Store(self.settings.db_path)
        user = store.create_user("synthetic", "hash-not-used-in-this-test")
        row = store.enqueue(user["id"], "synthetic", "2023-03-01", ["pencil_sharpeners"], None)
        worker = Worker(store, lambda: self.service)
        worker.run_once()
        result = store.query(row["id"], user["id"])
        packet = json.loads(result["private_packet"])
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(packet["review_reasons"], ["retrieval_unavailable"])
        self.assertEqual(packet["citations"], [])
        self.assertNotIn("PRIVATE_PROVIDER_DETAIL", result["private_packet"])


if __name__ == "__main__":
    unittest.main()
