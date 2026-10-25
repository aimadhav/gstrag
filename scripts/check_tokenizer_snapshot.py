"""Check wrapper token IDs against the cached original Jina tokenizer backend.

No Hub downloads, embeddings, credentials, or Mistral-specific patching.
"""

import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download
from tokenizers import Tokenizer
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/chapter7_repaired"


def main():
    snapshot = Path(snapshot_download("jinaai/jina-embeddings-v3", local_files_only=True))
    backend = Tokenizer.from_file(str(snapshot / "tokenizer.json"))
    wrapped = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True, fix_mistral_regex=False)
    wrapped.model_max_length = 10**9
    samples = []
    for variant in ["fixed", "hierarchical", "hybrid"]:
        samples.extend(json.loads(line)["embedding_text"] for line in (DATA / f"chunks_{variant}.jsonl").read_text(encoding="utf-8").splitlines())
    for name in ["chapter7_questions.source_audited_v2.json", "chapter7_source_regressions.json"]:
        # Token-ID comparison is not retrieval scoring; original held-out text
        # was already visible to its label auditor. No query embeddings here.
        samples.extend(q["question"] for q in json.loads((ROOT / "data/benchmark" / name).read_text(encoding="utf-8"))["questions"])
    mismatches = [i for i, text in enumerate(samples) if backend.encode(text, add_special_tokens=False).ids != wrapped.encode(text, add_special_tokens=False)]
    config = json.loads((snapshot / "tokenizer_config.json").read_text(encoding="utf-8"))
    result = {"snapshot_commit": snapshot.name, "tokenizer_class_in_config": config["tokenizer_class"],
        "tokenizer_json_sha256": hashlib.sha256((snapshot / "tokenizer.json").read_bytes()).hexdigest(),
        "samples_checked": len(samples), "mismatch_count": len(mismatches), "mismatch_indices": mismatches,
        "mistral_patch_applied": False,
        "note": "Transformers' offline Mistral-warning heuristic is not evidence that this XLM-R tokenizer needs Mistral regex replacement. Wrapper IDs were compared directly with the cached original backend. This does not pin hosted Jina model internals."}
    (DATA / "tokenizer_verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
