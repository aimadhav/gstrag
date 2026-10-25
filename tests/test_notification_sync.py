"""Deterministic transport/discovery/staging tests; no network or provider calls."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import requests

from gst_rag.notification_feed import (OfficialClient, SOURCES, SyncError, discover, parse_listing, safe_url)
from gst_rag.notification_sync import (Registry, digest, exclusive_run, main, run)


RATE = SOURCES["cgst_rate"][0]
TAX = SOURCES["cgst_tax"][0]
PDF = "https://gstcouncil.gov.in/sites/default/files/test.pdf"
PDF_BODY = b"%PDF-1.4\nSYNTHETIC_TRANSPORT_FIXTURE\n%%EOF"
ROBOTS = b"User-agent: *\nAllow: /\n"


def listing(label="08/2025-Central Tax (Rate)", href="/sites/default/files/test.pdf", next_page=None,
            extra="", serial=False):
    first_header = "<th>Sr. No.</th>" if serial else ""
    first_cell = "<td>1</td>" if serial else ""
    return (f"<table><tr>{first_header}<th>Notification No. &amp; Date of Issue</th><th>English</th>"
            f"<th>Hindi</th><th>Subject</th></tr><tr>{first_cell}<td>{label}</td>"
            f'<td><a href="{href}">View</a></td><td><a href="/hindi.pdf">Hindi</a></td>'
            f"<td>Illustrative subject, not legal advice</td></tr>{extra}</table>"
            + (f'<nav><a rel="next" href="{next_page}">Next page</a></nav>' if next_page else ""))


class Response:
    def __init__(self, body=b"", status=200, media="text/html", **headers):
        self.body, self.status_code = body, status
        self.headers = {"Content-Type": media, **headers}

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]


class Session:
    def __init__(self, mapping=None, robots=ROBOTS):
        self.mapping, self.robots, self.calls = mapping or {}, robots, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.mapping.get(url)
        if result is None and url.endswith("/robots.txt"):
            return Response(self.robots, media="text/plain")
        if isinstance(result, list): result = result.pop(0)
        if isinstance(result, Exception): raise result
        if result is None: raise AssertionError("Unexpected fake HTTP request")
        return result

    def close(self): pass


class Feed:
    def __init__(self, html=None, pdfs=None):
        self.html, self.pdfs, self.calls = html or {RATE: listing()}, pdfs or {PDF: PDF_BODY}, []

    def get(self, url, kind):
        self.calls.append((url, kind))
        result = (self.html if kind == "html" else self.pdfs)[url]
        if isinstance(result, Exception): raise result
        return (result.encode() if isinstance(result, str) else result), url


def stage_fixture(pdf, directory, metadata):
    return {"source_sha256": digest(pdf.read_bytes()), "eligible_for_retrieval": False,
            "review_status": "pending_source_metadata_review", "candidate": metadata,
            "issued_on": None, "effective_from": None,
            "records": [{"text": "Synthetic draft chunk", "source_refs": ["#/texts/0"], "pages": [1],
                         "source_type": "notification", "plan_required": "plus", "eligible_for_retrieval": False}]}


class TransportTests(unittest.TestCase):
    def client(self, session): return OfficialClient(session, sleep=lambda _: None, pause=0)

    def test_reject_nonofficial_http_credentials_ports_and_controls(self):
        for url in ["http://gstcouncil.gov.in/a.pdf", "https://evil.test/a.pdf", "https://gstcouncil.gov.in.evil.test/a.pdf",
                    "https://user:password@gstcouncil.gov.in/a.pdf", "https://gstcouncil.gov.in:8080/a.pdf",
                    "https://gstcouncil.gov.in/\na.pdf", "https://gstcouncil.gov.in\\@evil.test/a.pdf"]:
            with self.subTest(url=url), self.assertRaises(SyncError): safe_url(url)

    def test_pdf_fetch_obeys_robots_and_never_disables_tls_or_auto_redirects(self):
        session = Session({PDF: Response(PDF_BODY, media="application/pdf")})
        body, final = self.client(session).get(PDF, "pdf")
        self.assertEqual((body, final), (PDF_BODY, PDF))
        self.assertTrue(session.calls[0][0].endswith("/robots.txt"))
        for _, kwargs in session.calls:
            self.assertIs(kwargs["allow_redirects"], False)
            self.assertNotIn("verify", kwargs)
            self.assertNotIn("Authorization", kwargs["headers"])

    def test_disallowed_robots_blocks_actual_document_request(self):
        session = Session(robots=b"User-agent: *\nDisallow: /sites/\n")
        with self.assertRaisesRegex(SyncError, "robots_disallows"):
            self.client(session).get(PDF, "pdf")
        self.assertEqual(len(session.calls), 1)

    def test_robots_unavailable_fails_closed(self):
        session = Session({"https://gstcouncil.gov.in/robots.txt": Response(status=403)})
        with self.assertRaisesRegex(SyncError, "source_http_403"):
            self.client(session).get(PDF, "pdf")
        self.assertEqual(len(session.calls), 1)

    def test_missing_robots_404_allows_public_path(self):
        session = Session({"https://gstcouncil.gov.in/robots.txt": Response(status=404), PDF: Response(PDF_BODY, media="application/pdf")})
        self.assertEqual(self.client(session).get(PDF, "pdf")[0], PDF_BODY)

    def test_html_challenge_instead_of_robots_is_not_accepted(self):
        with self.assertRaisesRegex(SyncError, "unrecognized_robots"):
            self.client(Session(robots=b"<html>Challenge</html>")).get(PDF, "pdf")

    def test_unsafe_redirect_not_fetched(self):
        session = Session({PDF: Response(status=302, Location="https://evil.test/a.pdf")})
        with self.assertRaisesRegex(SyncError, "unsafe_source_url"):
            self.client(session).get(PDF, "pdf")
        self.assertEqual(len(session.calls), 2)

    def test_allowed_redirect_checks_destination_robots(self):
        target = "https://www.gstcouncil.gov.in/sites/default/files/new.pdf"
        session = Session({PDF: Response(status=302, Location=target), target: Response(PDF_BODY, media="application/pdf")})
        self.assertEqual(self.client(session).get(PDF, "pdf")[1], target)
        self.assertTrue(any(url == "https://www.gstcouncil.gov.in/robots.txt" for url, _ in session.calls))

    def test_retry_transient_error_but_defer_long_retry_after(self):
        session = Session({PDF: [Response(status=503), Response(PDF_BODY, media="application/pdf")]})
        self.assertEqual(self.client(session).get(PDF, "pdf")[0], PDF_BODY)
        session = Session({PDF: Response(status=429, **{"Retry-After": "90"})})
        with self.assertRaisesRegex(SyncError, "retry_deferred"):
            self.client(session).get(PDF, "pdf")

    def test_tls_failure_never_retried_with_verification_disabled(self):
        session = Session({PDF: requests.exceptions.SSLError("synthetic")})
        with self.assertRaisesRegex(SyncError, "tls_validation_failed"):
            self.client(session).get(PDF, "pdf")
        self.assertEqual(len(session.calls), 2)

    def test_wrong_content_type_and_pdf_envelope_rejected(self):
        for response in [Response(b"<html>not PDF</html>"), Response(b"%PDF-broken", media="application/pdf")]:
            with self.subTest(response=response), self.assertRaises(SyncError):
                self.client(Session({PDF: response})).get(PDF, "pdf")

    def test_declared_and_streamed_size_limits(self):
        for response in [Response(b"x", media="application/pdf", **{"Content-Length": "20000001"}),
                         Response(b"x" * 2_000_001)]:
            with self.subTest(response=response), self.assertRaises(SyncError):
                self.client(Session({PDF: response})).get(PDF, "pdf" if "Content-Length" in response.headers else "html")


class DiscoveryTests(unittest.TestCase):
    def test_english_relative_link_and_heading_based_tax_columns(self):
        rows, following = parse_listing(listing("11/2025-Central Tax", serial=True), TAX, "central_tax")
        self.assertEqual(rows[0].identity, "central_tax:11/2025:en")
        self.assertEqual(rows[0].pdf_url, PDF)
        self.assertIsNone(following)

    def test_series_separation_and_leading_zero_canonicalization(self):
        rate, _ = parse_listing(listing(), RATE, "central_tax_rate")
        tax, _ = parse_listing(listing("08/2025-Central Tax"), TAX, "central_tax")
        self.assertNotEqual(rate[0].identity, tax[0].identity)
        self.assertEqual(rate[0].number, "8")
        with self.assertRaisesRegex(SyncError, "series_or_number"):
            parse_listing(listing(), TAX, "central_tax")

    def test_missing_table_empty_table_and_wrong_identity_are_failures(self):
        for html in ["<html>service unavailable</html>", listing().split("<tr><td>")[0] + "</table>", listing("Unknown news item")]:
            with self.subTest(html=html), self.assertRaises(SyncError):
                parse_listing(html, RATE, "central_tax_rate")

    def test_missing_english_pdf_and_unsafe_pdf_are_not_silently_skipped(self):
        for html in [listing().replace(f'<a href="/sites/default/files/test.pdf">View</a>', ""),
                     listing(href="https://evil.test/a.pdf"), listing(href="/node/123")]:
            with self.subTest(html=html), self.assertRaises(SyncError): parse_listing(html, RATE, "central_tax_rate")

    def test_corrigendum_has_separate_identity_without_guessed_target_or_year(self):
        rows, _ = parse_listing(listing("Corrigendum"), RATE, "central_tax_rate")
        self.assertEqual(rows[0].kind, "corrigendum")
        self.assertIsNone(rows[0].number)
        self.assertIsNone(rows[0].year)

    def test_bounded_pagination_is_reported_not_claimed_complete(self):
        feed = Feed({RATE: listing(next_page="?page=1")})
        result = discover(feed, ["cgst_rate"], 1)
        self.assertTrue(result["bounded_scan"])
        self.assertEqual(result["sources"][0]["deferred_next_page"], RATE + "?page=1")
        self.assertFalse(result["current_law_verified"])

    def test_two_pages_and_year_filter_keep_unknown_year_corrigenda(self):
        feed = Feed({RATE: listing(next_page="?page=1"), RATE + "?page=1": listing("Corrigendum", href="/corr.pdf")})
        result = discover(feed, ["cgst_rate"], 2, 2026)
        self.assertFalse(result["bounded_scan"])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertIsNone(result["candidates"][0]["year"])

    def test_repeated_pages_and_unsafe_pagination_fail(self):
        html = listing(next_page="?page=1")
        result = discover(Feed({RATE: html, RATE + "?page=1": html}), ["cgst_rate"], 2)
        self.assertEqual(result["errors"][0]["error"], "pagination_repeated_body")
        for url in ["https://evil.test/?page=1", "/user/login?page=1", "?page=1&other=x"]:
            with self.subTest(url=url), self.assertRaises(SyncError): parse_listing(listing(next_page=url), RATE, "central_tax_rate")

    def test_invalid_bounds_and_duplicate_sources_rejected(self):
        for sources, pages, year in [([], 1, 2025), (["cgst_rate"] * 2, 1, 2025), (["state_feed"], 1, 2025), (["cgst_rate"], 0, 2025)]:
            with self.subTest(sources=sources, pages=pages), self.assertRaises(SyncError): discover(Feed(), sources, pages, year)

    def test_missing_next_marker_does_not_claim_the_last_page(self):
        html = listing() + '<nav><a href="?page=1">Page 2</a></nav>'
        with self.assertRaisesRegex(SyncError, "pagination_next_link_missing"):
            parse_listing(html, RATE, "central_tax_rate")


class RegistryAndStagingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "sync"

    def execute(self, feed=None, **kwargs):
        return run(self.root, feed or Feed(), sources=["cgst_rate"], parser=stage_fixture, **kwargs)

    def registry(self):
        registry = Registry(self.root)
        self.addCleanup(registry.close)
        return registry

    def test_repeat_run_deduplicates_download_and_parse(self):
        with patch("gst_rag.notification_sync.docling_stage", side_effect=AssertionError("not the injected parser")):
            first = self.execute(parse=True)
            second = self.execute(parse=True)
        self.assertEqual(first["downloaded_new_versions"], 1)
        self.assertEqual(first["staged_versions"], 1)
        self.assertEqual(second["unchanged_versions"], 1)
        self.assertEqual(second["staged_versions"], 0)
        self.assertEqual(self.registry().summary()["version_counts"], {"pending_source_metadata_review": 1})

    def test_changed_pdf_keeps_old_revision(self):
        self.execute()
        second = self.execute(Feed(pdfs={PDF: PDF_BODY.replace(b"FIXTURE", b"REVISION")}))
        self.assertEqual(second["downloaded_new_versions"], 1)
        self.assertEqual(len(list((self.root / "pdfs").glob("*.pdf"))), 2)
        self.assertEqual(self.registry().summary()["version_counts"], {"downloaded": 2})

    def test_metadata_never_guesses_dates_and_staging_never_publishes(self):
        result = self.execute(parse=True)
        row = self.registry().summary()["versions"][0]
        data = json.loads((self.root / row["stage_path"]).read_text())
        self.assertFalse(data["eligible_for_retrieval"])
        self.assertIsNone(data["effective_from"])
        self.assertEqual(result["published"], 0)
        self.assertFalse(result["active_corpus_changed"])

    def test_offline_stage_needs_no_network(self):
        self.execute()
        result = run(self.root, stage_only=True, parser=stage_fixture)
        self.assertEqual(result["staged_versions"], 1)

    def test_parse_failure_is_retryable_without_redownload(self):
        self.execute()
        with patch("gst_rag.notification_sync.docling_stage", side_effect=AssertionError):
            failed = run(self.root, stage_only=True, parser=lambda *args: (_ for _ in ()).throw(RuntimeError("private error text")))
        self.assertEqual(failed["errors"][0]["error"], "parse_failed:RuntimeError")
        self.assertNotIn("private error text", json.dumps(failed))
        self.assertEqual(run(self.root, stage_only=True, parser=stage_fixture)["staged_versions"], 1)

    def test_interrupted_run_and_parsing_are_recoverable(self):
        self.execute()
        registry = self.registry()
        version = registry.summary()["versions"][0]
        registry.set_version(version["id"], "parsing")
        registry.db.execute("INSERT INTO runs(id,mode,started_at,status) VALUES('interrupted-fixture','stage','2020','running')")
        registry.db.commit()
        self.assertEqual(run(self.root, stage_only=True, parser=stage_fixture)["staged_versions"], 1)
        self.assertEqual(registry.db.execute("SELECT status FROM runs WHERE id='interrupted-fixture'").fetchone()[0], "interrupted")

    def test_overlap_is_rejected_and_lock_releases(self):
        with exclusive_run(self.root), self.assertRaisesRegex(SyncError, "sync_already_running"):
            self.execute()
        self.assertEqual(self.execute()["downloaded_new_versions"], 1)

    def test_bounded_runs_do_not_starve_older_unchecked_entries(self):
        second_row = '<tr><td>07/2025-Central Tax (Rate)</td><td><a href="/second.pdf">View</a></td><td>Hindi</td><td>Other</td></tr>'
        feed = Feed({RATE: listing(extra=second_row)}, {PDF: PDF_BODY, "https://gstcouncil.gov.in/second.pdf": PDF_BODY})
        first, second = self.execute(feed, max_documents=1), self.execute(feed, max_documents=1)
        self.assertEqual(first["deferred_documents"], 1)
        self.assertEqual(second["downloaded_new_versions"], 1)
        self.assertEqual(self.registry().summary()["candidates"], 2)

    def test_one_pdf_failure_does_not_hide_other_outcomes(self):
        row = '<tr><td>07/2025-Central Tax (Rate)</td><td><a href="/second.pdf">View</a></td><td>Hindi</td><td>Other</td></tr>'
        result = self.execute(Feed({RATE: listing(extra=row)}, {PDF: SyncError("source_http_404"), "https://gstcouncil.gov.in/second.pdf": PDF_BODY}))
        self.assertEqual(result["downloaded_new_versions"], 1)
        self.assertEqual(len(result["errors"]), 1)

    def test_failed_discovery_does_not_download_partial_results(self):
        feed = Feed({RATE: listing(next_page="?page=1"), RATE + "?page=1": "<html>broken</html>"})
        result = self.execute(feed, max_pages=2)
        self.assertTrue(result["errors"])
        self.assertFalse(any(kind == "pdf" for _, kind in feed.calls))

    def test_corrupt_saved_pdf_is_not_silently_overwritten(self):
        self.execute()
        saved = next((self.root / "pdfs").glob("*.pdf"))
        saved.write_bytes(b"CORRUPT_SYNTHETIC_FIXTURE")
        self.assertEqual(self.execute()["errors"][0]["error"], "stored_pdf_integrity_failed")
        self.assertEqual(saved.read_bytes(), b"CORRUPT_SYNTHETIC_FIXTURE")

    def test_staging_cannot_opt_itself_into_retrieval(self):
        self.execute()
        def unsafe(*args):
            result = stage_fixture(*args)
            result["eligible_for_retrieval"] = True
            return result
        result = run(self.root, stage_only=True, parser=unsafe)
        self.assertEqual(result["errors"][0]["error"], "unsafe_or_incomplete_staging_result")

    def test_changed_staging_is_not_silently_accepted_as_a_cache_hit(self):
        self.execute(parse=True)
        version = self.registry().summary()["versions"][0]
        (self.root / version["stage_path"]).write_text('SYNTHETIC_CHANGED_STAGING', encoding="utf-8")
        result = self.execute(parse=True)
        self.assertEqual(result["errors"][0]["error"], "stored_staging_integrity_failed")

    def test_path_escape_and_invalid_document_limit_rejected(self):
        with self.assertRaisesRegex(SyncError, "outside_storage"): self.registry().path("../outside.pdf")
        with self.assertRaisesRegex(SyncError, "document_limit"): self.execute(max_documents=0)

    def test_no_active_corpus_or_experiment_changes(self):
        active = self.root.parent / "corpus.json"
        active.write_text("SYNTHETIC_ACTIVE_CORPUS", encoding="utf-8")
        frozen = self.root.parent / "frozen.json"
        frozen.write_text("SYNTHETIC_FROZEN_BENCHMARK", encoding="utf-8")
        self.execute(parse=True)
        self.assertEqual(active.read_text(), "SYNTHETIC_ACTIVE_CORPUS")
        self.assertEqual(frozen.read_text(), "SYNTHETIC_FROZEN_BENCHMARK")

    def test_cli_discovery_is_no_write_and_status_is_no_network(self):
        out = io.StringIO()
        with patch("gst_rag.notification_sync.OfficialClient", return_value=Feed()) as factory, redirect_stdout(out):
            factory.return_value.close = lambda: None
            self.assertEqual(main(["discover", "--source", "cgst_rate", "--root", str(self.root)]), 0)
        self.assertFalse(self.root.exists())
        out = io.StringIO()
        with patch("gst_rag.notification_sync.OfficialClient", side_effect=AssertionError("no network")), redirect_stdout(out):
            self.assertEqual(main(["status", "--root", str(self.root)]), 0)
        self.assertIn("no_ingestion_registry", out.getvalue())


if __name__ == "__main__":
    unittest.main()
