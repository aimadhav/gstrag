"""Small synthetic tests for evidence integrity, permissions, and expansion."""

import re
import unittest

from gst_rag.benchmark import allowed, assemble_context, evidence_recall, group_covered
from gst_rag.chunking import fixed_windows


class WordTokenizer:
    """Deterministic test double for context accounting, not model tokenization."""

    def encode(self, text, **kwargs):
        return re.findall(r"\S+", text)

    def __call__(self, text, **kwargs):
        offsets = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}


def child(text="matching rule", ref="r1", parent="p1", source="firm_book"):
    return {"text": text, "embedding_text": text, "headings": [], "source_refs": [ref],
            "parent_ids": [parent], "pages": [1], "source_type": source, "plan_required": "pro"}


class RetrievalContracts(unittest.TestCase):
    def test_truncated_prefix_is_retokenized_before_accepting_budget(self):
        class PrefixSensitiveTokenizer(WordTokenizer):
            def encode(self, text, **kwargs):
                tokens = super().encode(text, **kwargs)
                return tokens + ["prefix-only-extra-token"] if text == "one two" else tokens
        context, used, _ = assemble_context([child("one two three")], [], [], PrefixSensitiveTokenizer(), 2, "child", "pro")
        self.assertLessEqual(used, 2)
        self.assertEqual(context[0]["embedding_text"], "one")
        self.assertTrue(context[0]["truncated_for_budget"])

    def test_same_item_id_is_not_proof_of_evidence(self):
        group = [{"source_refs": ["r1"], "quote": "missing exception"}]
        self.assertFalse(group_covered(group, [child()]))

    def test_quote_in_a_different_item_is_not_proof(self):
        group = [{"source_refs": ["r2"], "quote": "matching rule"}]
        self.assertFalse(group_covered(group, [child()]))

    def test_all_independent_groups_are_required(self):
        groups = [[{"source_refs": ["r1"], "quote": "matching rule"}],
                  [{"source_refs": ["r2"], "quote": "exception"}]]
        self.assertEqual(evidence_recall(groups, [child()]), .5)

    def test_absent_evidence_is_not_counted_as_perfect_recall(self):
        self.assertIsNone(evidence_recall([], [child()]))

    def test_plus_rejects_firm_and_unknown_sources(self):
        self.assertFalse(allowed(child(), "plus"))
        self.assertFalse(allowed(child(source="unknown"), "pro"))
        self.assertTrue(allowed(child(source="notification"), "plus"))

    def test_expansion_preserves_matching_child_when_parent_is_too_large(self):
        hit = child()
        parent = {**hit, "text": "unrelated " * 50 + "matching rule", "parent_id": "p1"}
        parent.pop("embedding_text")
        context, used, fallbacks = assemble_context([hit], [], [parent], WordTokenizer(), 10, "parent", "pro")
        self.assertIn("matching rule", context[0]["embedding_text"])
        self.assertLessEqual(used, 10)
        self.assertEqual(fallbacks, 1)

    def test_parent_is_added_once(self):
        parent = {**child(), "text": "matching rule plus exception", "parent_id": "p1"}
        parent.pop("embedding_text")
        context, used, fallbacks = assemble_context([child(), child("exception")], [], [parent], WordTokenizer(), 4, "parent", "pro")
        self.assertEqual(len(context), 1)
        self.assertEqual(used, 4)
        self.assertEqual(fallbacks, 0)

    def test_parent_with_disallowed_source_is_not_loaded(self):
        parent = {**child(), "parent_id": "p1"}
        with self.assertRaises(KeyError):
            assemble_context([child(source="icai_book")], [], [parent], WordTokenizer(), 20, "parent", "plus")

    def test_neighbor_expansion_stays_in_section(self):
        units = [{"text": "different section", "headings": [], "source_refs": ["r0"], "parent_id": "p0"},
                 {"text": "matching rule", "headings": [], "source_refs": ["r1"], "parent_id": "p1"}]
        context, _, _ = assemble_context([child()], units, [], WordTokenizer(), 20, "neighbors", "pro")
        self.assertFalse(any("different section" in c["embedding_text"] for c in context))

    def test_fixed_windows_cover_source_and_carry_multiple_parents(self):
        units = [{"text": "a b c", "headings": [], "source_refs": ["r1"], "pages": [1], "parent_id": "p1"},
                 {"text": "d e f", "headings": [], "source_refs": ["r2"], "pages": [2], "parent_id": "p2"}]
        windows = fixed_windows(units, WordTokenizer(), 4, 1)
        self.assertEqual(windows[0]["parent_ids"], ["p1", "p2"])
        self.assertEqual({r for w in windows for r in w["source_refs"]}, {"r1", "r2"})
        self.assertTrue(all(len(WordTokenizer().encode(w["embedding_text"])) <= 4 for w in windows))


if __name__ == "__main__":
    unittest.main()
