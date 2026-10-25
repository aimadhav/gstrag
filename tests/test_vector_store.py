"""Synthetic offline adapter tests: no account/key, network or private PDF needed."""

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from gst_rag.auth import Settings
from gst_rag.vector_store import API_VERSION, DIMENSION, PineconeStore, Snapshot, namespaces_for

VECTOR = [1.] + [0.] * (DIMENSION - 1)


def bundle():
    return {"records": [{"chunk_id": str(i), "document_id": "doc-" + str(i), "source_type": source,
        "plan_required": "pro" if source == "firm_book" else "plus", "pages": [1, 2],
        "embedding_text": "SYNTHETIC_PRIVATE_TEXT_" + source} for i, source in enumerate(["icai_book", "firm_book", "notification"])],
        "sources": [], "links": []}


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.ok = 200 <= status < 400

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return copy.deepcopy(self.body)


class Session:
    def __init__(self):
        self.calls, self.rows = [], {}
        self.info = {"dimension": DIMENSION, "metric": "cosine", "vector_type": "dense",
            "status": {"ready": True}, "host": "synthetic.svc.test.pinecone.io", "tags": {"application": "gst-rag"}}
        self.response = None
        self.mutate = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        if self.response:
            return self.response
        body = kwargs["json"] or {}
        if "/indexes" in url:
            return Response(self.info)
        if url.endswith("/vectors/upsert"):
            ns = body["namespace"]
            self.rows.setdefault(ns, {}).update({r["id"]: r for r in body["vectors"]})
            return Response({"upsertedCount": len(body["vectors"])})
        if url.endswith("/query"):
            ns = body["namespace"]
            matches = [{"id": r["id"], "score": .5, "metadata": r["metadata"]}
                       for r in self.rows.get(ns, {}).values()
                       if r["metadata"]["corpus_id"] == body["filter"]["corpus_id"]["$eq"]]
            result = {"namespace": ns, "matches": matches[:body["topK"]], "usage": {"read_units": 1}}
        elif url.endswith("/vectors/fetch"):
            params = kwargs["params"]
            ns = next(v for k, v in params if k == "namespace")
            ids = [v for k, v in params if k == "ids"]
            result = {"namespace": ns, "vectors": {i: self.rows.get(ns, {})[i] for i in ids if i in self.rows.get(ns, {})},
                      "usage": {"readUnits": 1}}
        else:
            raise AssertionError("Unexpected endpoint")
        if self.mutate:
            self.mutate(result)
        return Response(result)


class VectorTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = Snapshot(bundle())
        self.session = Session()
        self.store = PineconeStore(self.snapshot, key="synthetic-not-a-real-key", session=self.session)
        self.store.connect()
        self.store.upsert([VECTOR] * 3)
        self.session.calls.clear()

    def test_plus_requests_only_two_allowed_namespaces(self):
        result = self.store.search(VECTOR, "plus")
        self.assertEqual([c[2]["json"]["namespace"] for c in self.session.calls], ["icai_books", "notifications"])
        self.assertEqual({r["source_type"] for r, _ in result}, {"icai_book", "notification"})

    def test_pro_requests_three_namespaces(self):
        self.assertEqual(len(self.store.search(VECTOR, "pro")), 3)
        self.assertEqual([c[2]["json"]["namespace"] for c in self.session.calls], ["icai_books", "firm_books", "notifications"])

    def test_downgrade_same_store_never_queries_firm_again(self):
        self.store.search(VECTOR, "pro")
        self.session.calls.clear()
        self.store.search(VECTOR, "plus")
        self.assertNotIn("firm_books", [c[2]["json"]["namespace"] for c in self.session.calls])

    def test_invalid_plan_rejected_before_request(self):
        for plan in ["admin", "enterprise", "Pro", "", None]:
            with self.assertRaises(ValueError):
                self.store.search(VECTOR, plan)
        self.assertEqual(self.session.calls, [])

    def test_metadata_filter_and_protocol_are_pinned(self):
        self.store.search(VECTOR, "plus")
        for _, _, kwargs in self.session.calls:
            self.assertEqual(kwargs["headers"]["X-Pinecone-Api-Version"], API_VERSION)
            self.assertEqual(kwargs["json"]["filter"]["corpus_id"]["$eq"], self.snapshot.corpus_id)
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["timeout"], (5, 30))

    def test_no_passage_text_in_remote_vectors(self):
        for rows in self.session.rows.values():
            for row in rows.values():
                self.assertNotIn("SYNTHETIC_PRIVATE_TEXT", str(row))
                self.assertEqual(row["metadata"]["pages"], ["1", "2"])

    def test_hydration_uses_local_full_record(self):
        record, _ = self.store.search(VECTOR, "plus")[0]
        self.assertIs(record, self.snapshot.records[0])
        self.assertIn("SYNTHETIC_PRIVATE_TEXT", record["embedding_text"])

    def test_unknown_id_fails_closed(self):
        self.session.mutate = lambda result: result["matches"][0].update(id="unknown")
        with self.assertRaisesRegex(ValueError, "failed closed"):
            self.store.search(VECTOR, "plus")

    def test_metadata_tampering_fails_closed(self):
        self.session.mutate = lambda result: result["matches"][0]["metadata"].update(pages=["999"])
        with self.assertRaisesRegex(ValueError, "failed closed"):
            self.store.search(VECTOR, "plus")

    def test_firm_record_in_allowed_namespace_fails_closed(self):
        firm_id = self.snapshot.vector_id(self.snapshot.records[1])
        firm_row = self.session.rows["firm_books"][firm_id]
        self.session.rows["icai_books"] = {firm_id: firm_row}
        with self.assertRaisesRegex(ValueError, "failed closed"):
            self.store.search(VECTOR, "plus")

    def test_wrong_namespace_response_fails_closed(self):
        self.session.mutate = lambda result: result.update(namespace="firm_books")
        with self.assertRaisesRegex(ValueError, "namespace"):
            self.store.search(VECTOR, "plus")

    def test_duplicate_match_rejected(self):
        self.session.mutate = lambda result: result["matches"].append(result["matches"][0])
        with self.assertRaisesRegex(ValueError, "failed closed"):
            self.store.search(VECTOR, "plus")

    def test_nonfinite_score_rejected(self):
        self.session.mutate = lambda result: result["matches"][0].update(score=float("nan"))
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            self.store.search(VECTOR, "plus")

    def test_snapshot_changes_if_text_pages_or_plan_sources_change(self):
        for key, value in [("embedding_text", "changed"), ("pages", [9]), ("document_id", "changed")]:
            changed = bundle()
            changed["records"][0][key] = value
            self.assertNotEqual(Snapshot(changed).corpus_id, self.snapshot.corpus_id)
        self.assertEqual(Snapshot(bundle()).corpus_id, self.snapshot.corpus_id)

    def test_duplicate_or_misclassified_chunks_rejected(self):
        changed = bundle()
        changed["records"].append(changed["records"][0])
        with self.assertRaises(ValueError):
            Snapshot(changed)
        changed = bundle()
        changed["records"][1]["plan_required"] = "plus"
        with self.assertRaises(ValueError):
            Snapshot(changed)

    def test_stale_snapshot_is_filtered_out(self):
        row = next(iter(self.session.rows["icai_books"].values()))
        row["metadata"]["corpus_id"] = "old-snapshot"
        result = self.store.search(VECTOR, "plus")
        self.assertEqual({r["source_type"] for r, _ in result}, {"notification"})

    def test_repeated_upsert_is_idempotent(self):
        self.store.upsert([VECTOR] * 3)
        self.assertEqual(sum(map(len, self.session.rows.values())), 3)

    def test_verify_fetches_every_expected_vector(self):
        counts = self.store.verify_records([VECTOR] * 3)
        self.assertEqual(counts, {"icai_books": 1, "firm_books": 1, "notifications": 1})

    def test_verify_detects_missing_record(self):
        self.session.rows["firm_books"].clear()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.store.verify_records()

    def test_verify_detects_modified_embedding(self):
        next(iter(self.session.rows["firm_books"].values()))["values"] = [0., 1.] + [0.] * (DIMENSION - 2)
        with self.assertRaisesRegex(ValueError, "embedding differs"):
            self.store.verify_records([VECTOR] * 3)

    def test_all_vectors_validated_before_first_upsert(self):
        for bad in [[], [1.] * 10, [float("nan")] * DIMENSION, [0.] * DIMENSION]:
            with self.assertRaises(ValueError):
                self.store.upsert([VECTOR, VECTOR, bad])
        self.assertEqual(self.session.calls, [])

    def test_invalid_query_vector_or_k_rejected(self):
        with self.assertRaises(ValueError):
            self.store.search([1.], "plus")
        for k in [0, -1, 101, True]:
            with self.assertRaises(ValueError):
                self.store.search(VECTOR, "plus", k)
        self.assertEqual(self.session.calls, [])

    def test_transport_and_provider_error_bodies_redacted(self):
        for response in [requests.Timeout("PRIVATE_KEY_REQUEST"), Response({"error": "PRIVATE_KEY_REQUEST"}, 401),
                         Response(ValueError("PRIVATE_KEY_REQUEST")), Response({}, 307)]:
            self.session.response = response
            with self.assertRaises(RuntimeError) as caught:
                self.store.search(VECTOR, "plus")
            self.assertNotIn("PRIVATE_KEY_REQUEST", str(caught.exception))

    def test_incompatible_or_unowned_index_untouched(self):
        for key, value in [("dimension", 1536), ("metric", "dotproduct"), ("vector_type", "sparse"),
                           ("embed", {"model": "other"}), ("tags", {})]:
            original = copy.deepcopy(self.session.info)
            self.session.info[key] = value
            with self.assertRaises(ValueError):
                self.store.connect()
            self.session.info = original
        self.assertTrue(all(c[0] == "GET" for c in self.session.calls))

    def test_unready_index_rejected(self):
        self.session.info["status"]["ready"] = False
        with self.assertRaisesRegex(ValueError, "not ready"):
            self.store.connect()

    def test_host_cannot_redirect_key_to_arbitrary_server(self):
        for host in ["evil.example", "x.pinecone.io.evil.example", "https://x.svc.pinecone.io", "x.svc.pinecone.io/path", "x@x.svc.pinecone.io"]:
            self.session.info["host"] = host
            with self.assertRaises(ValueError):
                self.store.connect()
        self.assertTrue(all(c[0] == "GET" for c in self.session.calls))

    def test_create_is_explicit_and_uses_small_serverless_configuration(self):
        self.store.create()
        body = self.session.calls[-1][2]["json"]
        self.assertEqual(body["spec"], {"serverless": {"cloud": "aws", "region": "us-east-1"}})
        self.assertEqual(body["deletion_protection"], "enabled")
        self.assertEqual(body["dimension"], DIMENSION)

    def test_missing_key_bad_name_and_unconnected_data_are_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                PineconeStore(self.snapshot)
        for name in ["../evil", "UPPER", "-bad", "bad/", "x" * 46]:
            with self.assertRaises(ValueError):
                PineconeStore(self.snapshot, name, key="fake")
        store = PineconeStore(self.snapshot, key="fake", session=self.session)
        with self.assertRaises(ValueError):
            store.search(VECTOR, "plus")

    def test_settings_accept_pinecone_without_changing_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(Settings(Path(tmp), Path(tmp) / "db", "x" * 32).retriever, "bm25")
            self.assertEqual(Settings(Path(tmp), Path(tmp) / "db", "x" * 32, retriever="pinecone").retriever, "pinecone")


if __name__ == "__main__":
    unittest.main()
