"""API/state-machine tests use temporary SQLite and synthetic evidence only."""

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
import jwt

from gst_rag.api import create_app
from gst_rag.auth import PASSWORDS, Settings, issue_token
from gst_rag.service import Worker
from gst_rag.store import StateError, Store


class FakeService:
    def __init__(self):
        self.calls, self.callback, self.fail, self.force_firm = [], None, False, False

    def retrieve(self, question, topics, as_of, plan):
        self.calls.append((question, topics, as_of, plan))
        if self.callback:
            callback, self.callback = self.callback, None
            callback()
        if self.fail:
            raise RuntimeError("PRIVATE_PROVIDER_ERROR_AND_KEY")
        source = "firm_book" if plan == "pro" or self.force_firm else "icai_book"
        return {"status": "review_required", "citations": [{"citation_id": "S1", "document_id": source,
            "source_name": "Synthetic " + source, "source_type": source, "pages": [1], "source_refs": ["#/texts/0"],
            "excerpt": "PRIVATE_SOURCE_EXCERPT_" + source, "pdf_url": "/admin/sources/" + source + "/pdf#page=1"}],
            "context_tokens": 10, "review_reasons": ["synthetic_manual_review"], "plan_used": plan,
            "history_used_as_evidence": False, "generation": "not_configured"}


class ApiTests(unittest.TestCase):
    password = "unit-test-password-not-real"

    @classmethod
    def setUpClass(cls):
        cls.password_hash = PASSWORDS.hash(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = time.time()
        self.settings = Settings(self.root, self.root / "test.sqlite3", "test-only-signing-secret-" * 3, worker_enabled=False)
        self.store = Store(self.settings.db_path, clock=lambda: self.now)
        self.admin = self.store.create_user("admin", self.password_hash, "pro", "admin", bootstrap=True)
        self.plus = self.store.create_user("plus-user", self.password_hash)
        self.pro = self.store.create_user("pro-user", self.password_hash, "pro")
        self.fake = FakeService()
        source = self.root / "data/sources/synthetic.pdf"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"%PDF-1.4\nsynthetic endpoint fixture\n%%EOF")
        self.pdf = source
        self.bundle_path = self.root / "data/app/corpus.json"
        self.bundle_path.parent.mkdir(parents=True)
        self.bundle = {"records": [], "links": [], "sources": [{"document_id": "synthetic", "source_type": "notification",
            "name": "Synthetic fixture", "page_count": 1, "pdf_path": "data/sources/synthetic.pdf", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}
        self.bundle_path.write_text(json.dumps(self.bundle), encoding="utf-8")
        self.app = create_app(self.settings, self.store, lambda: self.fake)
        self.client = self.enterContext(TestClient(self.app))

    def headers(self, user):
        return {"Authorization": "Bearer " + issue_token(user, self.settings)}

    def submit(self, user=None, **changes):
        body = {"question": "Synthetic question", "as_of": "2023-03-01", "topic_ids": ["pencil_sharpeners"]} | changes
        result = self.client.post("/queries", json=body, headers=self.headers(user or self.plus))
        self.assertEqual(result.status_code, 202, result.text)
        return result.json()

    def ready(self, user=None):
        row = self.submit(user)
        self.assertTrue(self.app.state.worker.run_once())
        return self.private(row["id"])

    def private(self, query_id):
        response = self.client.get("/admin/queries/" + query_id, headers=self.headers(self.admin))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def decide(self, row, **changes):
        return self.client.post(f"/admin/queries/{row['id']}/decision", headers=self.headers(self.admin), json={
            "revision": row["revision"], "action": "edit_and_approve", "text": "Synthetic manually approved answer.", "citation_ids": ["S1"]} | changes)

    def test_protected_endpoints_require_authentication(self):
        for url in ["/me", "/queries", "/admin/reviews", "/admin/sources", "/admin/sources/synthetic/pdf"]:
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_json_login_returns_token_not_password_hash(self):
        response = self.client.post("/auth/token", json={"username": "PLUS-USER", "password": self.password})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.password_hash, response.text)
        self.assertNotIn(self.password, response.text)
        me = self.client.get("/me", headers={"Authorization": "Bearer " + response.json()["access_token"]})
        self.assertEqual(me.json()["plan"], "plus")

    def test_wrong_and_unknown_credentials_are_generic(self):
        bodies = [{"username": "plus-user", "password": "wrong-test-password"}, {"username": "unknown-user", "password": self.password}]
        results = [self.client.post("/auth/token", json=b) for b in bodies]
        self.assertTrue(all(r.status_code == 401 for r in results))
        self.assertEqual(results[0].json(), results[1].json())

    def test_validation_never_echoes_password_input(self):
        response = self.client.post("/auth/token", json={"username": "plus-user", "password": "SENSITIVE"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("SENSITIVE", response.text)

    def test_wrong_signature_expired_and_unsigned_tokens_rejected(self):
        claims = {"sub": self.plus["id"], "iat": 1, "exp": 2, "iss": "gst-rag-local", "aud": "gst-rag-api"}
        tokens = [jwt.encode(claims, self.settings.jwt_secret, algorithm="HS256"),
                  jwt.encode(claims | {"exp": int(time.time()) + 100}, "different-signing-key-with-at-least-32-bytes", algorithm="HS256"),
                  jwt.encode(claims, None, algorithm="none")]
        for token in tokens:
            self.assertEqual(self.client.get("/me", headers={"Authorization": "Bearer " + token}).status_code, 401)

    def test_regular_user_cannot_call_admin_routes_even_if_pro(self):
        headers = self.headers(self.pro)
        for url in ["/admin/users", "/admin/reviews", "/admin/sources", "/admin/sources/synthetic/pdf"]:
            self.assertEqual(self.client.get(url, headers=headers).status_code, 403)
        self.assertEqual(self.client.patch(f"/admin/users/{self.pro['id']}/plan", headers=headers, json={"plan": "plus"}).status_code, 403)

    def test_admin_creates_only_normal_users_with_manual_plan(self):
        body = {"username": "new-user", "password": self.password, "plan": "pro"}
        result = self.client.post("/admin/users", headers=self.headers(self.admin), json=body)
        self.assertEqual(result.status_code, 201)
        self.assertEqual((result.json()["role"], result.json()["plan"]), ("user", "pro"))
        self.assertNotIn("password", result.text)
        self.assertEqual(self.client.post("/admin/users", headers=self.headers(self.admin), json=body | {"role": "admin"}).status_code, 422)

    def test_no_browser_supplied_plan_user_or_namespace(self):
        for field in ["plan", "user_id", "namespaces", "role"]:
            response = self.client.post("/queries", headers=self.headers(self.plus), json={"question": "Test", field: "pro"})
            self.assertEqual(response.status_code, 422)
        self.assertFalse(self.store.queries(self.plus["id"]))

    def test_submit_is_queued_then_polls_pending_without_evidence(self):
        queued = self.submit()
        self.assertEqual(queued["status"], "queued")
        self.app.state.worker.run_once()
        public = self.client.get("/queries/" + queued["id"], headers=self.headers(self.plus)).json()
        self.assertEqual(public["status"], "pending_review")
        self.assertIsNone(public["answer"])
        self.assertEqual(public["citations"], [])
        self.assertNotIn("PRIVATE_SOURCE", json.dumps(public))
        self.assertNotIn("pdf_url", json.dumps(public))

    def test_missing_date_or_topic_clarifies_without_retrieval(self):
        for changes in [{"as_of": None}, {"topic_ids": []}]:
            queued = self.submit(**changes)
            self.app.state.worker.run_once()
            public = self.client.get("/queries/" + queued["id"], headers=self.headers(self.plus)).json()
            self.assertEqual(public["status"], "clarification_required")
        self.assertEqual(self.fake.calls, [])

    def test_draft_remains_admin_only_on_detail_and_lists(self):
        row = self.ready()
        saved = self.client.put(f"/admin/queries/{row['id']}/draft", headers=self.headers(self.admin),
            json={"revision": row["revision"], "draft_text": "PRIVATE_DRAFT_NOT_APPROVED"})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["draft_text"], "PRIVATE_DRAFT_NOT_APPROVED")
        for url in ["/queries/" + row["id"], "/queries"]:
            public = self.client.get(url, headers=self.headers(self.plus))
            self.assertNotIn("PRIVATE_DRAFT", public.text)
            self.assertNotIn("PRIVATE_SOURCE", public.text)
        self.assertEqual(self.client.get("/admin/queries/" + row["id"], headers=self.headers(self.plus)).status_code, 403)

    def test_edit_approval_returns_plain_source_names_pages_not_links(self):
        row = self.ready()
        response = self.decide(row)
        self.assertEqual(response.status_code, 200, response.text)
        public = self.client.get("/queries/" + row["id"], headers=self.headers(self.plus)).json()
        self.assertEqual(public["status"], "approved")
        self.assertEqual(public["approval_kind"], "edit_and_approve")
        self.assertEqual(set(public["citations"][0]), {"citation_id", "source_name", "source_type", "pages"})
        self.assertNotIn("/admin/", json.dumps(public))

    def test_approve_uses_only_saved_draft(self):
        row = self.ready()
        self.assertEqual(self.decide(row, action="approve", text=None).status_code, 422)
        saved = self.client.put(f"/admin/queries/{row['id']}/draft", headers=self.headers(self.admin),
            json={"revision": row["revision"], "draft_text": "Approved existing draft."}).json()
        self.assertEqual(self.decide(saved, action="approve", text=None).json()["answer"], "Approved existing draft.")

    def test_missing_or_unknown_citations_rejected(self):
        row = self.ready()
        for citation_ids in [[], ["UNKNOWN"]]:
            self.assertEqual(self.decide(row, citation_ids=citation_ids).status_code, 422)

    def test_approval_cannot_smuggle_pdf_links_in_answer_text(self):
        row = self.ready()
        for text in ["See https://example.test/source.pdf", "See /admin/sources/private/pdf", "[PDF](source.pdf)"]:
            self.assertEqual(self.decide(row, text=text).status_code, 422)

    def test_duplicate_decision_and_stale_draft_revision_conflict(self):
        row = self.ready()
        self.assertEqual(self.decide(row).status_code, 200)
        self.assertEqual(self.decide(row).status_code, 409)
        self.assertEqual(self.client.put(f"/admin/queries/{row['id']}/draft", headers=self.headers(self.admin),
            json={"revision": row["revision"], "draft_text": "Cannot overwrite approval"}).status_code, 409)

    def test_admin_can_refuse_or_request_clarification(self):
        for action, expected in [("refuse", "safe_refusal"), ("request_clarification", "clarification_required")]:
            row = self.ready()
            result = self.decide(row, action=action, text="Please clarify the transaction facts.", citation_ids=[])
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["status"], expected)
            self.assertIsNone(result.json()["answer"])

    def test_query_owner_isolation_and_followup_owner_check(self):
        row = self.submit(self.pro)
        self.assertEqual(self.client.get("/queries/" + row["id"], headers=self.headers(self.plus)).status_code, 404)
        self.assertEqual(self.client.get("/queries", headers=self.headers(self.plus)).json(), [])
        response = self.client.post("/queries", headers=self.headers(self.plus), json={"question": "Hijack", "parent_query_id": row["id"]})
        self.assertEqual(response.status_code, 404)

    def test_followup_chain_keeps_conversation_but_does_not_replay_answers(self):
        row = self.ready(self.pro)
        self.assertEqual(self.decide(row, text="OLD_APPROVED_PRO_CONTENT").status_code, 200)
        self.store.set_plan(self.pro["id"], "plus")
        followup = self.submit(self.pro, question="New standalone followup", parent_query_id=row["id"])
        self.app.state.worker.run_once()
        self.assertEqual(self.fake.calls[-1], ("New standalone followup", ["pencil_sharpeners"], "2023-03-01", "plus"))
        old = self.client.get("/queries/" + row["id"], headers=self.headers(self.pro)).json()
        self.assertEqual(old["answer"], "OLD_APPROVED_PRO_CONTENT")
        self.assertEqual(old["conversation_id"], followup["conversation_id"])
        packet = self.private(followup["id"])["packet"]
        self.assertNotIn("OLD_APPROVED_PRO_CONTENT", json.dumps(packet))
        self.assertEqual(packet["citations"][0]["source_type"], "icai_book")

    def test_stale_pro_token_uses_current_db_plan(self):
        headers = self.headers(self.pro)
        self.store.set_plan(self.pro["id"], "plus")
        self.assertEqual(self.client.get("/me", headers=headers).json()["plan"], "plus")
        queued = self.client.post("/queries", headers=headers, json={"question": "After downgrade", "as_of": "2023-03-01", "topic_ids": ["pencil_sharpeners"]}).json()
        self.app.state.worker.run_once()
        self.assertEqual(self.private(queued["id"])["plan_at_retrieval"], "plus")

    def test_plan_change_while_queued_is_applied_when_claimed(self):
        row = self.submit(self.pro)
        self.store.set_plan(self.pro["id"], "plus")
        self.app.state.worker.run_once()
        self.assertEqual(self.private(row["id"])["packet"]["plan_used"], "plus")

    def test_plan_change_during_processing_discards_old_packet_and_requeues(self):
        row = self.submit(self.pro)
        self.fake.callback = lambda: self.store.set_plan(self.pro["id"], "plus")
        self.app.state.worker.run_once()
        stale = self.private(row["id"])
        self.assertEqual(stale["status"], "queued")
        self.assertIsNone(stale["packet"])
        self.app.state.worker.run_once()
        self.assertEqual(self.private(row["id"])["packet"]["plan_used"], "plus")

    def test_pending_pro_answer_requires_reprocess_after_downgrade(self):
        row = self.ready(self.pro)
        self.store.set_plan(self.pro["id"], "plus")
        self.assertEqual(self.decide(row).status_code, 409)
        response = self.client.post(f"/admin/queries/{row['id']}/reprocess", headers=self.headers(self.admin), json={"revision": row["revision"]})
        self.assertEqual(response.status_code, 202)
        self.assertIsNone(response.json()["packet"])
        self.app.state.worker.run_once()
        current = self.private(row["id"])
        self.assertEqual(current["plan_at_retrieval"], "plus")
        self.assertEqual(self.decide(current).status_code, 200)

    def test_disallowed_source_citation_is_rejected_even_if_service_is_wrong(self):
        self.fake.force_firm = True
        row = self.ready(self.plus)
        self.assertEqual(self.decide(row).status_code, 422)

    def test_provider_failure_is_private_and_cannot_be_approved_without_evidence(self):
        self.fake.fail = True
        row = self.ready()
        self.assertEqual(row["packet"]["review_reasons"], ["retrieval_unavailable"])
        self.assertEqual(self.decide(row).status_code, 422)
        response = self.client.get("/queries/" + row["id"], headers=self.headers(self.plus))
        self.assertNotIn("PRIVATE_PROVIDER", response.text)

    def test_disabled_user_token_stops_working(self):
        with self.store.connection() as db:
            db.execute("UPDATE users SET active=0 WHERE id=?", (self.plus["id"],))
        self.assertEqual(self.client.get("/me", headers=self.headers(self.plus)).status_code, 401)

    def test_expired_content_hidden_and_purge_dry_run_preserves_sources(self):
        row = self.ready()
        self.decide(row)
        self.now += Store.retention_seconds + 1
        self.assertEqual(self.client.get("/queries/" + row["id"], headers=self.headers(self.plus)).status_code, 410)
        self.assertEqual(self.client.get("/queries", headers=self.headers(self.plus)).json(), [])
        self.assertEqual(self.store.purge(), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM queries").fetchone()[0], 1)
        self.assertEqual(self.store.purge(apply=True), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM queries").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM review_events").fetchone()[0], 0)
        self.assertTrue(self.pdf.exists())
        self.assertIsNotNone(self.store.user(user_id=self.plus["id"]))

    def test_approval_retention_starts_at_approval(self):
        row = self.ready()
        self.now += 2 * 24 * 60 * 60
        self.decide(row)
        self.assertEqual(self.store.query(row["id"])["expires_at"], self.now + Store.retention_seconds)

    def test_pending_state_survives_new_store_instance(self):
        row = self.ready()
        restarted = Store(self.settings.db_path, clock=lambda: self.now)
        self.assertEqual(restarted.query(row["id"])["status"], "pending_review")

    def test_processing_recovered_after_restart_and_job_not_claimed_twice(self):
        row = self.submit()
        self.assertIsNotNone(self.store.claim())
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.recover_processing(), 1)
        self.app.state.worker.run_once()
        self.assertEqual(self.private(row["id"])["status"], "pending_review")

    def test_pdf_route_is_admin_only_and_no_store(self):
        response = self.client.get("/admin/sources/synthetic/pdf", headers=self.headers(self.admin))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.pdf.read_bytes())
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_pdf_checksum_change_requires_reingestion(self):
        self.pdf.write_bytes(b"replaced file")
        self.assertEqual(self.client.get("/admin/sources/synthetic/pdf", headers=self.headers(self.admin)).status_code, 409)

    def test_pdf_path_cannot_escape_registered_storage(self):
        self.bundle["sources"][0]["pdf_path"] = "../../outside.pdf"
        self.bundle_path.write_text(json.dumps(self.bundle), encoding="utf-8")
        self.assertEqual(self.client.get("/admin/sources/synthetic/pdf", headers=self.headers(self.admin)).status_code, 409)

    def test_unknown_source_and_query_are_not_found(self):
        self.assertEqual(self.client.get("/admin/sources/unknown/pdf", headers=self.headers(self.admin)).status_code, 404)
        self.assertEqual(self.client.get("/queries/00000000-0000-0000-0000-000000000000", headers=self.headers(self.plus)).status_code, 404)

    def test_pagination_bounds_are_enforced(self):
        for url in ["/queries?limit=101", "/queries?offset=-1", "/admin/reviews?limit=0"]:
            self.assertEqual(self.client.get(url, headers=self.headers(self.admin)).status_code, 422)

    def test_first_admin_bootstrap_cannot_overwrite_existing_admin(self):
        with self.assertRaises(StateError):
            self.store.create_user("second-admin", self.password_hash, "pro", "admin", bootstrap=True)

    def test_weak_signing_secret_rejected(self):
        with self.assertRaises(ValueError):
            Settings(self.root, self.settings.db_path, "short")


if __name__ == "__main__":
    unittest.main()
