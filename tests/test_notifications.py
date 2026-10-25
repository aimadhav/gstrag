"""Small deterministic notification/date/access contracts; no network or LLM."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from docling_core.types.doc import DoclingDocument, DocItemLabel, ProvenanceItem, BoundingBox

from gst_rag.notifications import (notification_key, explicit_references, english_date, reviewed_records,
    book_links, check_updates, public_status, update_context, qualified_group_covered)
from test_retrieval_contracts import WordTokenizer


def notification(key="8/2021", issued="2021-09-30", effective="2021-10-01"):
    text = "Complete condition and exception"
    return {"chunk_id": key, "document_id": "notification-" + key, "source_type": "notification", "plan_required": "plus",
        "text": text, "embedding_text": text, "source_refs": ["#/texts/0"], "pages": [1],
        "evidence_spans": [{"source_ref": "#/texts/0", "quote": text, "pages": [1]}],
        "notification": {"key": notification_key(key), "issued_on": issued, "effective_from": effective,
                         "topic_id": "solar", "source_url": "https://example.test/private.pdf"}}


class IdentityAndDates(unittest.TestCase):
    def test_leading_zero_number_is_canonical(self):
        self.assertEqual(notification_key("08/2021"), notification_key("8/2021"))

    def test_notification_series_must_be_explicit(self):
        self.assertEqual(explicit_references("08/2021-central tax (rate)"), {"central_tax_rate:8/2021"})
        self.assertFalse(explicit_references("08/2021-Central Tax"))
        self.assertFalse(explicit_references("08/2021-Integrated Tax (Rate)"))

    def test_invalid_notification_number_rejected(self):
        for number in ["0/2021", "8/21", "08/2021-Central Tax"]:
            with self.assertRaises(ValueError): notification_key(number)

    def test_parse_ordinal_dates_and_split_docling_suffix(self):
        self.assertEqual(english_date("New Delhi, the 30 th September, 2021"), "2021-09-30")
        self.assertEqual(english_date("force on the 1 st day of October, 2021."), "2021-10-01")

    def test_ambiguous_or_invalid_dates_not_guessed(self):
        for text in ["next October", "31st February, 2021", "1st October, 2021 and 2nd October, 2021"]:
            with self.assertRaises(ValueError): english_date(text)


class UpdateSelection(unittest.TestCase):
    def check(self, when, records=None, plan="plus", topics=("solar",)):
        return check_updates(records if records is not None else [notification()], topics, when, plan)

    def test_issue_day_is_published_but_not_effective(self):
        check = self.check("2021-09-30")
        self.assertFalse(check["candidates"])
        self.assertEqual(len(check["published_not_yet_effective"]), 1)

    def test_effective_day_is_inclusive(self):
        self.assertEqual(len(self.check("2021-10-01")["candidates"]), 1)

    def test_not_yet_published_source_not_used_for_earlier_date(self):
        check = self.check("2021-09-29")
        self.assertFalse(check["candidates"])
        self.assertFalse(check["published_not_yet_effective"])

    def test_keep_both_amendments_not_only_newest(self):
        records = [notification(), notification("24/2018", "2018-12-31", "2019-01-01")]
        self.assertEqual([r["chunk_id"] for r in self.check("2021-10-01", records)["candidates"]], ["24/2018", "8/2021"])

    def test_missing_date_requires_clarification(self):
        check = self.check(None)
        self.assertEqual(check["status"], "clarification_required")
        self.assertFalse(check["candidates"])

    def test_empty_topic_or_empty_corpus_does_not_prove_no_updates(self):
        for check in [self.check("2023-01-01", []), self.check("2023-01-01", topics=("other",))]:
            self.assertEqual(check["status"], "review_required")
            self.assertFalse(check["current_law_verified"])

    def test_unknown_plan_rejected(self):
        with self.assertRaises(ValueError): self.check("2023-01-01", plan="admin-from-browser")

    def test_relevant_notification_checked_without_any_book_hit(self):
        check = self.check("2023-01-01")
        self.assertEqual(len(check["candidates"]), 1)
        self.assertEqual(check["status"], "review_required")

    def test_no_automatic_current_law_claim_for_later_date(self):
        check = self.check("2026-10-21")
        self.assertEqual(check["status"], "review_required")
        self.assertFalse(check["current_law_verified"])


class AccessAndPacking(unittest.TestCase):
    def setUp(self):
        self.notice = notification()
        self.book = {"chunk_id": "firm:1", "document_id": "firm", "source_type": "firm_book", "plan_required": "pro",
                     "text": "See 08/2021-Central Tax (Rate)", "embedding_text": "firm opinion", "source_refs": ["#/texts/0"], "pages": [2]}

    def test_explicit_book_link_is_candidate_not_approval(self):
        links = book_links([self.book], [self.notice])
        self.assertEqual(links[0]["status"], "candidate_pending_admin_review")

    def test_plus_never_sees_private_book_link(self):
        records = [self.book, self.notice]
        links = book_links([self.book], [self.notice])
        self.assertFalse(check_updates(records, ["solar"], "2023-01-01", "plus", links)["links"])
        self.assertEqual(len(check_updates(records, ["solar"], "2023-01-01", "pro", links)["links"]), 1)

    def test_public_status_drops_draft_passages_pdf_urls_and_internal_links(self):
        check = check_updates([self.notice, self.book], ["solar"], "2023-01-01", "pro")
        check["draft"] = "Unapproved private answer"
        payload = public_status(check)
        self.assertEqual(set(payload), {"status", "message"})
        self.assertEqual(payload["status"], "pending_review")
        self.assertNotIn("pdf", json.dumps(payload))
        self.assertNotIn("private", json.dumps(payload))

    def test_full_notification_condition_reserved_before_books(self):
        check = check_updates([self.notice], ["solar"], "2023-01-01", "pro")
        context, _, reason = update_context(check, [self.book], WordTokenizer(), 5, "pro")
        self.assertEqual(context[0]["text"], self.notice["text"])
        self.assertFalse(context[0]["truncated_for_budget"])
        self.assertEqual(reason, "notification_evidence_reserved")

    def test_over_budget_notification_is_not_truncated(self):
        check = check_updates([self.notice], ["solar"], "2023-01-01", "plus")
        context, used, reason = update_context(check, [], WordTokenizer(), 2, "plus")
        self.assertEqual((context, used), ([], 0))
        self.assertIn("over_budget", reason)

    def test_disallowed_book_context_rejected(self):
        check = check_updates([self.notice], ["solar"], "2023-01-01", "plus")
        with self.assertRaises(ValueError): update_context(check, [self.book], WordTokenizer(), 100, "plus")

    def test_pdf_local_source_refs_must_be_qualified_by_document(self):
        group = [{"document_id": "other-notification", "source_refs": ["#/texts/0"], "quote": "Complete condition"}]
        self.assertFalse(qualified_group_covered(group, [self.notice]))
        group[0]["document_id"] = self.notice["document_id"]
        self.assertTrue(qualified_group_covered(group, [self.notice]))

    def test_quote_must_belong_to_the_claimed_span_not_another_span(self):
        group = [{"document_id": self.notice["document_id"], "source_refs": ["#/texts/1"], "quote": "Complete condition"}]
        self.notice["source_refs"].append("#/texts/1")
        self.notice["evidence_spans"].append({"source_ref": "#/texts/1", "quote": "Different text", "pages": [1]})
        self.assertFalse(qualified_group_covered(group, [self.notice]))


class ReviewBinding(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        doc = DoclingDocument(name="notification_fixture")
        texts = ["Notification No. 8/2021-Central Tax (Rate)", "30th September, 2021", "1st October, 2021",
                 "Amends No.1/2017-Central Tax (Rate)", "Full condition and exception"]
        for text in texts:
            doc.add_text(label=DocItemLabel.TEXT, text=text, prov=ProvenanceItem(page_no=1, charspan=(0, len(text)),
                bbox=BoundingBox(l=0, r=100, t=100, b=90, coord_origin="BOTTOMLEFT")))
        doc.save_as_json(self.root / "docling.json")
        self.manifest = {"document_id": "notice", "sha256": "original-pdf", "source_type": "notification", "plan_required": "plus"}
        (self.root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        self.review = {"document_id": "notice", "source_sha256": "original-pdf",
            "docling_sha256": hashlib.sha256((self.root / "docling.json").read_bytes()).hexdigest(),
            "review_status": "source_audited", "reviewer_type": "assistant", "number": "8/2021", "amends": "1/2017",
            "issued_on": "2021-09-30", "effective_from": "2021-10-01", "source_url": "https://example.test/source",
            "anchors": {key: {"source_ref": f"#/texts/{i}", "pages": [1], "quote": texts[i]}
                        for i, key in enumerate(["identity", "issued_on", "effective_from", "amends"])},
            "clauses": [{"id": "condition", "topic_id": "solar", "subject": "Condition", "source_refs": ["#/texts/4"],
                         "provisions": ["entry"], "operative_change": "Inserts condition"}]}

    def build(self):
        path = self.root / "review.json"
        path.write_text(json.dumps(self.review), encoding="utf-8")
        return reviewed_records(self.root, path, WordTokenizer())

    def test_valid_review_retains_condition_and_evidence(self):
        records = self.build()
        self.assertIn("Full condition and exception", records[0]["text"])
        self.assertEqual(records[0]["notification"]["effective_to"], None)
        self.assertEqual(records[0]["notification"]["rate_scope"], "cgst_only")

    def test_wrong_pdf_or_parse_rejected(self):
        for field in ["source_sha256", "docling_sha256"]:
            original = self.review[field]
            self.review[field] = "changed"
            with self.assertRaises(ValueError): self.build()
            self.review[field] = original

    def test_invented_date_rejected(self):
        self.review["effective_from"] = "2021-09-30"
        with self.assertRaises(ValueError): self.build()

    def test_wrong_page_rejected(self):
        self.review["anchors"]["identity"]["pages"] = [2]
        with self.assertRaises(ValueError): self.build()

    def test_wrong_notification_identity_rejected(self):
        self.review["number"] = "9/2021"
        with self.assertRaises(ValueError): self.build()

    def test_unknown_clause_ref_rejected(self):
        self.review["clauses"][0]["source_refs"] = ["#/texts/999"]
        with self.assertRaises(ValueError): self.build()

    def test_unreviewed_metadata_rejected(self):
        self.review["review_status"] = "draft"
        with self.assertRaises(ValueError): self.build()


if __name__ == "__main__":
    unittest.main()
