"""Hosted queue/API/client tests: temporary storage, fake transport, no real keys."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import uuid

from fastapi.testclient import TestClient

from gst_rag.api import create_app
from gst_rag.auth import Settings, issue_token
from gst_rag.notification_feed import SyncError
from gst_rag.notification_sync import Registry, run as import_run
from gst_rag.store import StateError
from gst_rag.sync_jobs import SyncJobs, SyncWorker, import_notifications
from scripts import trigger_notification_sync as client
from test_notification_sync import Feed, RATE, TAX, listing, stage_fixture

SECRET = "s" * 48
AUTH = {"Authorization": "Bearer " + SECRET}
JOB_ID = str(uuid.uuid4())


def report(**kwargs):
    return {"active_corpus_changed": False, "published": 0, "errors": [], **kwargs}


def wait_for(jobs, job_id):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        row = jobs.get(job_id)
        if row["status"] in {"completed", "completed_with_errors", "failed"}:
            return row
        time.sleep(.01)
    raise AssertionError("Synthetic job did not finish")


class TempCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.jobs = SyncJobs(self.root / "data/app/notification_sync")

    def worker(self, runner):
        worker = SyncWorker(self.jobs, runner)
        worker.start()
        self.addCleanup(worker.close)
        return worker

    def settings(self, **kwargs):
        return Settings(self.root, self.root / "users.sqlite3", "j" * 48,
                        worker_enabled=False, generation="off", **kwargs)


class QueueTests(TempCase):
    def test_persistent_enqueue_and_idempotency_even_after_finish(self):
        first = self.jobs.enqueue("github:1:2")
        self.assertEqual(SyncJobs(self.jobs.root).enqueue("github:1:2"), first)
        worker = self.worker(lambda: report())
        finished = wait_for(self.jobs, first["id"])
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(self.jobs.enqueue("github:1:2"), finished)
        worker.close()

    def test_different_trigger_conflicts_instead_of_unbounded_backlog(self):
        self.jobs.enqueue("first")
        with self.assertRaises(StateError) as caught:
            self.jobs.enqueue("second")
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "sync_job_in_progress"))

    def test_racing_same_key_inserts_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(self.jobs.enqueue, ["same"] * 8))
        self.assertEqual(len({r["id"] for r in rows}), 1)

    def test_racing_distinct_keys_accepts_only_one(self):
        def enqueue(key):
            try:
                return self.jobs.enqueue(str(key))["id"]
            except StateError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(enqueue, range(8)))
        self.assertEqual(rows.count("sync_job_in_progress"), 7)

    def test_invalid_key_not_stored(self):
        for value in ["", "x" * 129, "space key", "../path", "\r\n"]:
            with self.subTest(value=value), self.assertRaises(StateError):
                self.jobs.enqueue(value)

    def test_missing_job(self):
        with self.assertRaises(StateError) as caught:
            self.jobs.get(str(uuid.uuid4()))
        self.assertEqual(caught.exception.status, 404)

    def test_result_only_exposes_safe_counts(self):
        row = self.jobs.enqueue("private-key")
        self.worker(lambda: report(staged_versions=1, errors=[{"error": "PRIVATE_CONTENT"}],
                                   discovery={"bounded_scan": True}, path="PRIVATE_CONTENT"))
        finished = wait_for(self.jobs, row["id"])
        self.assertEqual(finished["status"], "completed_with_errors")
        self.assertEqual(finished["result"]["error_count"], 1)
        self.assertTrue(finished["result"]["bounded_scan"])
        self.assertNotIn("PRIVATE_CONTENT", json.dumps(finished))
        self.assertNotIn("private-key", json.dumps(finished))

    def test_raw_exception_redacted(self):
        def fail(): raise RuntimeError("SECRET_AND_PRIVATE_PDF")
        row = self.jobs.enqueue("a")
        self.worker(fail)
        finished = wait_for(self.jobs, row["id"])
        self.assertEqual((finished["status"], finished["error"]), ("failed", "import_failed"))
        self.assertNotIn("SECRET", json.dumps(finished))

    def test_unsafe_runner_result_not_reported_as_success(self):
        row = self.jobs.enqueue("a")
        self.worker(lambda: report(published=1, active_corpus_changed=True))
        self.assertEqual(wait_for(self.jobs, row["id"])["status"], "failed")

    def test_interrupted_job_requeued_on_owner_start(self):
        row = self.jobs.enqueue("a")
        self.jobs.claim()  # Simulate a previous process dying after claiming.
        self.worker(lambda: report())
        finished = wait_for(self.jobs, row["id"])
        self.assertEqual((finished["status"], finished["attempts"]), ("completed", 2))

    def test_second_owner_cannot_recover_live_job(self):
        entered, release = threading.Event(), threading.Event()
        def blocked():
            entered.set()
            release.wait(4)
            return report()
        self.addCleanup(release.set)
        row = self.jobs.enqueue("a")
        first = self.worker(blocked)
        self.assertTrue(entered.wait(2))
        second = SyncWorker(self.jobs, lambda: report())
        try:
            with self.assertRaisesRegex(RuntimeError, "sync_worker_unavailable"):
                second.start()
            self.assertEqual(self.jobs.get(row["id"])["status"], "running")
            self.assertEqual(self.jobs.get(row["id"])["attempts"], 1)
        finally:
            release.set()
            first.close()
            second.close()

    def test_importer_lock_conflict_retries_then_finishes(self):
        calls = []
        def runner():
            calls.append(1)
            if len(calls) == 1:
                raise SyncError("sync_already_running")
            return report()
        row = self.jobs.enqueue("a")
        self.worker(runner)
        self.assertEqual(wait_for(self.jobs, row["id"])["attempts"], 2)

    def test_importer_busy_has_bounded_retries(self):
        def runner(): raise SyncError("sync_already_running")
        row = self.jobs.enqueue("a")
        # Seed two prior attempts without slow sleeps; this is the final retry.
        with self.jobs.connection() as db:
            db.execute("UPDATE jobs SET attempts=2 WHERE id=?", (row["id"],))
        self.worker(runner)
        finished = wait_for(self.jobs, row["id"])
        self.assertEqual((finished["attempts"], finished["error"]), (3, "importer_busy"))

    def test_default_runner_fixed_options_and_client_closed(self):
        settings = self.settings()
        with patch("gst_rag.sync_jobs.OfficialClient") as transport, patch("gst_rag.sync_jobs.run", return_value=report()) as run:
            self.assertEqual(import_notifications(settings), report())
            self.assertEqual(run.call_args.kwargs["sources"], ["cgst_tax", "cgst_rate"])
            self.assertIs(run.call_args.kwargs["parse"], True)
            self.assertEqual(run.call_args.kwargs["max_documents"], 2)
            transport.return_value.close.assert_called_once()

    def test_default_runner_closes_client_on_failure(self):
        with patch("gst_rag.sync_jobs.OfficialClient") as transport, patch("gst_rag.sync_jobs.run", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError): import_notifications(self.settings())
            transport.return_value.close.assert_called_once()


class ApiTests(TempCase):
    def api(self, enabled=True, runner=None):
        settings = self.settings(notification_sync_enabled=enabled, notification_sync_secret=SECRET if enabled else None)
        app = create_app(settings, sync_runner=runner or (lambda: report()))
        return app, TestClient(app)

    def test_disabled_by_default(self):
        app, http = self.api(False)
        with http:
            response = http.post("/internal/notification-sync/jobs", json={}, headers=AUTH | {"Idempotency-Key": "a"})
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(app.state.sync_worker.thread)

    def test_missing_and_wrong_credential(self):
        _, http = self.api()
        with http:
            for auth in [{}, {"Authorization": "Bearer wrong"}]:
                self.assertEqual(http.post("/internal/notification-sync/jobs", json={}, headers=auth | {"Idempotency-Key": "a"}).status_code, 401)

    def test_admin_jwt_is_not_sync_credential_and_reverse(self):
        app, http = self.api()
        token = issue_token({"id": str(uuid.uuid4()), "plan": "pro"}, app.state.settings)
        with http:
            self.assertEqual(http.post("/internal/notification-sync/jobs", json={}, headers={"Authorization": "Bearer " + token, "Idempotency-Key": "a"}).status_code, 401)
            self.assertEqual(http.get("/admin/ingestion/notifications", headers=AUTH).status_code, 401)
            self.assertEqual(http.get("/me", headers=AUTH).status_code, 401)

    def test_strict_empty_body_and_required_key(self):
        _, http = self.api()
        with http:
            self.assertEqual(http.post("/internal/notification-sync/jobs", json={}, headers=AUTH).status_code, 422)
            for body in [{"url": "https://evil.test"}, {"publish": True}, {"parse": False}]:
                self.assertEqual(http.post("/internal/notification-sync/jobs", json=body, headers=AUTH | {"Idempotency-Key": "a"}).status_code, 422)

    def test_trigger_duplicate_and_status(self):
        app, http = self.api()
        with http:
            first = http.post("/internal/notification-sync/jobs", json={}, headers=AUTH | {"Idempotency-Key": "a"})
            self.assertEqual(first.status_code, 202)
            self.assertEqual(first.headers["Cache-Control"], "no-store")
            job = wait_for(app.state.sync_jobs, first.json()["id"])
            duplicate = http.post("/internal/notification-sync/jobs", json={}, headers=AUTH | {"Idempotency-Key": "a"})
            self.assertEqual(duplicate.json()["id"], job["id"])
            self.assertEqual(http.get("/internal/notification-sync/jobs/" + job["id"], headers=AUTH).json(), job)
            self.assertEqual(http.get("/internal/notification-sync/jobs/" + job["id"]).status_code, 401)
            self.assertEqual(http.get("/internal/notification-sync/jobs/" + str(uuid.uuid4()), headers=AUTH).status_code, 404)

    def test_valid_secret_cannot_queue_when_worker_not_started(self):
        _, http = self.api()
        # Intentionally no lifespan startup: no silently abandoned accepted jobs.
        response = http.post("/internal/notification-sync/jobs", json={}, headers=AUTH | {"Idempotency-Key": "a"})
        self.assertEqual(response.status_code, 503)

    def test_health_reports_worker_readiness_without_credentials(self):
        _, http = self.api()
        self.assertEqual(http.get("/health").json()["notification_sync"], "unavailable")
        with http:
            self.assertEqual(http.get("/health").json()["notification_sync"], "ready")
            self.assertNotIn(SECRET, http.get("/health").text)
        _, disabled = self.api(False)
        with disabled:
            self.assertEqual(disabled.get("/health").json()["notification_sync"], "disabled")

    def test_different_http_trigger_rejected_while_one_runs(self):
        entered, release = threading.Event(), threading.Event()
        def blocked():
            entered.set()
            release.wait(3)
            return report()
        _, http = self.api(runner=blocked)
        with http:
            try:
                self.assertEqual(http.post("/internal/notification-sync/jobs", json={}, headers=AUTH | {"Idempotency-Key": "a"}).status_code, 202)
                self.assertTrue(entered.wait(1))
                response = http.post("/internal/notification-sync/jobs", json={}, headers=AUTH | {"Idempotency-Key": "b"})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json(), {"error": "sync_job_in_progress"})
            finally:
                release.set()

    def test_end_to_end_client_api_queue_importer_staging_not_publication(self):
        active = self.root / "data/app/corpus.json"
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_bytes(b"EXISTING_CORPUS_SENTINEL")
        feed = Feed(html={RATE: listing(), TAX: listing("01/2025-Central Tax")})
        app, http = self.api(runner=lambda: import_run(self.jobs.root, client=feed, parse=True, parser=stage_fixture))
        def request(method, url, headers, body, timeout):
            response = http.request(method, url.removeprefix("https://backend.test"), headers=headers, content=body)
            self.assertLess(response.status_code, 300)
            return response.json()
        with http:
            result = client.run("https://backend.test", SECRET, "github:1:1", request=request, poll_seconds=.01)
        self.assertEqual(result["status"], "completed")
        registry = Registry(self.jobs.root)
        try:
            versions = registry.summary()["versions"]
            self.assertEqual(len(versions), 2)
            self.assertTrue(all(v["status"] == "pending_source_metadata_review" for v in versions))
            for version in versions:
                staged = json.loads(registry.path(version["stage_path"]).read_bytes())
                self.assertFalse(staged["eligible_for_retrieval"])
        finally:
            registry.close()
        self.assertEqual(active.read_bytes(), b"EXISTING_CORPUS_SENTINEL")
        self.assertFalse((self.root / "data/app/publications").exists())


class ConfigTests(TempCase):
    def test_sync_settings_safe_defaults(self):
        settings = self.settings()
        self.assertFalse(settings.notification_sync_enabled)
        self.assertIsNone(settings.notification_sync_secret)

    def test_sync_secret_not_in_repr(self):
        self.assertNotIn(SECRET, repr(self.settings(notification_sync_secret=SECRET)))

    def test_invalid_configuration(self):
        for kwargs in [{"notification_sync_enabled": True}, {"notification_sync_secret": "short"},
                       {"notification_sync_secret": "j" * 48}, {"notification_sync_max_pages": 6},
                       {"notification_sync_max_documents": 0}, {"notification_sync_since_year": 1999}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.settings(**kwargs)


class ClientTests(unittest.TestCase):
    def run_client(self, request, **kwargs):
        return client.run("https://backend.test", SECRET, "github:1:2", request=request, sleep=lambda _: None, **kwargs)

    def test_reject_unsafe_backend_urls(self):
        for url in ["http://backend.test", "https://user:pass@backend.test", "https://backend.test/?key=x",
                    "https://backend.test/#x", "https://backend.test/../other", "https://backend.test\n.evil", "https://backend.test:99999"]:
            with self.subTest(url=url), self.assertRaises(client.ClientError): client.backend_url(url)
        self.assertEqual(client.backend_url("https://backend.test/api/"), "https://backend.test/api")

    def test_post_retry_preserves_same_key_and_body(self):
        calls = []
        def request(method, url, headers, body, timeout):
            calls.append((method, url, dict(headers), body))
            if len(calls) == 1: raise client.ClientError("lost_response", retryable=True)
            return {"id": JOB_ID, "status": "completed"}
        self.assertEqual(self.run_client(request)["status"], "completed")
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[0][3], b"{}")

    def test_configuration_errors_stop_before_http(self):
        for secret, key in [("short", "a"), (SECRET, ""), (SECRET, "../command")]:
            calls = []
            with self.subTest(secret_length=len(secret), key=key), self.assertRaises(client.ClientError):
                client.run("https://backend.test", secret, key, request=lambda *args: calls.append(args))
            self.assertFalse(calls)

    def test_polls_only_same_origin_constructed_job_path(self):
        calls = []
        def request(method, url, headers, body, timeout):
            calls.append((method, url))
            return {"id": JOB_ID, "status": "queued" if len(calls) == 1 else "completed", "status_url": "https://evil.test"}
        self.run_client(request)
        self.assertEqual(calls[1], ("GET", "https://backend.test/internal/notification-sync/jobs/" + JOB_ID))

    def test_malformed_or_mismatched_job_rejected(self):
        for row in [{}, {"id": "../../evil", "status": "queued"}, {"id": JOB_ID, "status": "invented"}]:
            with self.subTest(row=row), self.assertRaises(client.ClientError): self.run_client(lambda *args: row)
        rows = iter([{"id": JOB_ID, "status": "queued"}, {"id": str(uuid.uuid4()), "status": "completed"}])
        with self.assertRaises(client.ClientError): self.run_client(lambda *args: next(rows))

    def test_poll_timeout_does_not_cancel_or_claim_backend_success(self):
        ticks = iter(range(20))
        with self.assertRaisesRegex(client.ClientError, "sync_poll_timeout_backend_job_may_still_run"):
            self.run_client(lambda *args: {"id": JOB_ID, "status": "running"}, clock=lambda: next(ticks), wait_seconds=4)

    def test_raw_backend_response_not_returned(self):
        result = self.run_client(lambda *args: {"id": JOB_ID, "status": "failed", "error": "PRIVATE_CONTENT"})
        self.assertEqual(result, {"id": JOB_ID, "status": "failed"})

    def test_permanent_http_failure_not_retried(self):
        with patch.object(client, "request_json", side_effect=AssertionError):
            calls = []
            def request(*args):
                calls.append(1)
                raise client.ClientError("sync_http_401")
            with self.assertRaisesRegex(client.ClientError, "401"): self.run_client(request)
            self.assertEqual(len(calls), 1)

    def test_redirect_handler_refuses_forwarding(self):
        self.assertIsNone(client.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test"))

    def test_http_error_redacted_and_transport_bounded(self):
        with patch.object(client, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("https://PRIVATE.test", 302, "SECRET", {}, io.BytesIO(b"PRIVATE"))
            with self.assertRaisesRegex(client.ClientError, "^sync_http_302$"):
                client.request_json("POST", "https://backend.test", AUTH, b"{}", 1)
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 1)
            self.assertIsInstance(opener.call_args.args[0], client.ProxyHandler)
            self.assertEqual(opener.call_args.args[0].proxies, {})
            self.assertIsInstance(opener.call_args.args[1], client.NoRedirect)

    def test_transport_error_does_not_echo_url(self):
        with patch.object(client, "build_opener") as opener:
            opener.return_value.open.side_effect = URLError("PRIVATE_TOKEN")
            with self.assertRaisesRegex(client.ClientError, "^sync_transport_error$"):
                client.request_json("GET", "https://backend.test", AUTH, None, 1)

    def test_oversized_and_nonjson_response_rejected(self):
        for body, media, expected in [(b"x" * 65537, "application/json", "oversized_sync_response"),
                                      (b"{}", "text/html", "invalid_sync_response"),
                                      (b"not json", "application/json", "invalid_sync_response")]:
            with self.subTest(media=media, size=len(body)), patch.object(client, "build_opener") as opener:
                response = opener.return_value.open.return_value.__enter__.return_value
                response.read.return_value = body
                response.headers = Message()
                response.headers["Content-Type"] = media
                with self.assertRaisesRegex(client.ClientError, "^" + expected + "$"):
                    client.request_json("GET", "https://backend.test", AUTH, None, 1)

    def test_main_fails_on_partial_or_failed_job(self):
        for status in ["completed_with_errors", "failed", "completed"]:
            with self.subTest(status=status), patch.object(client, "run", return_value={"id": JOB_ID, "status": status}), redirect_stdout(io.StringIO()) as out:
                code = client.main()
                self.assertEqual(code, 0 if status == "completed" else 1)
                self.assertEqual(json.loads(out.getvalue())["status"], status)

    def test_unexpected_client_failure_never_prints_raw_error(self):
        with patch.object(client, "run", side_effect=RuntimeError("PRIVATE_TOKEN")), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(client.main(), 1)
            self.assertEqual(json.loads(out.getvalue()), {"error": "sync_client_failed"})

    def test_workflow_is_opt_in_default_branch_only_and_narrow(self):
        import yaml
        workflow = yaml.load((Path(__file__).resolve().parents[1] / ".github/workflows/notification-sync.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow["on"]), {"schedule", "workflow_dispatch"})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(workflow["concurrency"]["cancel-in-progress"], "false")
        job = workflow["jobs"]["stage"]
        self.assertIn("vars.GST_NOTIFICATION_SYNC_ENABLED == 'true'", job["if"])
        self.assertIn("github.event.repository.default_branch", job["if"])
        checkout, trigger = job["steps"]
        self.assertRegex(checkout["uses"], r"^actions/checkout@[0-9a-f]{40}$")
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        self.assertEqual(trigger["run"], "python3 scripts/trigger_notification_sync.py")
        self.assertEqual(set(trigger["env"]), {"GST_BACKEND_URL", "GST_NOTIFICATION_SYNC_SECRET", "GST_SYNC_REQUEST_KEY"})


if __name__ == "__main__":
    unittest.main()
