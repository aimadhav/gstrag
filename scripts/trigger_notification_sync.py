"""Dependency-free GitHub client: enqueue once, poll safely, never send PDFs/keys to providers."""

import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


class ClientError(ValueError):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.retryable = retryable


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def backend_url(value):
    # An explicitly configured HTTPS origin and optional simple deployment prefix.
    # No query, userinfo, fragments, dot segments, whitespace or arbitrary status URLs.
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9_-]+)*/?", value):
        raise ClientError("invalid_backend_url")
    try:
        parts = urlsplit(value)
        if not parts.hostname or (parts.port is not None and not 1 <= parts.port <= 65535):
            raise ValueError()
    except ValueError:
        raise ClientError("invalid_backend_url") from None
    return value.rstrip("/")


def request_json(method, url, headers, body, timeout):
    # No ambient proxy, redirects, cookies or .netrc credentials. Normal TLS verification.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ClientError("oversized_sync_response")
            if response.headers.get_content_type() != "application/json":
                raise ClientError("invalid_sync_response")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ClientError("invalid_sync_response")
            return result
    except HTTPError as exc:
        status = exc.code
        exc.close()
        # Never print HTTP bodies, URLs, Location headers or exception text.
        raise ClientError(f"sync_http_{status}", retryable=status in {429, 502, 503, 504}) from None
    except (URLError, TimeoutError, OSError):
        raise ClientError("sync_transport_error", retryable=True) from None
    except ClientError:
        raise
    except (ValueError, UnicodeError):
        raise ClientError("invalid_sync_response") from None


def run(base, secret, key, request=request_json, sleep=time.sleep, clock=time.monotonic,
        wait_seconds=600, poll_seconds=5):
    base = backend_url(base)
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret):
        raise ClientError("invalid_sync_secret_configuration")
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", key):
        raise ClientError("invalid_sync_request_key")
    if not 1 <= wait_seconds <= 900 or not 0 < poll_seconds <= 30:
        raise ClientError("invalid_poll_configuration")
    deadline = clock() + wait_seconds
    headers = {"Authorization": "Bearer " + secret, "Content-Type": "application/json",
               "Accept": "application/json", "Idempotency-Key": key}
    url = base + "/internal/notification-sync/jobs"

    def call(method, target, body=None):
        for attempt in range(3):
            remaining = deadline - clock()
            if remaining <= 0:
                raise ClientError("sync_poll_timeout_backend_job_may_still_run")
            try:
                return request(method, target, headers, body, min(20, remaining))
            except ClientError as exc:
                if not exc.retryable or attempt == 2:
                    raise
                sleep(min(2 ** attempt, max(0, deadline - clock())))

    def validate(row, expected=None):
        try:
            job_id = str(UUID(row["id"]))
            status = row["status"]
            if status not in {"queued", "running", "completed", "completed_with_errors", "failed"}:
                raise ValueError()
            if expected is not None and job_id != expected:
                raise ValueError()
            return job_id, status
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ClientError("invalid_sync_response") from None

    row = call("POST", url, b"{}")
    job_id, status = validate(row)
    while status in {"queued", "running"}:
        if clock() >= deadline:
            raise ClientError("sync_poll_timeout_backend_job_may_still_run")
        sleep(min(poll_seconds, max(0, deadline - clock())))
        row = call("GET", url + "/" + job_id)
        _, status = validate(row, job_id)
    # Only a safe summary is returned to the runner log, not raw backend responses.
    return {"id": job_id, "status": status}


def main():
    try:
        result = run(os.environ.get("GST_BACKEND_URL", ""), os.environ.get("GST_NOTIFICATION_SYNC_SECRET", ""),
                     os.environ.get("GST_SYNC_REQUEST_KEY", ""))
        print(json.dumps(result))
        return 0 if result["status"] == "completed" else 1
    except ClientError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except Exception:
        print(json.dumps({"error": "sync_client_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
