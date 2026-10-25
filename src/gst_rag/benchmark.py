"""Small retrieval experiment. BM25 is a diagnostic, Jina is the dense run.

No answer model is involved, so retrieval errors can be inspected directly.
"""

import hashlib
import json
import math
import os
import re
import time
import unicodedata
from collections import Counter

from .chunking import contextualize
from .ingestion import read_json, write_json


def normalize(text):
    text = unicodedata.normalize("NFKC", text).lower()
    return " ".join(text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})).split())


def allowed(record, plan):
    sources = {"icai_book", "notification"} | ({"firm_book"} if plan == "pro" else set())
    return record.get("source_type") in sources


def group_covered(group, records):
    """Exact quote evidence, restricted to matching original Docling items.

    Conservative by design: sharing a source ID alone is not enough, because
    two different chunks can be excerpts from the same large source element.
    """
    for alternative in group:
        quote = normalize(alternative["quote"])
        for record in records:
            if set(alternative["source_refs"]) & set(record["source_refs"]):
                text = record.get("embedding_text", record.get("text", ""))
                if quote in normalize(text):
                    return True
    return False


def evidence_recall(groups, records):
    return sum(group_covered(group, records) for group in groups) / len(groups) if groups else None


def verify_heldout_freeze(args, report):
    """A small local guard against scoring before freeze or retuning afterward."""
    if args.split != "heldout":
        return
    path = args.directory / "experiment_freeze.json"
    if not path.exists():
        raise ValueError("Held-out retrieval requires experiment_freeze.json after development checks pass")
    freeze = read_json(path)
    if freeze["config_id"] != report["config_id"] or freeze["question_set_sha256"] != hashlib.sha256(args.questions.read_bytes()).hexdigest():
        raise ValueError("Configuration or question set differs from the frozen experiment")
    for name, checksum in freeze["artifact_sha256"].items():
        if hashlib.sha256((args.directory / name).read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Frozen artifact changed: {name}")
    code_directory = __import__("pathlib").Path(__file__).parent
    for name, checksum in freeze.get("code_sha256", {}).items():
        if hashlib.sha256((code_directory / name).read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Frozen implementation changed: {name}")
    settings = {"retriever": args.retriever, "context_mode": args.context_mode,
                "context_budget": args.context_budget, "plan": args.plan, "top_k": args.top_k,
                "variant": args.variant}
    if settings != freeze["heldout_settings"]:
        raise ValueError("Held-out settings differ from the predeclared evaluation")
    if list(args.directory.glob("benchmark_*_heldout_*.json")):
        raise ValueError("Held-out results already exist; preserve them and do not retune/re-score this frozen experiment")


class BM25:
    def __init__(self, records):
        self.frequencies = [Counter(re.findall(r"\w+", normalize(r["embedding_text"]))) for r in records]
        self.lengths = [sum(f.values()) for f in self.frequencies]
        self.mean_length = sum(self.lengths) / max(len(self.lengths), 1)
        df = Counter(word for f in self.frequencies for word in f)
        self.idf = {word: math.log(1 + (len(records) - n + .5) / (n + .5)) for word, n in df.items()}

    def scores(self, question):
        words = set(re.findall(r"\w+", normalize(question)))
        values = []
        for freq, length in zip(self.frequencies, self.lengths):
            score = 0.0
            for word in words:
                n = freq.get(word, 0)
                if n:
                    denominator = n + 1.2 * (1 - .75 + .75 * length / (self.mean_length or 1))
                    score += self.idf.get(word, 0) * n * 2.2 / denominator
            values.append(score)
        return values


class Jina:
    model = "jina-embeddings-v3"

    def __init__(self, directory):
        from dotenv import load_dotenv
        load_dotenv()
        self.key = os.environ.get("JINA_API_KEY")
        if not self.key:
            raise ValueError("Set JINA_API_KEY in your local .env to run dense retrieval. No API request was made.")
        self.cache_path = directory / "jina_cache.json"
        self.cache = read_json(self.cache_path) if self.cache_path.exists() else {}
        self.tokens = 0
        self.api_seconds = 0.0
        self.requests = 0

    def encode(self, texts, task):
        import requests
        import numpy as np
        keys = [hashlib.sha256(json.dumps([self.model, task, text], ensure_ascii=False).encode()).hexdigest() for text in texts]
        missing = list(dict.fromkeys(k for k in keys if k not in self.cache))
        inputs = dict(zip(keys, texts))
        for start in range(0, len(missing), 16):
            batch = missing[start:start + 16]
            started = time.perf_counter()
            response = requests.post("https://api.jina.ai/v1/embeddings", timeout=120,
                headers={"Authorization": f"Bearer {self.key}"},
                json={"model": self.model, "task": task, "normalized": True, "embedding_type": "float", "truncate": False,
                      "input": [inputs[k] for k in batch]})
            self.api_seconds += time.perf_counter() - started
            self.requests += 1
            if not response.ok:
                raise RuntimeError(f"Jina request returned HTTP {response.status_code}; inspect account/model availability. Response body omitted.")
            payload = response.json()
            vectors = sorted(payload["data"], key=lambda entry: entry["index"])
            if len(vectors) != len(batch) or [v["index"] for v in vectors] != list(range(len(batch))):
                raise ValueError("Unexpected embedding response indices")
            self.cache.update({k: row["embedding"] for k, row in zip(batch, vectors)})
            self.tokens += payload.get("usage", {}).get("total_tokens", 0)
            write_json(self.cache_path, self.cache)
        array = np.array([self.cache[k] for k in keys], dtype="float32")
        if array.size == 0:
            return array
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        if not np.isfinite(array).all() or (norms == 0).any():
            raise ValueError("Invalid or zero embedding vector")
        return array / norms


def assemble_context(hits, units, parents, tokenizer, budget, mode, plan):
    if budget <= 0:
        raise ValueError("Context budget must be positive")
    parent_map = {p["parent_id"]: p for p in parents if allowed(p, plan)}
    context, seen, seen_parent_ids = [], set(), set()
    used, fallbacks = 0, 0

    def add(record):
        nonlocal used
        if not allowed(record, plan):
            raise ValueError("Context contains a disallowed source")
        text = record.get("embedding_text") or contextualize(record["text"], record["headings"])
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in seen:
            return True
        tokens = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        remaining = budget - used
        if remaining <= 0:
            return False
        offsets = tokens["offset_mapping"]
        truncated = len(offsets) > remaining
        if truncated:
            original_text, end = text, remaining
            text = original_text[:offsets[end - 1][1]]
            # A prefix can retokenize differently from the full passage. Check
            # the ACTUAL prefix count, not just the original offset position.
            while len(tokenizer.encode(text, add_special_tokens=False)) > remaining and end:
                end -= 1
                text = original_text[:offsets[end - 1][1]] if end else ""
            if not text:
                return False
        used += len(tokenizer.encode(text, add_special_tokens=False))
        context.append({**record, "embedding_text": text, "truncated_for_budget": truncated})
        seen.add(key)
        return not truncated

    for hit in hits:
        if mode == "parent":
            expanded = [parent_map[pid] for pid in hit["parent_ids"] if pid not in seen_parent_ids]
            if not expanded:
                continue
            size = sum(len(tokenizer.encode(contextualize(p["text"], p["headings"]), add_special_tokens=False)) for p in expanded)
            if size <= budget - used:
                for parent in expanded:
                    add(parent)
                    seen_parent_ids.add(parent["parent_id"])
                continue
            # Do not discard the matching child because its parent is too large.
            fallbacks += 1
        add(hit)
        if mode == "neighbors":
            refs = set(hit["source_refs"])
            positions = [i for i, unit in enumerate(units) if refs & set(unit["source_refs"])]
            neighbors = sorted({j for i in positions for j in [i - 1, i + 1] if 0 <= j < len(units)})
            for i in neighbors:
                # Never expand across section boundaries.
                if units[i]["parent_id"] in hit["parent_ids"]:
                    add({**units[i], "source_type": hit["source_type"], "plan_required": hit["plan_required"]})
    return context, used, fallbacks


def run_benchmark(args):
    from transformers import AutoTokenizer
    import numpy as np

    questions_file = read_json(args.questions)
    if questions_file.get("annotation_status") not in {"reviewed", "source_audited"} and not args.allow_draft_labels:
        raise ValueError("Labels need source review, or --allow-draft-labels for a diagnostic only. Source review is not independent legal validation.")
    output_tag = getattr(args, "output_tag", "")
    if output_tag and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", output_tag):
        raise ValueError("Output tag must contain 1-64 letters, digits, underscores or hyphens")
    report = read_json(args.directory / "chunk_report.json")
    if questions_file["document_id"] != report["config"]["document_id"]:
        raise ValueError("Question evidence belongs to a different document")
    verify_heldout_freeze(args, report)
    questions = [q for q in questions_file["questions"] if q["split"] == args.split]
    if not questions or args.top_k < 10:
        raise ValueError("Need questions in this split and top-k of at least 10")
    tokenizer = AutoTokenizer.from_pretrained(report["config"]["tokenizer"])
    tokenizer.model_max_length = 10**9
    units = read_json(args.directory / "units.json")
    parents = read_json(args.directory / "parents.json")
    for question in questions:
        for group in question["evidence_groups"]:
            if not group_covered(group, units):
                raise ValueError(f"Evidence for {question['id']} is not present in the canonical source. Check labels before making API calls.")
    jina = Jina(args.directory) if args.retriever == "jina" else None
    if jina and report["config"]["tokenizer"] != "jinaai/jina-embeddings-v3":
        raise ValueError("Dense benchmark requires the matching Jina-v3 tokenizer; rebuild chunks")
    query_vectors = jina.encode([q["question"] for q in questions], "retrieval.query") if jina else None
    output = {"config_id": report["config_id"], "retriever": args.retriever,
              "question_set_sha256": hashlib.sha256(args.questions.read_bytes()).hexdigest(),
              "top_k": args.top_k,
              "scope": "lexical diagnostic, not a dense retrieval result" if not jina else "Jina dense retrieval",
              "annotation_status": questions_file["annotation_status"], "split": args.split,
              "context_mode": args.context_mode, "context_budget": args.context_budget,
              "plan": args.plan, "variants": {}}
    variants = ["fixed", "hierarchical", "hybrid"] if args.variant == "all" else [args.variant]
    for variant in variants:
        records = [json.loads(line) for line in (args.directory / f"chunks_{variant}.jsonl").read_text(encoding="utf-8").splitlines()]
        records = [r for r in records if allowed(r, args.plan)]
        dense_vectors = jina.encode([r["embedding_text"] for r in records], "retrieval.passage") if jina and records else None
        ranker = BM25(records) if not jina else None
        rows = []
        for index, question in enumerate(questions):
            started = time.perf_counter()
            scores = (dense_vectors @ query_vectors[index]).tolist() if jina and records else ranker.scores(question["question"]) if ranker else []
            order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:args.top_k]
            hits = [records[i] for i in order]
            search_ms = (time.perf_counter() - started) * 1000
            groups = question["evidence_groups"]
            context, used, fallbacks = assemble_context(hits, units, parents, tokenizer, args.context_budget, args.context_mode, args.plan)
            first = next((i + 1 for i, hit in enumerate(hits) if any(group_covered(g, [hit]) for g in groups)), None)
            recall10 = evidence_recall(groups, hits[:10])
            rows.append({"question_id": question["id"], "question": question["question"],
                         "expected": question["expected"], "evidence_recall_at_5": evidence_recall(groups, hits[:5]),
                         "evidence_recall_at_10": recall10, "complete_at_10": recall10 == 1 if groups else None,
                         "reciprocal_rank_at_10": 1 / first if first and first <= 10 else 0 if groups else None,
                         "context_evidence_recall": evidence_recall(groups, context), "context_tokens": used,
                         "oversize_parent_fallbacks": fallbacks, "search_ms": round(search_ms, 3),
                         "hits": [{"chunk_id": hit["chunk_id"], "pages": hit["pages"], "score": scores[i]} for i, hit in zip(order, hits)],
                         "context": context})
        def average(field):
            values = [r[field] for r in rows if r[field] is not None]
            return round(sum(values) / len(values), 4) if values else None
        output["variants"][variant] = {"questions": len(rows), "answerable_questions": sum(bool(q["evidence_groups"]) for q in questions),
            "summary": {field: average(field) for field in ["evidence_recall_at_5", "evidence_recall_at_10", "complete_at_10", "reciprocal_rank_at_10", "context_evidence_recall", "context_tokens", "search_ms"]},
            "rows": rows}
    if jina:
        output["api_usage_this_run"] = {"tokens": jina.tokens, "requests": jina.requests, "seconds": round(jina.api_seconds, 3), "model": jina.model}
    output["notes"] = ["No answer generation or abstention policy was evaluated.",
                       "No-evidence questions are excluded from evidence-recall averages.",
                       "Search timing excludes embedding and context assembly; API time is reported separately.",
                       "Exact quote coverage is conservative and does not establish answer correctness."]
    suffix = f"_{output_tag}" if output_tag else ""
    path = args.directory / f"benchmark_{args.retriever}_{args.split}_{args.context_mode}_{args.plan}_{args.variant}{suffix}.json"
    write_json(path, output)
    return {"saved": str(path), "scope": output["scope"], "annotation_status": output["annotation_status"],
            "variants": {k: v["summary"] for k, v in output["variants"].items()}}
