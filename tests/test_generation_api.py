"""Full API/worker/privacy tests with synthetic retrieval and fake generation."""

import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from gst_rag.api import create_app
from gst_rag.auth import PASSWORDS, Settings, issue_token
from gst_rag.generation import DraftingService
from gst_rag.ingestion import write_json
from gst_rag.store import Store
from test_generation import Provider, answer, packet


class Retrieval:
    def __init__(self):
        self.calls, self.callback, self.fail = [], None, False

    def retrieve(self, question, topics, as_of, plan):
        self.calls.append(plan)
        if self.callback:
            callback, self.callback = self.callback, None
            callback()
        if self.fail:
            raise RuntimeError("PRIVATE_RETRIEVAL_ERROR")
        evidence = packet("firm_book" if plan == "pro" else "icai_book")
        evidence["plan_used"] = plan
        return evidence


class GenerationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = PASSWORDS.hash("synthetic-login-password")

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        write_json(self.root / "data/app/corpus.json", {"records": [], "sources": [], "links": []})
        self.settings = Settings(self.root, self.root / "db", "x" * 32, worker_enabled=False,
                                 gemini_key="SYNTHETIC_NOT_A_LIVE_KEY", gemini_allow_firm_content=True)
        self.store = Store(self.settings.db_path)
        self.admin = self.store.create_user("admin", self.password_hash, "pro", "admin", bootstrap=True)
        self.plus = self.store.create_user("plus", self.password_hash)
        self.pro = self.store.create_user("pro", self.password_hash, "pro")
        self.retrieval, self.provider = Retrieval(), Provider()
        self.app = create_app(self.settings, self.store, lambda: self.retrieval, DraftingService(self.settings, self.provider))
        self.client = self.enterContext(TestClient(self.app))

    def headers(self, user):
        return {"Authorization": "Bearer " + issue_token(user, self.settings)}

    def submit(self, user=None, **changes):
        response = self.client.post("/queries", headers=self.headers(user or self.plus),
            json={"question": "Synthetic question", "as_of": "2023-03-01", "topic_ids": ["other_gst"]} | changes)
        self.assertEqual(response.status_code, 202)
        return response.json()

    def private(self, row):
        response = self.client.get("/admin/queries/" + row["id"], headers=self.headers(self.admin))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def ready(self, user=None, **changes):
        row = self.submit(user, **changes)
        self.app.state.worker.run_once()
        return self.private(row)

    def approve(self, row, citations=None):
        return self.client.post(f"/admin/queries/{row['id']}/decision", headers=self.headers(self.admin),
            json={"action": "approve", "revision": row["revision"], "citation_ids": citations or ["S1", "S2"]})

    def test_generated_draft_is_persisted_but_never_in_user_detail_or_lists(self):
        row = self.ready()
        self.assertEqual(row["status"], "pending_review")
        self.assertIn("Synthetic book explanation", row["draft_text"])
        self.assertEqual(row["packet"]["generation"], "validated_private_draft")
        self.assertEqual(len(self.provider.calls), 1)
        for url in ["/queries", "/queries/" + row["id"]]:
            response = self.client.get(url, headers=self.headers(self.plus))
            for text in ["Synthetic book explanation", "generated_answer", "PRIVATE_PDF", "generation_details", "draft_text"]:
                self.assertNotIn(text, response.text)

    def test_explicit_approval_releases_draft_and_server_citations_only(self):
        row = self.ready()
        response = self.approve(row)
        self.assertEqual(response.status_code, 200)
        approved = response.json()
        self.assertEqual(approved["answer"], row["draft_text"])
        self.assertTrue(all(set(c) == {"citation_id", "source_name", "source_type", "pages"} for c in approved["citations"]))
        self.assertNotIn("pdf_url", response.text)
        self.assertNotIn("generated_answer", response.text)

    def test_approval_must_include_every_inline_citation(self):
        row = self.ready()
        response = self.approve(row, ["S1"])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "inline_citations_must_be_in_approval_selection")

    def test_admin_can_edit_generated_draft_then_approve(self):
        row = self.ready()
        response = self.client.post(f"/admin/queries/{row['id']}/decision", headers=self.headers(self.admin),
            json={"action": "edit_and_approve", "revision": row["revision"], "text": "Human edited synthetic statement [S1]", "citation_ids": ["S1"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Human edited synthetic statement [S1]")

    def test_key_missing_keeps_retrieval_and_manual_drafting(self):
        self.settings.gemini_key = None
        row = self.ready()
        self.assertIsNone(row["draft_text"])
        self.assertTrue(row["packet"]["citations"])
        self.assertEqual(row["packet"]["generation"], "not_configured")
        self.assertEqual(self.provider.calls, [])
        saved = self.client.put(f"/admin/queries/{row['id']}/draft", headers=self.headers(self.admin),
            json={"revision": row["revision"], "draft_text": "Manual synthetic answer [S1]"})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.approve(saved.json(), ["S1"]).status_code, 200)

    def test_invalid_model_citation_keeps_evidence_but_no_approvable_draft(self):
        self.provider.raw["book_explanation"][0]["evidence"][0]["citation_id"] = "S999"
        row = self.ready()
        self.assertIsNone(row["draft_text"])
        self.assertTrue(row["packet"]["citations"])
        self.assertEqual(row["packet"]["generation"], "generated_citation_unknown")
        self.assertEqual(self.approve(row).status_code, 422)

    def test_provider_failure_preserves_retrieval_and_hides_error(self):
        self.provider.error = RuntimeError("PRIVATE_PROVIDER_ERROR_KEY")
        row = self.ready()
        self.assertTrue(row["packet"]["citations"])
        self.assertEqual(row["packet"]["generation"], "generation_unavailable")
        self.assertIsNone(row["draft_text"])
        self.assertNotIn("PRIVATE_PROVIDER_ERROR_KEY", json.dumps(row))

    def test_downgrade_after_retrieval_skips_generation_and_requeues(self):
        self.retrieval.callback = lambda: self.store.set_plan(self.pro["id"], "plus")
        row = self.ready(self.pro)
        self.assertEqual(row["status"], "queued")
        self.assertIsNone(row["packet"])
        self.assertIsNone(row["draft_text"])
        self.assertEqual(self.provider.calls, [])
        self.app.state.worker.run_once()
        current = self.private(row)
        self.assertEqual(current["plan_at_retrieval"], "plus")
        self.assertTrue(all(s["source_type"] != "firm_book" for s in self.provider.calls[0]["evidence"]))

    def test_downgrade_during_model_call_discards_draft_and_packet(self):
        def downgrade():
            self.provider.callback = None
            self.store.set_plan(self.pro["id"], "plus")
        self.provider.callback = downgrade
        row = self.ready(self.pro)
        self.assertEqual(row["status"], "queued")
        self.assertIsNone(row["packet"])
        self.assertIsNone(row["draft_text"])
        self.app.state.worker.run_once()
        current = self.private(row)
        self.assertEqual(current["plan_at_retrieval"], "plus")
        self.assertTrue(all(s["source_type"] != "firm_book" for s in self.provider.calls[-1]["evidence"]))

    def test_pending_pro_draft_after_downgrade_cannot_be_approved(self):
        row = self.ready(self.pro)
        self.store.set_plan(self.pro["id"], "plus")
        self.assertEqual(self.approve(row).status_code, 409)

    def test_approved_pro_history_survives_but_is_not_sent_to_model_on_followup(self):
        self.provider.raw["book_explanation"][0]["text"] = "OLD_PRIVATE_PRO_ANSWER"
        row = self.ready(self.pro)
        self.assertEqual(self.approve(row).status_code, 200)
        self.store.set_plan(self.pro["id"], "plus")
        self.provider.raw = answer()
        followup = self.ready(self.pro, parent_query_id=row["id"])
        self.assertEqual(followup["conversation_id"], row["conversation_id"])
        self.assertNotIn("OLD_PRIVATE_PRO_ANSWER", json.dumps(self.provider.calls[-1]))
        self.assertTrue(all(c["source_type"] != "firm_book" for c in self.provider.calls[-1]["evidence"]))
        old = self.client.get("/queries/" + row["id"], headers=self.headers(self.pro)).json()
        self.assertIn("OLD_PRIVATE_PRO_ANSWER", old["answer"])

    def test_restart_preserves_pending_generated_draft(self):
        row = self.ready()
        restored = Store(self.settings.db_path).query(row["id"])
        self.assertEqual(restored["draft_text"], row["draft_text"])
        self.assertEqual(restored["status"], "pending_review")

    def test_reprocess_clears_previous_generated_draft(self):
        row = self.ready()
        response = self.client.post(f"/admin/queries/{row['id']}/reprocess", headers=self.headers(self.admin), json={"revision": row["revision"]})
        self.assertEqual(response.status_code, 202)
        self.assertIsNone(response.json()["draft_text"])
        self.assertIsNone(response.json()["packet"])

    def test_missing_date_or_topic_never_calls_model(self):
        for changes in [{"as_of": None}, {"topic_ids": []}]:
            row = self.ready(**changes)
            self.assertEqual(row["status"], "clarification_required")
        self.assertEqual(self.provider.calls, [])

    def test_retrieval_failure_never_calls_model(self):
        self.retrieval.fail = True
        row = self.ready()
        self.assertEqual(row["packet"]["review_reasons"], ["retrieval_unavailable"])
        self.assertEqual(self.provider.calls, [])

    def test_model_clarification_and_uncertainty_never_published_automatically(self):
        self.provider.raw["status"] = "needs_clarification"
        for field in ["book_explanation", "latest_notification", "practical_effect"]:
            self.provider.raw[field] = []
        self.provider.raw["clarification_question"] = "PRIVATE_MODEL_CLARIFICATION"
        row = self.ready()
        self.assertEqual(row["status"], "pending_review")
        response = self.client.get("/queries/" + row["id"], headers=self.headers(self.plus))
        self.assertNotIn("PRIVATE_MODEL_CLARIFICATION", response.text)
        self.assertIsNone(response.json()["answer"])

    def test_firm_privacy_default_blocks_only_external_generation_not_retrieval(self):
        self.settings.gemini_allow_firm_content = False
        row = self.ready(self.pro)
        self.assertEqual(row["packet"]["generation"], "firm_content_requires_privacy_opt_in")
        self.assertTrue(any(c["source_type"] == "firm_book" for c in row["packet"]["citations"]))
        self.assertEqual(self.provider.calls, [])

    def test_health_reports_configuration_not_keys_or_provider_connectivity(self):
        result = self.client.get("/health").json()
        self.assertEqual(result["generation"], "configured_not_live_verified")
        self.assertNotIn("SYNTHETIC_NOT_A_LIVE_KEY", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
