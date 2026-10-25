"""Synthetic source approval -> candidate -> verification -> activation tests.

No government source is approved and no live provider/account is used.
"""

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docling_core.types.doc import DoclingDocument, DocItemLabel, ProvenanceItem, BoundingBox
from fastapi.testclient import TestClient

from gst_rag.api import create_app
from gst_rag.auth import PASSWORDS, Settings, issue_token
from gst_rag.ingestion import write_json
from gst_rag.models import NotificationReview, SourceRejection
from gst_rag.notification_publication import Publications, candidate_links, encoded, main, references
from gst_rag.notification_sync import digest, run
from gst_rag.notifications import check_updates
from gst_rag.service import Corpus, RetrievalService, Worker
from gst_rag.store import StateError, Store
from gst_rag.vector_store import PineconeStore, Snapshot
from test_notification_sync import Feed
from test_retrieval_contracts import WordTokenizer
from test_vector_store import Session, VECTOR


TEXTS = ["Notification No. 8/2025-Central Tax (Rate)", "1st January, 2025", "2nd January, 2025",
         "Amends No. 1/2017-Central Tax (Rate)", "Synthetic operative clause: all conditions and exceptions retained."]


def parser_fixture(pdf, directory, metadata):
    directory.mkdir(parents=True, exist_ok=True)
    document = DoclingDocument(name="synthetic_source_review")
    for text in TEXTS:
        document.add_text(label=DocItemLabel.TEXT, text=text,
                          prov=ProvenanceItem(page_no=1, charspan=(0, len(text)),
                                              bbox=BoundingBox(l=0, r=100, t=100, b=90, coord_origin="BOTTOMLEFT")))
    document.save_as_json(directory / "docling.json")
    sha = digest(pdf.read_bytes())
    manifest = {"document_id": "notification-" + sha[:16], "sha256": sha, "source_type": "notification",
                "plan_required": "plus", "page_count": 1}
    write_json(directory / "manifest.json", manifest)
    return {"schema": "notification-staging-v1", "source_sha256": sha, "document_id": manifest["document_id"],
            "candidate": metadata, "page_count": 1, "docling_sha256": digest((directory / "docling.json").read_bytes()),
            "review_status": "pending_source_metadata_review", "eligible_for_retrieval": False,
            "records": [{"text": "UNAPPROVED_SYNTHETIC_DRAFT", "eligible_for_retrieval": False}]}


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.actor = {"id": "synthetic-admin-actor", "role": "admin", "active": True}
        self.publisher = Publications(self.root, tokenizer_factory=WordTokenizer)
        sources, records = [], []
        for kind, required in [("icai_book", "plus"), ("firm_book", "pro")]:
            path = self.root / "data/sources" / (kind + ".pdf")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"%PDF-1.4\nSYNTHETIC_" + kind.encode() + b"\n%%EOF")
            sources.append({"document_id": kind, "source_type": kind, "page_count": 1, "name": kind,
                            "sha256": digest(path.read_bytes()), "pdf_path": path.relative_to(self.root).as_posix()})
            text = f"Synthetic {kind} book refers to 8/2025-Central Tax (Rate)."
            records.append({"chunk_id": kind + ":1", "document_id": kind, "source_type": kind, "plan_required": required,
                            "pages": [1], "source_refs": ["#/texts/0"], "text": text, "embedding_text": text, "headings": []})
        self.active_path = self.root / "data/app/corpus.json"
        write_json(self.active_path, {"version": "synthetic-base", "sources": sources, "records": records, "links": []})
        self.before = self.active_path.read_bytes()
        self.base = digest(self.before)
        self.sync_root = self.root / "data/app/notification_sync"
        run(self.sync_root, Feed(), sources=["cgst_rate"], parse=True, parser=parser_fixture)
        self.version = self.publisher.list_sources(self.actor)[0]["id"]
        self.detail = self.publisher.detail(self.version, self.actor)
        anchors = {key: {"source_ref": f"#/texts/{i}", "pages": [1], "quote": TEXTS[i]}
                   for i, key in enumerate(["identity", "issued_on", "effective_from", "amends"])}
        self.body = {"revision": 0, "stage_sha256": self.detail["stage_sha256"], "source_checked": True,
                     "issued_on": "2025-01-01", "effective_from": "2025-01-02", "amends": "central_tax_rate:1/2017",
                     "anchors": anchors, "clauses": [{"id": "condition", "subject": "Synthetic complete condition",
                         "topic_id": "other_gst", "source_refs": ["#/texts/4"], "provisions": ["Synthetic entry"],
                         "operative_change": "Synthetic change for testing only", "complete_clause_confirmed": True}]}

    def approve(self):
        return self.publisher.review(self.version, self.body, self.actor)

    def prepared(self):
        self.approve()
        return self.publisher.prepare([self.version], self.base, self.actor)

    def verified(self, mode="bm25", **kwargs):
        publication = self.prepared()
        self.publisher.index(publication["id"], mode, **kwargs)
        return publication

    def remote_factory(self, session):
        return lambda snapshot, name: PineconeStore(snapshot, name, key="synthetic-publication-key", session=session)


class SourceReviewTests(Fixture):
    def test_admin_approval_is_bound_to_pdf_parse_stage_and_actor(self):
        result = self.approve()
        self.assertEqual((result["revision"], result["status"], result["actor_id"]), (1, "approved", self.actor["id"]))
        self.assertFalse(result["answer_approval_performed"])
        self.assertEqual(self.active_path.read_bytes(), self.before)
        record = self.publisher.detail(self.version, self.actor)["review"]["records"][0]
        self.assertEqual(record["plan_required"], "plus")
        self.assertIn(TEXTS[4], record["text"])
        self.assertFalse(record["notification"]["chain_complete"])

    def test_nonalphabetic_series_are_not_confused(self):
        self.assertEqual(references("8/2025-Central Tax (Rate) and 8/2025-Central Tax"),
                         {"central_tax_rate:8/2025", "central_tax:8/2025"})

    def test_non_admin_cannot_read_or_approve_sources(self):
        for role in [None, {"id": "user", "role": "user"}, self.actor | {"active": False}]:
            with self.subTest(role=role), self.assertRaises(StateError) as caught:
                self.publisher.review(self.version, self.body, role)
            self.assertEqual(caught.exception.status, 403)

    def test_stale_revision_and_stage_checksum_rejected(self):
        self.approve()
        with self.assertRaisesRegex(StateError, "stale_source_review_revision"):
            self.approve()
        body = self.body | {"revision": 1, "stage_sha256": "0" * 64}
        with self.assertRaisesRegex(StateError, "stale_stage_digest"):
            self.publisher.review(self.version, body, self.actor)

    def test_wrong_anchor_page_quote_or_identity_rejected(self):
        for field, value in [("pages", [2]), ("quote", "Invented notification identity")]:
            body = copy.deepcopy(self.body)
            body["anchors"]["identity"][field] = value
            with self.subTest(field=field), self.assertRaises(StateError): self.publisher.review(self.version, body, self.actor)

    def test_invented_date_and_ambiguous_date_evidence_rejected(self):
        body = self.body | {"effective_from": "2025-01-03"}
        with self.assertRaisesRegex(StateError, "date_not_supported"):
            self.publisher.review(self.version, body, self.actor)

    def test_retrospective_effect_requires_separate_policy(self):
        body = self.body | {"effective_from": "2024-12-31"}
        with self.assertRaisesRegex(StateError, "retrospective"):
            self.publisher.review(self.version, body, self.actor)

    def test_wrong_amendment_target_rejected(self):
        with self.assertRaisesRegex(StateError, "amendment_target"):
            self.publisher.review(self.version, self.body | {"amends": "central_tax:1/2017"}, self.actor)

    def test_unknown_clause_ref_and_duplicate_clause_rejected(self):
        body = copy.deepcopy(self.body)
        body["clauses"][0]["source_refs"] = ["#/texts/999"]
        with self.assertRaisesRegex(StateError, "unknown_clause"):
            self.publisher.review(self.version, body, self.actor)
        body = copy.deepcopy(self.body)
        body["clauses"].append(copy.deepcopy(body["clauses"][0]))
        with self.assertRaisesRegex(StateError, "duplicate_clause"):
            self.publisher.review(self.version, body, self.actor)

    def test_over_budget_complete_clause_rejected_not_truncated(self):
        class OverBudget:
            def encode(self, *args, **kwargs): return list(range(513))
        publisher = Publications(self.root, tokenizer_factory=OverBudget)
        with self.assertRaisesRegex(StateError, "exceeds_512"):
            publisher.review(self.version, self.body, self.actor)

    def test_corrupted_parse_cannot_be_approved(self):
        path = next((self.sync_root / "staging").glob("*/docling.json"))
        path.write_text("SYNTHETIC_CHANGED_PARSE", encoding="utf-8")
        with self.assertRaisesRegex(StateError, "staged_source_changed"):
            self.approve()

    def test_operative_clause_without_page_provenance_is_rejected(self):
        folder = next((self.sync_root / "staging").iterdir())
        document = DoclingDocument.load_from_json(folder / "docling.json")
        document.texts[4].prov = []
        document.save_as_json(folder / "docling.json")
        stage = json.loads((folder / "staged.json").read_text(encoding="utf-8"))
        stage["docling_sha256"] = digest((folder / "docling.json").read_bytes())
        write_json(folder / "staged.json", stage)
        sha = digest((folder / "staged.json").read_bytes())
        with self.publisher.registry(mutate=True) as registry:
            registry.db.execute("UPDATE versions SET stage_sha256=? WHERE id=?", (sha, self.version))
            registry.db.commit()
        with self.assertRaisesRegex(StateError, "missing_page_provenance"):
            self.publisher.review(self.version, self.body | {"stage_sha256": sha}, self.actor)

    def test_rejection_records_actor_and_blocks_publication(self):
        body = SourceRejection(revision=0, stage_sha256=self.body["stage_sha256"], reason="Synthetic missing context")
        self.assertEqual(self.publisher.reject(self.version, body, self.actor)["status"], "rejected")
        with self.assertRaisesRegex(StateError, "source_review_missing"):
            self.publisher.prepare([self.version], self.base, self.actor)

    def test_schema_requires_human_checks_and_forbids_reviewer_spoofing(self):
        for changes in [{"source_checked": False}, {"reviewer_id": "pretend-admin"}, {"issued_on": None}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): NotificationReview.model_validate(self.body | changes)


class PublicationTests(Fixture):
    def test_unreviewed_source_never_prepares(self):
        with self.assertRaisesRegex(StateError, "source_review_missing"):
            self.publisher.prepare([self.version], self.base, self.actor)

    def test_prepare_preserves_active_bundle_and_keeps_exact_backup(self):
        publication = self.prepared()
        folder = self.publisher._folder(publication["id"])
        self.assertEqual(self.active_path.read_bytes(), self.before)
        self.assertEqual((folder / "base.json").read_bytes(), self.before)
        bundle = json.loads((folder / "corpus.json").read_bytes())
        self.assertEqual(len(bundle["records"]), 3)
        self.assertEqual({s["source_type"] for s in bundle["sources"]}, {"firm_book", "icai_book", "notification"})
        self.assertEqual(len(bundle["links"]), 2)
        self.assertTrue(all(link["status"] == "candidate_pending_admin_review" for link in bundle["links"]))

    def test_prepare_is_idempotent_and_stale_base_rejected(self):
        publication = self.prepared()
        self.assertEqual(self.publisher.prepare([self.version], self.base, self.actor)["id"], publication["id"])
        with self.assertRaisesRegex(StateError, "active_corpus_changed"):
            self.publisher.prepare([self.version], "0" * 64, self.actor)

    def test_unverified_or_wrong_retriever_snapshot_cannot_activate(self):
        publication = self.prepared()
        with self.assertRaisesRegex(StateError, "not_verified"):
            self.publisher.activate(publication["id"], self.base, self.actor, "bm25")
        self.publisher.index(publication["id"], "bm25")
        with self.assertRaisesRegex(StateError, "not_verified"):
            self.publisher.activate(publication["id"], self.base, self.actor, "pinecone")
        self.assertEqual(self.active_path.read_bytes(), self.before)

    def test_bm25_activation_is_explicit_and_date_lane_works_for_both_plans(self):
        publication = self.verified()
        result = self.publisher.activate(publication["id"], self.base, self.actor, "bm25")
        self.assertFalse(result["restart_required"])
        self.assertFalse(result["answer_approval_performed"])
        corpus = Corpus(self.root)
        for plan in ["plus", "pro"]:
            self.assertEqual(len(check_updates(corpus.records, ["other_gst"], "2025-01-02", plan)["candidates"]), 1)
        self.assertEqual(check_updates(corpus.records, ["other_gst"], "2025-01-01", "plus")["candidates"], [])
        self.assertEqual(len(corpus.records), 3)
        self.assertEqual(self.publisher.list_publications(self.actor)[0]["activated_by"], self.actor["id"])

    def test_active_base_change_blocks_indexing_and_activation(self):
        publication = self.verified()
        self.active_path.write_bytes(self.before + b"\n")
        with self.assertRaisesRegex(StateError, "active_corpus_changed"):
            self.publisher.activate(publication["id"], self.base, self.actor, "bm25")
        with self.assertRaisesRegex(StateError, "active_corpus_changed"):
            self.publisher.index(publication["id"], "bm25")

    def test_changed_review_after_prepare_blocks_verification(self):
        publication = self.prepared()
        self.publisher.review(self.version, self.body | {"revision": 1}, self.actor)
        with self.assertRaisesRegex(StateError, "source_review_missing_or_changed"):
            self.publisher.index(publication["id"], "bm25")

    def test_corrupted_candidate_or_backup_blocks_activation(self):
        publication = self.verified()
        folder = self.publisher._folder(publication["id"])
        (folder / "base.json").write_bytes(b"SYNTHETIC_CORRUPTED_BACKUP")
        with self.assertRaisesRegex(StateError, "publication_backup_changed"):
            self.publisher.activate(publication["id"], self.base, self.actor, "bm25")
        self.assertEqual(self.active_path.read_bytes(), self.before)

    def test_changed_candidate_snapshot_cannot_activate(self):
        publication = self.verified()
        path = self.publisher._folder(publication["id"]) / "corpus.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(StateError, "publication_snapshot_changed"):
            self.publisher.activate(publication["id"], self.base, self.actor, "bm25")
        self.assertEqual(self.active_path.read_bytes(), self.before)

    def test_provider_verification_failure_does_not_change_active_corpus(self):
        publication = self.prepared()
        class FailedJina:
            def encode(self, *args): raise RuntimeError("PRIVATE_PROVIDER_DETAIL")
        with self.assertRaisesRegex(StateError, "snapshot_verification_failed"):
            self.publisher.index(publication["id"], "pinecone", jina_factory=lambda root: FailedJina())
        self.assertEqual(self.active_path.read_bytes(), self.before)
        self.assertEqual(self.publisher.list_publications(self.actor)[0]["state"], "verification_failed")

    def test_full_pinecone_snapshot_is_uploaded_and_verified_offline(self):
        publication = self.prepared()
        session = Session()
        class Jina:
            def encode(inner, texts, task):
                self.assertEqual(len(texts), 3)
                return [VECTOR] * len(texts)
        self.publisher.index(publication["id"], "pinecone", store_factory=self.remote_factory(session), jina_factory=lambda root: Jina())
        counts = {namespace: len(rows) for namespace, rows in session.rows.items()}
        self.assertEqual(counts, {"icai_books": 1, "firm_books": 1, "notifications": 1})
        self.publisher.activate(publication["id"], self.base, self.actor, "pinecone", store_factory=self.remote_factory(session))
        self.assertEqual(len(Corpus(self.root).records), 3)

    def test_missing_remote_vector_at_activation_blocks_switch(self):
        publication = self.prepared()
        session = Session()
        class Jina:
            def encode(self, texts, task): return [VECTOR] * len(texts)
        self.publisher.index(publication["id"], "pinecone", store_factory=self.remote_factory(session), jina_factory=lambda root: Jina())
        session.rows["notifications"].clear()
        with self.assertRaisesRegex(StateError, "activation_verification_failed"):
            self.publisher.activate(publication["id"], self.base, self.actor, "pinecone", store_factory=self.remote_factory(session))
        self.assertEqual(self.active_path.read_bytes(), self.before)

    def test_index_cli_dry_run_makes_no_provider_call(self):
        publication = self.prepared()
        with patch("gst_rag.notification_publication.app_jina", side_effect=AssertionError("no provider")), redirect_stdout(io.StringIO()) as output:
            code = main(["index", publication["id"], "--root", str(self.root), "--mode", "pinecone"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output.getvalue())["provider_calls_made"])
        self.assertEqual(self.active_path.read_bytes(), self.before)

    def test_already_published_notification_requires_explicit_revision_policy(self):
        publication = self.verified()
        self.publisher.activate(publication["id"], self.base, self.actor, "bm25")
        with self.assertRaisesRegex(StateError, "requires_revision_policy"):
            self.publisher.prepare([self.version], digest(self.active_path.read_bytes()), self.actor)

    def test_active_source_review_cannot_be_silently_revised_or_rejected(self):
        publication = self.verified()
        self.publisher.activate(publication["id"], self.base, self.actor, "bm25")
        with self.assertRaisesRegex(StateError, "active_source_review_frozen"):
            self.publisher.review(self.version, self.body | {"revision": 1}, self.actor)
        with self.assertRaisesRegex(StateError, "active_source_review_frozen"):
            self.publisher.reject(self.version, SourceRejection(revision=1, stage_sha256=self.body["stage_sha256"],
                                                                reason="Synthetic correction request"), self.actor)

    def test_real_service_detects_activation_and_keeps_its_old_snapshot_coherent(self):
        settings = Settings(self.root, self.root / "state.db", "x" * 32, worker_enabled=False, generation="off")
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=WordTokenizer()):
            old = RetrievalService(settings)
            self.assertTrue(old.is_current())
            publication = self.verified()
            self.publisher.activate(publication["id"], self.base, self.actor, "bm25")
            self.assertFalse(old.is_current())
            self.assertEqual(len(old.corpus.records), 2)
            new = RetrievalService(settings)
            self.assertTrue(new.is_current())
            self.assertEqual(len(new.corpus.records), 3)
            plus = new.retrieve("Synthetic book", ["other_gst"], "2025-01-02", "plus")
            pro = new.retrieve("Synthetic book", ["other_gst"], "2025-01-02", "pro")
            self.assertNotIn("firm_book", {c["source_type"] for c in plus["citations"]})
            self.assertIn("notification", {c["source_type"] for c in plus["citations"]})
            self.assertIn("firm_book", {c["source_type"] for c in pro["citations"]})

    def test_worker_rebuilds_service_between_jobs_after_activation(self):
        state = {"current": True, "created": 0}
        class Service:
            def is_current(self): return state["current"]
            def retrieve(self, question, topics, date, plan):
                return {"status": "review_required", "citations": [], "generation": "not_configured"}
        def factory():
            state["created"] += 1
            state["current"] = True
            return Service()
        store = Store(self.root / "worker.db")
        user = store.create_user("synthetic-user", "not-a-real-password-hash")
        worker = Worker(store, factory)
        for _ in range(2):
            store.enqueue(user["id"], "Synthetic dated question", "2025-01-02", ["other_gst"], None)
            self.assertTrue(worker.run_once())
            state["current"] = False
        self.assertEqual(state["created"], 2)


class AdminApiTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = PASSWORDS.hash("synthetic-fixture-password-only")

    def setUp(self):
        super().setUp()
        self.settings = Settings(self.root, self.root / "api.db", "x" * 32, worker_enabled=False, generation="off")
        self.store = Store(self.settings.db_path)
        self.admin = self.store.create_user("fixture-admin", self.password_hash, "pro", "admin", bootstrap=True)
        self.user = self.store.create_user("fixture-user", self.password_hash, "pro")
        self.client = self.enterContext(TestClient(create_app(self.settings, self.store, publications=self.publisher)))

    def headers(self, actor): return {"Authorization": "Bearer " + issue_token(actor, self.settings)}

    def test_all_ingestion_reads_and_writes_require_authenticated_admin(self):
        routes = [("GET", "/admin/ingestion/notifications"), ("GET", "/admin/ingestion/notifications/" + self.version),
                  ("GET", "/admin/ingestion/notifications/" + self.version + "/pdf"),
                  ("GET", "/admin/ingestion/corpus"), ("GET", "/admin/ingestion/publications")]
        for method, path in routes:
            self.assertEqual(self.client.request(method, path).status_code, 401)
            self.assertEqual(self.client.request(method, path, headers=self.headers(self.user)).status_code, 403)
        url = "/admin/ingestion/notifications/" + self.version + "/review"
        self.assertEqual(self.client.put(url, json=self.body).status_code, 401)
        self.assertEqual(self.client.put(url, json=self.body, headers=self.headers(self.user)).status_code, 403)
        writes = [("/admin/ingestion/notifications/" + self.version + "/reject",
                   {"revision": 0, "stage_sha256": self.body["stage_sha256"], "reason": "Synthetic rejection"}),
                  ("/admin/ingestion/publications", {"version_ids": [self.version], "base_sha256": self.base}),
                  ("/admin/ingestion/publications/" + "a" * 64 + "/activate", {"base_sha256": self.base, "confirm": True})]
        for path, body in writes:
            self.assertEqual(self.client.post(path, json=body).status_code, 401)
            self.assertEqual(self.client.post(path, json=body, headers=self.headers(self.user)).status_code, 403)

    def test_admin_api_can_review_prepare_verify_and_activate_without_publishing_an_answer(self):
        headers = self.headers(self.admin)
        url = "/admin/ingestion/notifications/" + self.version
        detail = self.client.get(url, headers=headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["items"]), 5)
        reviewed = self.client.put(url + "/review", json=self.body, headers=headers)
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["actor_id"], self.admin["id"])
        current = self.client.get("/admin/ingestion/corpus", headers=headers).json()
        prepared = self.client.post("/admin/ingestion/publications", headers=headers,
                                    json={"version_ids": [self.version], "base_sha256": current["base_sha256"]})
        self.assertEqual(prepared.status_code, 201, prepared.text)
        publication_id = prepared.json()["id"]
        self.publisher.index(publication_id, "bm25")
        activated = self.client.post(f"/admin/ingestion/publications/{publication_id}/activate", headers=headers,
                                    json={"base_sha256": self.base, "confirm": True})
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertFalse(activated.json()["answer_approval_performed"])
        self.assertEqual(self.client.get("/queries", headers=self.headers(self.user)).json(), [])

    def test_reviewer_spoof_and_missing_activation_confirmation_are_rejected(self):
        headers = self.headers(self.admin)
        url = "/admin/ingestion/notifications/" + self.version + "/review"
        self.assertEqual(self.client.put(url, json=self.body | {"actor_id": "spoof"}, headers=headers).status_code, 422)
        self.assertEqual(self.client.post("/admin/ingestion/publications/" + "a" * 64 + "/activate", headers=headers,
                                         json={"base_sha256": self.base}).status_code, 422)

    def test_staged_pdf_has_admin_only_no_store_view(self):
        response = self.client.get("/admin/ingestion/notifications/" + self.version + "/pdf", headers=self.headers(self.admin))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
