"""Actual mixed-corpus lexical access smoke, not dense retrieval-quality scoring."""

import json
import argparse
from pathlib import Path

from transformers import AutoTokenizer

from gst_rag.benchmark import BM25, allowed, assemble_context
from gst_rag.ingestion import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
ICAI = ROOT / "data/processed/icai_composite_mixed_p70_79"
FIRM = ROOT / "data/processed/chapter7_repaired"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--icai-directory", type=Path, default=ICAI)
    parser.add_argument("--firm-directory", type=Path, default=FIRM)
    args = parser.parse_args()
    records, units, parents = [], [], []
    for directory in [args.icai_directory, args.firm_directory]:
        records += [json.loads(line) for line in (directory / "chunks_hybrid.jsonl").read_text(encoding="utf-8").splitlines()]
        units += read_json(directory / "units.json")
        parents += read_json(directory / "parents.json")
    tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3", local_files_only=True, fix_mistral_regex=False)
    tokenizer.model_max_length = 10**9
    query = "Magnam Netlink dairy plant In our view the AAR had erred concessional works contract"
    results = {}
    for plan in ["plus", "pro"]:
        candidates = [r for r in records if allowed(r, plan)]
        scores = BM25(candidates).scores(query)
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:10]
        hits = [candidates[i] for i in order]
        context, used, _ = assemble_context(hits, units, parents, tokenizer, 2048, "child", plan)
        assert all(allowed(r, plan) for r in hits + context)
        if plan == "plus":
            assert all(r["source_type"] == "icai_book" for r in candidates + hits + context)
        else:
            assert any(r["source_type"] == "firm_book" and "Magnam" in r["embedding_text"] and "In our view" in r["embedding_text"] for r in context)
        results[plan] = {"eligible_chunks": len(candidates), "eligible_source_types": sorted({r["source_type"] for r in candidates}),
            "hit_source_types": sorted({r["source_type"] for r in hits}), "context_source_types": sorted({r["source_type"] for r in context}),
            "context_tokens": used, "hit_document_ids": sorted({r["document_id"] for r in hits})}
    report = {"status": "passed", "scope": "Mixed ICAI/firm lexical access smoke; no query embeddings or answer generation. Not JWT authentication or semantic correctness.", "plans": results}
    write_json(args.icai_directory / "mixed_access_smoke.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
