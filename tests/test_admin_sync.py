"""Admin browser controls use current-role JWT auth, never the scheduler secret."""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from gst_rag.api import create_app
from gst_rag.auth import Settings, issue_token
from gst_rag.store import Store


class AdminSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = Settings(self.root, self.root / "app.sqlite3", "j" * 48, worker_enabled=False,
                                 generation="off", notification_sync_enabled=True, notification_sync_secret="s" * 48)
        self.store = Store(self.settings.db_path)
        self.admin = self.store.create_user("admin", "unused-synthetic-hash", "pro", "admin")
        self.user = self.store.create_user("user", "unused-synthetic-hash", "plus")
        self.auth = {"Authorization": "Bearer " + issue_token(self.admin, self.settings)}
        self.user_auth = {"Authorization": "Bearer " + issue_token(self.user, self.settings)}
        self.app = create_app(self.settings, self.store, sync_runner=lambda: {
            "active_corpus_changed": False, "published": 0, "errors": [], "staged_versions": 1})
        self.http = self.enterContext(TestClient(self.app))

    def test_admin_reads_settings_and_safe_history_without_service_secret(self):
        response = self.http.get("/admin/ingestion/sync", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json(), {"enabled": True, "worker_ready": True, "max_pages": 1,
                                           "max_documents": 2, "since_year": 2025, "jobs": []})
        self.assertNotIn(self.settings.notification_sync_secret, response.text)

    def test_researcher_and_anonymous_cannot_read_or_start_imports(self):
        for headers, status in [({}, 401), (self.user_auth, 403)]:
            with self.subTest(status=status):
                self.assertEqual(self.http.get("/admin/ingestion/sync", headers=headers).status_code, status)
                self.assertEqual(self.http.post("/admin/ingestion/sync", json={}, headers=headers | {"Idempotency-Key": "admin-test"}).status_code, status)

    def test_admin_starts_deduplicated_job(self):
        headers = self.auth | {"Idempotency-Key": "admin:request-1"}
        first = self.http.post("/admin/ingestion/sync", json={}, headers=headers)
        second = self.http.post("/admin/ingestion/sync", json={}, headers=headers)
        self.assertEqual((first.status_code, second.status_code), (202, 202))
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(len(self.http.get("/admin/ingestion/sync", headers=self.auth).json()["jobs"]), 1)

    def test_sync_secret_still_does_not_grant_admin_access(self):
        headers = {"Authorization": "Bearer " + self.settings.notification_sync_secret}
        self.assertEqual(self.http.get("/admin/ingestion/sync", headers=headers).status_code, 401)
        self.assertEqual(self.http.post("/admin/ingestion/sync", json={}, headers=headers | {"Idempotency-Key": "a"}).status_code, 401)
        self.assertEqual(self.http.post("/internal/notification-sync/jobs", json={}, headers=self.auth | {"Idempotency-Key": "a"}).status_code, 401)

    def test_current_database_role_wins_over_old_admin_token(self):
        with self.store.connection() as db:
            db.execute("UPDATE users SET role='user' WHERE id=?", (self.admin["id"],))
        self.assertEqual(self.http.get("/admin/ingestion/sync", headers=self.auth).status_code, 403)

    def test_disabled_worker_status_readable_but_cannot_trigger(self):
        self.settings.notification_sync_enabled = False
        self.assertFalse(self.http.get("/admin/ingestion/sync", headers=self.auth).json()["enabled"])
        self.assertEqual(self.http.post("/admin/ingestion/sync", json={}, headers=self.auth | {"Idempotency-Key": "a"}).status_code, 503)

    def test_admin_cannot_choose_external_urls_or_publication_options(self):
        for body in [{"url": "https://evil.test"}, {"publish": True}]:
            with self.subTest(body=body):
                self.assertEqual(self.http.post("/admin/ingestion/sync", json=body, headers=self.auth | {"Idempotency-Key": "a"}).status_code, 422)

    def test_missing_request_key_rejected(self):
        self.assertEqual(self.http.post("/admin/ingestion/sync", json={}, headers=self.auth).status_code, 422)


if __name__ == "__main__":
    unittest.main()
