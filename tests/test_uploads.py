"""Synthetic upload/replacement checks. No user PDF, provider call or real approval."""
from io import BytesIO
import json
import time
import unittest

from docling_core.types.doc import DoclingDocument, DocItemLabel, ProvenanceItem, BoundingBox
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, TextStringObject
from pydantic import ValidationError

from gst_rag.api import create_app
from gst_rag.auth import Settings, issue_token
from gst_rag.ingestion import write_json
from gst_rag.models import BookReview, UploadReservation, NotificationReview
from gst_rag.notification_sync import digest, exclusive_run, run
from gst_rag.service import Corpus
from gst_rag.store import StateError, Store
from gst_rag.uploads import Uploads, UploadWorker, validate_pdf, MAX_BYTES
from test_notification_publication import Fixture, TEXTS


def pdf_bytes(title="synthetic", pages=1, encrypt=False, active=False):
    writer = PdfWriter()
    for _ in range(pages): writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Title": title})
    if encrypt: writer.encrypt("test-fixture-password")
    if active:
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("synthetic-only")})
    stream = BytesIO(); writer.write(stream); return stream.getvalue()


def upload_parser(pdf, directory, metadata):
    directory.mkdir(parents=True, exist_ok=True)
    document = DoclingDocument(name="Synthetic uploaded source")
    for text in TEXTS:
        document.add_text(label=DocItemLabel.TEXT, text=text, prov=ProvenanceItem(page_no=1, charspan=(0, len(text)),
                          bbox=BoundingBox(l=0, r=100, t=100, b=90, coord_origin="BOTTOMLEFT")))
    document.save_as_json(directory / "docling.json")
    kind, sha = metadata["source_type"], digest(pdf.read_bytes())
    document_id = kind + "-" + sha[:16]
    write_json(directory / "manifest.json", {"document_id": document_id, "sha256": sha, "source_type": kind,
                                             "plan_required": "pro" if kind == "firm_book" else "plus", "page_count": 1})
    text = "\n".join(TEXTS)
    return {"schema": "admin-upload-staging-v1", "source_sha256": sha, "document_id": document_id,
        "page_count": 1, "candidate": metadata, "docling_sha256": digest((directory / "docling.json").read_bytes()),
        "review_status": "pending_source_metadata_review", "eligible_for_retrieval": False,
        "warnings": ["Synthetic parser, not a live Docling conversion"],
        "records": [{"chunk_id": document_id + ":1", "document_id": document_id, "source_type": kind,
                     "plan_required": "pro" if kind == "firm_book" else "plus", "text": text, "embedding_text": text,
                     "pages": [1], "source_refs": [f"#/texts/{i}" for i in range(5)], "token_count": 40,
                     "eligible_for_retrieval": False}]}


class UploadFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.uploads = Uploads(self.root, self.publisher, parser=upload_parser)

    def reserve(self, kind="firm_book", replacement=None, title="Synthetic uploaded book", content=None, **kwargs):
        content = content or pdf_bytes(title)
        payload = {"title": title, "source_type": kind, "sha256": digest(content), "byte_count": len(content),
                   "replaces_document_id": replacement, **kwargs}
        return self.uploads.reserve(UploadReservation(**payload), self.actor), content

    def staged(self, **kwargs):
        row, body = self.reserve(**kwargs); self.uploads.receive(row["id"], body, self.actor)
        with exclusive_run(self.sync_root / "upload-worker"): self.uploads.process_one()
        return self.uploads.get(row["id"], self.actor)

    def review(self, row, action="approve", **kwargs):
        return self.uploads.review_book(row["id"], BookReview(revision=row["revision"], stage_sha256=row["stage_sha256"],
            action=action, reason="Synthetic source and structure review", source_checked=action == "approve", structure_checked=action == "approve", **kwargs), self.actor)


class PdfValidationTests(unittest.TestCase):
    def test_valid_pdf_is_structurally_checked(self): self.assertEqual(validate_pdf(pdf_bytes()), 1)

    def test_fake_envelope_not_enough(self):
        for body in [b"not PDF", b"%PDF-1.4\nNOT_A_PDF\n%%EOF"]:
            with self.subTest(body=body), self.assertRaises(StateError): validate_pdf(body)

    def test_encrypted_pdf_refused(self):
        with self.assertRaisesRegex(StateError, "encrypted_pdf_not_supported"): validate_pdf(pdf_bytes(encrypt=True))

    def test_active_pdf_content_refused(self):
        with self.assertRaisesRegex(StateError, "active_pdf_content"): validate_pdf(pdf_bytes(active=True))

    def test_page_count_bounded(self):
        with self.assertRaisesRegex(StateError, "uploaded_pdf_page_limit"): validate_pdf(pdf_bytes(pages=501))


class UploadTests(UploadFixture):
    def test_reservation_does_not_write_pdf_or_change_active_corpus(self):
        row, _ = self.reserve()
        self.assertEqual(row["status"], "awaiting_upload")
        self.assertEqual(self.active_path.read_bytes(), self.before)
        self.assertFalse((self.sync_root / "pdfs" / (row["sha256"] + ".pdf")).exists())

    def test_reservation_and_transfer_idempotent(self):
        first, body = self.reserve(); second, _ = self.reserve()
        self.assertEqual(first["id"], second["id"])
        self.uploads.receive(first["id"], body, self.actor)
        self.assertEqual(self.uploads.receive(first["id"], body, self.actor)["status"], "uploaded_queued")
        self.assertEqual(len(self.uploads.list(self.actor)), 1)

    def test_source_types_determine_plan_never_client_plan(self):
        for kind in ["icai_book", "firm_book"]:
            row = self.staged(kind=kind, title=kind + " sample")
            detail = self.uploads.detail(row["id"], self.actor)
            self.assertTrue(all(r["plan_required"] == ("pro" if kind == "firm_book" else "plus") and not r["eligible_for_retrieval"] for r in detail["draft_chunks"]))

    def test_bad_hash_or_byte_count_does_not_queue(self):
        row, body = self.reserve()
        for bad in [body + b"x", body[:-1] + b"x"]:
            with self.assertRaisesRegex(StateError, "upload_size_or_digest_mismatch"): self.uploads.receive(row["id"], bad, self.actor)
        self.assertEqual(self.uploads.get(row["id"], self.actor)["status"], "awaiting_upload")

    def test_nonadmin_denied(self):
        row, _ = self.reserve()
        for call in [lambda: self.uploads.list({"role": "user"}), lambda: self.uploads.get(row["id"], {"role": "user"})]:
            with self.assertRaises(StateError) as caught: call()
            self.assertEqual(caught.exception.status, 403)

    def test_notification_identity_required_and_verified_with_anchors(self):
        with self.assertRaisesRegex(StateError, "notification_identity_required"): self.reserve(kind="notification")
        row = self.staged(kind="notification", series="central_tax_rate", number=8, year=2025)
        detail = self.publisher.detail(row["id"], self.actor)
        body = self.body | {"stage_sha256": detail["stage_sha256"]}
        self.publisher.review(row["id"], NotificationReview(**body), self.actor)
        self.assertEqual(self.uploads.get(row["id"], self.actor)["review_status"], "approved")
        with self.assertRaises(StateError): self.uploads.review_book(row["id"], BookReview(revision=1, stage_sha256=row["stage_sha256"], action="reject", reason="Synthetic reason"), self.actor)

    def test_books_are_not_listed_in_notification_inbox(self):
        row = self.staged()
        self.assertNotIn(row["id"], {r["id"] for r in self.publisher.list_sources(self.actor)})

    def test_book_review_requires_actual_checks_and_stale_hash_is_rejected(self):
        row = self.staged()
        with self.assertRaises(ValidationError): BookReview(revision=0, stage_sha256=row["stage_sha256"], action="approve", reason="Unchecked approval")
        self.review(row)
        with self.assertRaisesRegex(StateError, "stale_source_review"): self.review(row)

    def test_rejection_keeps_pdf_and_does_not_require_false_attestations(self):
        row = self.staged(); self.review(row, "reject")
        self.assertEqual(self.uploads.get(row["id"], self.actor)["review_status"], "rejected")
        self.assertTrue(self.publisher.pdf(row["id"], self.actor).exists())
        with self.assertRaisesRegex(StateError, "source_review_missing_or_changed"): self.publisher.prepare([row["id"]], self.base, self.actor)

    def test_parse_error_is_redacted_retryable_and_recovers_after_restart(self):
        row, body = self.reserve(); self.uploads.receive(row["id"], body, self.actor)
        self.uploads.parser = lambda *args: (_ for _ in ()).throw(RuntimeError("PRIVATE_PDF_PATH_OR_CONTENT"))
        self.uploads.process_one(); failed = self.uploads.get(row["id"], self.actor)
        self.assertEqual(failed["status"], "upload_parse_failed"); self.assertNotIn("PRIVATE", json.dumps(failed))
        self.uploads.retry(row["id"], self.actor); self.uploads.parser = upload_parser
        with self.uploads.registry() as registry:
            registry.db.execute("UPDATE versions SET status='parsing' WHERE id=?", (row["id"],)); registry.db.commit()
        self.uploads.recover(); self.uploads.process_one()
        self.assertEqual(self.uploads.get(row["id"], self.actor)["status"], "pending_source_metadata_review")

    def test_cross_type_same_hash_is_rejected_even_in_staging(self):
        _, content = self.reserve(kind="firm_book")
        with self.assertRaisesRegex(StateError, "source_hash_conflicting_classification"): self.reserve(kind="icai_book", content=content)

    def test_replacement_type_and_target_bound_to_current_source(self):
        with self.assertRaisesRegex(StateError, "replacement_source_type_mismatch"): self.reserve(kind="icai_book", replacement="firm_book")
        with self.assertRaisesRegex(StateError, "replacement_target_not_active"): self.reserve(replacement="not-registered")

    def test_new_book_can_be_reviewed_prepared_verified_and_explicitly_activated(self):
        row = self.staged(); self.review(row)
        publication = self.publisher.prepare([row["id"]], self.base, self.actor)
        self.assertEqual(self.active_path.read_bytes(), self.before)
        self.publisher.index(publication["id"], "bm25")
        self.assertEqual(self.active_path.read_bytes(), self.before)
        self.publisher.activate(publication["id"], self.base, self.actor, "bm25", "unused")
        self.assertEqual(len(Corpus(self.root).records), 3)
        with self.assertRaisesRegex(StateError, "active_source_review_frozen"): self.review(row)

    def test_replacement_retires_chunks_but_preserves_original_pdf_identity(self):
        original = Corpus(self.root).pdf_path("firm_book"); before_bytes = original.read_bytes()
        row = self.staged(replacement="firm_book"); self.review(row)
        publication = self.publisher.prepare([row["id"]], self.base, self.actor)
        self.publisher.index(publication["id"], "bm25"); self.publisher.activate(publication["id"], self.base, self.actor, "bm25", "unused")
        corpus = Corpus(self.root)
        self.assertFalse(any(r["document_id"] == "firm_book" for r in corpus.records))
        self.assertTrue(corpus.sources["firm_book"]["archived"])
        self.assertEqual(corpus.pdf_path("firm_book").read_bytes(), before_bytes)
        self.assertTrue(any(r["source_type"] == "firm_book" and r["plan_required"] == "pro" for r in corpus.records))
        self.assertEqual(len(corpus.sources), 3)

    def test_replacement_target_changes_before_prepare_fail_closed(self):
        row = self.staged(replacement="firm_book"); self.review(row)
        bundle = json.loads(self.active_path.read_bytes()); bundle["sources"][1]["archived"] = True
        write_json(self.active_path, bundle)
        with self.assertRaisesRegex(StateError, "replacement_target_changed"):
            self.publisher.prepare([row["id"]], digest(self.active_path.read_bytes()), self.actor)

    def test_corrupted_stage_not_approved(self):
        row = self.staged()
        with self.uploads.registry() as registry:
            version = registry.db.execute("SELECT stage_path FROM versions WHERE id=?", (row["id"],)).fetchone()
            registry.path(version[0]).write_bytes(b"CHANGED")
        with self.assertRaises(StateError): self.review(row)

    def test_oversized_or_wrong_page_chunks_cannot_be_approved(self):
        for field, value in [("token_count", 513), ("pages", [2])]:
            with self.subTest(field=field):
                def bad_parser(pdf, directory, metadata):
                    staged = upload_parser(pdf, directory, metadata)
                    staged["records"][0][field] = value
                    return staged
                self.uploads.parser = bad_parser
                row = self.staged(title="Invalid chunk " + field)
                with self.assertRaisesRegex(StateError, "uploaded_chunk_review_failed"):
                    self.review(row)
                self.assertEqual(self.active_path.read_bytes(), self.before)

    def test_unsafe_parser_policy_fails_private_staging(self):
        def unsafe_parser(pdf, directory, metadata):
            staged = upload_parser(pdf, directory, metadata)
            staged["records"][0]["plan_required"] = "plus"
            return staged
        self.uploads.parser = unsafe_parser
        row = self.staged(kind="firm_book")
        self.assertEqual(row["status"], "upload_parse_failed")
        with self.assertRaises(StateError): self.uploads.detail(row["id"], self.actor)
        self.assertEqual(self.active_path.read_bytes(), self.before)


class UploadApiTests(UploadFixture):
    def setUp(self):
        super().setUp()
        settings = Settings(self.root, self.root / "users.db", "j" * 48, worker_enabled=False, generation="off", upload_worker_enabled=True)
        self.store = Store(settings.db_path)
        admin = self.store.create_user("admin", "unused-fixture-hash", "pro", "admin")
        user = self.store.create_user("user", "unused-fixture-hash", "plus")
        self.auth = {"Authorization": "Bearer " + issue_token(admin, settings)}
        self.user_auth = {"Authorization": "Bearer " + issue_token(user, settings)}
        self.app = create_app(settings, self.store, publications=self.publisher, upload_parser=upload_parser)
        self.http = self.enterContext(TestClient(self.app))
        self.content = pdf_bytes("API fixture")
        self.payload = {"title": "Synthetic API upload", "source_type": "firm_book", "sha256": digest(self.content), "byte_count": len(self.content)}

    def test_all_upload_routes_require_current_admin(self):
        version_id = "a" * 64
        for method, path, body in [("GET", "/admin/uploads", None), ("POST", "/admin/uploads", self.payload),
                                   ("GET", f"/admin/uploads/{version_id}", None), ("GET", f"/admin/uploads/{version_id}/detail", None),
                                   ("GET", f"/admin/uploads/{version_id}/pdf", None), ("PUT", f"/admin/uploads/{version_id}/pdf", None),
                                   ("PUT", f"/admin/uploads/{version_id}/review", {"revision": 0, "stage_sha256": "b" * 64, "action": "reject", "reason": "Synthetic rejection"}),
                                   ("POST", f"/admin/uploads/{version_id}/retry", None)]:
            for headers, status in [({}, 401), (self.user_auth, 403)]:
                with self.subTest(path=path, status=status):
                    self.assertEqual(self.http.request(method, path, headers=headers, **({"json": body} if body else {})).status_code, status)

    def test_streaming_upload_queue_detail_and_protected_pdf(self):
        response = self.http.post("/admin/uploads", json=self.payload, headers=self.auth)
        self.assertEqual(response.status_code, 201); version_id = response.json()["id"]
        received = self.http.put(f"/admin/uploads/{version_id}/pdf", content=self.content, headers=self.auth | {"Content-Type": "application/pdf"})
        self.assertEqual(received.status_code, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = self.http.get(f"/admin/uploads/{version_id}", headers=self.auth).json()
            if row["status"] == "pending_source_metadata_review": break
            time.sleep(.01)
        self.assertEqual(row["status"], "pending_source_metadata_review")
        self.assertEqual(self.http.get(f"/admin/uploads/{version_id}/detail", headers=self.auth).status_code, 200)
        pdf = self.http.get(f"/admin/uploads/{version_id}/pdf", headers=self.auth)
        self.assertEqual(pdf.content, self.content); self.assertEqual(pdf.headers["Cache-Control"], "no-store")
        self.assertEqual(self.active_path.read_bytes(), self.before)

    def test_declared_size_and_media_type_are_enforced(self):
        version_id = self.http.post("/admin/uploads", json=self.payload, headers=self.auth).json()["id"]
        self.assertEqual(self.http.put(f"/admin/uploads/{version_id}/pdf", content=self.content, headers=self.auth | {"Content-Type": "text/html"}).status_code, 415)
        self.assertEqual(self.http.put(f"/admin/uploads/{version_id}/pdf", content=self.content + b"extra", headers=self.auth | {"Content-Type": "application/pdf"}).status_code, 413)

    def test_client_cannot_supply_plan_or_server_path(self):
        for field, value in [("plan_required", "plus"), ("pdf_path", "C:/Windows/escape.pdf")]:
            self.assertEqual(self.http.post("/admin/uploads", json=self.payload | {field: value}, headers=self.auth).status_code, 422)


if __name__ == "__main__": unittest.main()
