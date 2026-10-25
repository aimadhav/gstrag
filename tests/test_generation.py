"""Synthetic provider/validator tests. No real Gemini key or network required."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import requests

from gst_rag.auth import Settings
from gst_rag.generation import (DraftingService, GeminiClient, GeneratedAnswer, GenerationError, PROMPT,
                                normalized_quote, render_answer, validate_answer)

BOOK = "A synthetic book condition applies only when both supplied requirements are met."
NOTICE = "This synthetic notification changes the condition from the stated effective date."


def packet(source="icai_book"):
    return {"status": "review_required", "context_tokens": 45, "plan_used": "pro" if source == "firm_book" else "plus",
        "history_used_as_evidence": False, "review_reasons": ["incomplete_amendment_chain"],
        "citations": [{"citation_id": key, "source_type": kind, "excerpt": text, "pages": [1],
                       "pdf_url": "/admin/sources/PRIVATE_PDF/pdf", "source_name": "PRIVATE_SOURCE_NAME", "source_refs": ["private_ref"]}
                      for key, kind, text in [("S1", source, BOOK), ("S2", "notification", NOTICE)]]}


def job(plan="plus"):
    return {"question": "Synthetic question?", "as_of": "2023-03-01", "topic_ids": '["other_gst"]',
            "plan_at_retrieval": plan, "parent_query_id": "PRIVATE_PREVIOUS_QUERY", "old_answer": "PRIVATE_OLD_PRO_ANSWER"}


def answer():
    return {"status": "draft", "book_explanation": [{"text": "Synthetic book explanation.",
            "evidence": [{"citation_id": "S1", "quote": BOOK}]}],
        "latest_notification": [{"text": "Synthetic notification explanation.", "evidence": [{"citation_id": "S2", "quote": NOTICE}]}],
        "practical_effect": [{"text": "Synthetic practical conclusion for human review.", "evidence": [{"citation_id": "S2", "quote": NOTICE}]}],
        "limitations": ["Only synthetic excerpts are supplied."], "review_flags": [], "clarification_question": ""}


class Provider:
    def __init__(self, raw=None):
        self.raw = raw if raw is not None else answer()
        self.calls, self.callback, self.error = [], None, None

    def generate(self, data):
        self.calls.append(copy.deepcopy(data))
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return copy.deepcopy(self.raw), {"promptTokenCount": 12, "candidatesTokenCount": 20}


class Response:
    status_code = 200
    content = b"synthetic-wire-response"

    def __init__(self, payload=None):
        self.payload = payload or {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer())}]}}],
            "usageMetadata": {"totalTokenCount": 32, "PRIVATE_METADATA": "private"}}

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return copy.deepcopy(self.payload)


class Session:
    def __init__(self):
        self.response, self.calls, self.error = Response(), [], None

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(Path("."), Path("unused-db"), "x" * 32, gemini_key="SYNTHETIC_SECRET_KEY")
        self.provider = Provider()
        self.drafter = DraftingService(self.settings, self.provider)

    def run_draft(self, evidence=None, request=None):
        return self.drafter.draft(request or job(), evidence if evidence is not None else packet())

    def reject(self, expected, evidence=None, request=None):
        result, text = self.run_draft(evidence, request)
        self.assertEqual(result["generation"], expected)
        self.assertIsNone(text)
        self.assertNotIn("generated_answer", result)
        return result

    def test_valid_draft_remains_review_required(self):
        result, text = self.run_draft()
        self.assertEqual(result["generation"], "validated_private_draft")
        self.assertEqual(result["status"], "review_required")
        self.assertIn("Book explanation", text)
        self.assertIn("Latest notification (loaded evidence only)", text)
        self.assertIn("Practical effect", text)
        self.assertIn("[S1]", text)
        self.assertIn("[S2]", text)
        self.assertEqual(result["generation_details"]["citation_ids"], ["S1", "S2"])
        self.assertFalse(result["generation_details"]["citation_checks_prove_entailment"])
        self.assertIn("explicit_admin_approval_required", result["review_reasons"])

    def test_no_key_keeps_manual_workflow_without_provider_call(self):
        self.settings.gemini_key = None
        self.reject("not_configured")
        self.assertEqual(self.provider.calls, [])

    def test_explicit_off_never_calls_provider(self):
        self.settings.generation = "off"
        self.reject("disabled")
        self.assertEqual(self.provider.calls, [])

    def test_no_evidence_never_calls_provider(self):
        evidence = packet()
        evidence["citations"] = []
        self.reject("no_evidence", evidence)
        self.assertEqual(self.provider.calls, [])

    def test_plus_firm_evidence_rejected_before_provider(self):
        evidence = packet("firm_book")
        evidence["plan_used"] = "plus"
        self.reject("evidence_policy_rejected", evidence)
        self.assertEqual(self.provider.calls, [])

    def test_firm_privacy_opt_in_required(self):
        self.reject("firm_content_requires_privacy_opt_in", packet("firm_book"), job("pro"))
        self.assertEqual(self.provider.calls, [])

    def test_explicit_firm_opt_in_allows_pro_but_never_approves(self):
        self.settings.gemini_allow_firm_content = True
        result, text = self.run_draft(packet("firm_book"), job("pro"))
        self.assertIsNotNone(text)
        self.assertIn("firm_source_requires_opinion_review", result["review_reasons"])
        self.assertEqual(result["status"], "review_required")

    def test_packet_plan_mismatch_rejected(self):
        evidence = packet()
        evidence["plan_used"] = "pro"
        self.reject("evidence_policy_rejected", evidence)
        self.assertEqual(self.provider.calls, [])

    def test_history_evidence_rejected(self):
        evidence = packet()
        evidence["history_used_as_evidence"] = True
        self.reject("evidence_policy_rejected", evidence)

    def test_duplicate_evidence_id_rejected(self):
        evidence = packet()
        evidence["citations"].append(evidence["citations"][0])
        self.reject("evidence_policy_rejected", evidence)

    def test_missing_pages_or_excerpt_rejected(self):
        for field, value in [("pages", []), ("pages", [0]), ("pages", [True]), ("excerpt", ""), ("citation_id", "BAD")]:
            evidence = packet()
            evidence["citations"][0][field] = value
            self.reject("evidence_policy_rejected", evidence)
        self.assertEqual(self.provider.calls, [])

    def test_input_char_and_context_caps_before_call(self):
        evidence = packet()
        evidence["context_tokens"] = 2049
        self.reject("evidence_policy_rejected", evidence)
        evidence = packet()
        evidence["citations"][0]["excerpt"] = "synthetic " * 3000
        self.reject("evidence_input_over_budget", evidence)
        self.assertEqual(self.provider.calls, [])

    def test_request_excludes_urls_pages_paths_names_and_old_answers(self):
        self.run_draft()
        data = self.provider.calls[0]
        encoded = json.dumps(data)
        for secret in ["PRIVATE_PDF", "PRIVATE_SOURCE_NAME", "private_ref", "PRIVATE_OLD_PRO_ANSWER", "PRIVATE_PREVIOUS_QUERY", "SYNTHETIC_SECRET_KEY"]:
            self.assertNotIn(secret, encoded)
        self.assertEqual(set(data["evidence"][0]), {"citation_id", "source_type", "excerpt", "truncated_for_budget"})
        self.assertFalse(data["current_law_verified"])

    def test_unknown_model_citation_rejected(self):
        self.provider.raw["book_explanation"][0]["evidence"][0]["citation_id"] = "S999"
        self.reject("generated_citation_unknown")

    def test_invented_or_truncated_away_quote_rejected(self):
        self.provider.raw["book_explanation"][0]["evidence"][0]["quote"] = "An invented exception absent from the source excerpt."
        self.reject("generated_quote_not_in_evidence")

    def test_notification_section_cannot_cite_book(self):
        self.provider.raw["latest_notification"][0]["evidence"] = [{"citation_id": "S1", "quote": BOOK}]
        self.reject("generated_citation_wrong_section")

    def test_book_section_cannot_cite_notification(self):
        self.provider.raw["book_explanation"][0]["evidence"] = [{"citation_id": "S2", "quote": NOTICE}]
        self.reject("generated_citation_wrong_section")

    def test_claim_without_citation_rejected(self):
        self.provider.raw["book_explanation"][0]["evidence"] = []
        self.reject("generated_schema_invalid")

    def test_duplicate_support_rejected(self):
        claim = self.provider.raw["book_explanation"][0]
        claim["evidence"].append(claim["evidence"][0])
        self.reject("generated_duplicate_citation")

    def test_model_urls_and_inline_markers_rejected(self):
        for text, reason in [("See https://example.test/source.pdf", "generated_links_disallowed"),
                             ("Open /admin/sources/source/pdf", "generated_links_disallowed"),
                             ("Synthetic statement [S999]", "model_inline_citations_disallowed")]:
            self.provider.raw = answer()
            self.provider.raw["book_explanation"][0]["text"] = text
            self.reject(reason)

    def test_model_cannot_return_approved_status_or_extra_page_fields(self):
        self.provider.raw["status"] = "approved"
        self.reject("generated_schema_invalid")
        self.provider.raw = answer() | {"pages": [666]}
        self.reject("generated_schema_invalid")

    def test_empty_draft_or_abstention_with_claims_rejected(self):
        self.provider.raw["status"] = "insufficient_evidence"
        self.reject("generated_status_inconsistent")
        self.provider.raw = answer()
        for field in ["book_explanation", "latest_notification", "practical_effect"]:
            self.provider.raw[field] = []
        self.reject("generated_status_inconsistent")

    def test_abstention_stays_for_admin_without_a_draft(self):
        self.provider.raw["status"] = "insufficient_evidence"
        for field in ["book_explanation", "latest_notification", "practical_effect"]:
            self.provider.raw[field] = []
        result, text = self.run_draft()
        self.assertEqual(result["generation"], "insufficient_evidence")
        self.assertIsNone(text)
        self.assertEqual(result["status"], "review_required")

    def test_model_clarification_stays_private_for_admin(self):
        self.provider.raw["status"] = "needs_clarification"
        for field in ["book_explanation", "latest_notification", "practical_effect"]:
            self.provider.raw[field] = []
        self.reject("generated_status_inconsistent")
        self.provider.raw["clarification_question"] = "What are the synthetic transaction facts?"
        result, text = self.run_draft()
        self.assertEqual(result["generation"], "needs_clarification")
        self.assertEqual(result["status"], "review_required")
        self.assertIsNone(text)

    def test_conflict_uncertainty_and_compliance_are_review_flags_not_auto_actions(self):
        self.provider.raw["review_flags"] = ["source_conflict", "effective_date_uncertain", "uncertain"]
        request = job() | {"question": "What is the penalty liability deadline for compliance?"}
        result, text = self.run_draft(request=request)
        self.assertIsNotNone(text)
        self.assertIn("source_conflict", result["review_reasons"])
        self.assertIn("compliance_question_requires_review", result["review_reasons"])
        self.assertEqual(result["status"], "review_required")

    def test_unexpected_provider_error_is_redacted_and_evidence_preserved(self):
        self.provider.error = RuntimeError("PRIVATE_ERROR_AND_KEY")
        result = self.reject("generation_unavailable")
        self.assertEqual(result["citations"], packet()["citations"])
        self.assertNotIn("PRIVATE_ERROR_AND_KEY", json.dumps(result))

    def test_provider_cannot_smuggle_arbitrary_error_code_into_packet(self):
        self.provider.error = GenerationError("PRIVATE_ERROR_AND_KEY")
        result = self.reject("generation_unavailable")
        self.assertNotIn("PRIVATE_ERROR_AND_KEY", json.dumps(result))

    def test_rendered_draft_length_limit_and_no_rejected_body_saved(self):
        claim = lambda cid, quote: {"text": "x" * 900, "evidence": [{"citation_id": cid, "quote": quote}]}
        self.provider.raw["book_explanation"] = [claim("S1", BOOK)] * 5
        self.provider.raw["latest_notification"] = [claim("S2", NOTICE)] * 5
        self.provider.raw["practical_effect"] = [claim("S2", NOTICE)] * 5
        self.provider.raw["limitations"] = ["x" * 500] * 8
        self.reject("generated_answer_over_budget")

    def test_quoted_span_check_does_not_prove_claim_entailment(self):
        # Deliberate counterexample: structurally valid but NOT supported meaning.
        # All drafts remain private precisely because this is not an NLI oracle.
        self.provider.raw["book_explanation"][0]["text"] = "An unrelated synthetic conclusion which the quotation does not establish."
        result, _ = self.run_draft()
        self.assertEqual(result["generation"], "validated_private_draft")
        self.assertFalse(result["generation_details"]["citation_checks_prove_entailment"])
        self.assertEqual(result["status"], "review_required")

    def test_original_packet_not_mutated(self):
        original = packet()
        self.run_draft(original)
        self.assertEqual(original, packet())

    def test_settings_repr_redacts_key_and_rejects_model_path(self):
        self.assertNotIn("SYNTHETIC_SECRET_KEY", repr(self.settings))
        for model in ["../../bad", "gemini-test?key=bad", "https://evil.test"]:
            with self.assertRaises(ValueError):
                Settings(Path("."), Path("db"), "x" * 32, gemini_model=model)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(Path("."), Path("db"), "x" * 32, gemini_key="SYNTHETIC_SECRET_KEY")
        self.session = Session()
        self.client = GeminiClient(self.settings, self.session)

    def test_request_has_fixed_host_header_key_schema_no_tools_and_bounded_output(self):
        result, usage = self.client.generate({"evidence": [], "question": "synthetic"})
        self.assertEqual(result, answer())
        self.assertEqual(usage, {"totalTokenCount": 32})
        url, kwargs = self.session.calls[0]
        self.assertEqual(url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent")
        self.assertNotIn("SYNTHETIC_SECRET_KEY", url)
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "SYNTHETIC_SECRET_KEY")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (5, 45))
        self.assertEqual(kwargs["json"]["generationConfig"]["maxOutputTokens"], 4096)
        self.assertNotIn("tools", kwargs["json"])
        self.assertIn("untrusted data", kwargs["json"]["systemInstruction"]["parts"][0]["text"])

    def test_missing_key_does_not_send(self):
        self.settings.gemini_key = None
        with self.assertRaisesRegex(GenerationError, "not_configured"):
            self.client.generate({})
        self.assertEqual(self.session.calls, [])

    def test_http_errors_redirects_and_timeout_redacted_no_retry(self):
        for status in [400, 401, 403, 429, 500, 307]:
            self.session.response.status_code = status
            with self.assertRaisesRegex(GenerationError, "provider_unavailable"):
                self.client.generate({})
        self.session.error = requests.Timeout("PRIVATE_ERROR_KEY")
        with self.assertRaises(GenerationError) as caught:
            self.client.generate({})
        self.assertNotIn("PRIVATE_ERROR_KEY", str(caught.exception))
        self.assertEqual(len(self.session.calls), 7)

    def test_prompt_safety_block_rejected(self):
        self.session.response.payload["promptFeedback"] = {"blockReason": "SAFETY"}
        with self.assertRaisesRegex(GenerationError, "provider_safety_blocked"):
            self.client.generate({})

    def test_safety_block_or_incomplete_candidate_rejected(self):
        for reason, expected in [("SAFETY", "provider_safety_blocked"), ("RECITATION", "provider_safety_blocked"),
                                 ("MAX_TOKENS", "provider_response_incomplete"), ("OTHER", "provider_response_incomplete")]:
            self.session.response.payload["candidates"][0]["finishReason"] = reason
            with self.assertRaisesRegex(GenerationError, expected):
                self.client.generate({})

    def test_blocked_safety_rating_rejected_even_if_stop(self):
        self.session.response.payload["candidates"][0]["safetyRatings"] = [{"blocked": True}]
        with self.assertRaisesRegex(GenerationError, "provider_safety_blocked"):
            self.client.generate({})

    def test_malformed_candidate_or_json_rejected(self):
        for payload in [{"candidates": []}, {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]},
                        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not JSON"}]}}]},
                        ValueError("PRIVATE_ERROR")]:
            self.session.response.payload = payload
            with self.assertRaisesRegex(GenerationError, "provider_response_invalid"):
                self.client.generate({})

    def test_response_size_limit_enforced(self):
        self.session.response.content = b"x" * 131073
        with self.assertRaisesRegex(GenerationError, "provider_response_invalid"):
            self.client.generate({})

    def test_thoughts_and_tool_calls_are_not_treated_as_answer(self):
        for part in [{"text": "private reasoning", "thought": True}, {"functionCall": {"name": "fake"}}]:
            self.session.response.payload["candidates"][0]["content"]["parts"] = [part]
            with self.assertRaisesRegex(GenerationError, "provider_response_invalid"):
                self.client.generate({})


if __name__ == "__main__":
    unittest.main()
