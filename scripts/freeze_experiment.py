"""Freeze a checked local experiment before a single held-out retrieval run."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/chapter7_repaired"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = DATA / "experiment_freeze.json"
    if target.exists() or list(DATA.glob("benchmark_*_heldout_*.json")):
        raise ValueError("A freeze/results already exist. Do not overwrite or retune this held-out experiment.")
    checks = load(DATA / "source_audit_verification.json")
    assert all(c["passed"] for c in checks["checks"])
    assert any(c["name"] == "dense_targeted_development_regressions" for c in checks["checks"])
    tokenizer = load(DATA / "tokenizer_verification.json")
    assert tokenizer["mismatch_count"] == 0
    labels = ROOT / "data/benchmark/chapter7_questions.source_audited_v2.json"
    artifacts = ["manifest.json", "docling.json", "chunk_report.json", "units.json", "parents.json",
        "chunks_fixed.jsonl", "chunks_hierarchical.jsonl", "chunks_hybrid.jsonl", "picture_transcription_audit.json", "tokenizer_verification.json"]
    result = {"freeze_date": "2026-10-21", "config_id": load(DATA / "chunk_report.json")["config_id"],
        "question_set_sha256": checksum(labels),
        "artifact_sha256": {name: checksum(DATA / name) for name in artifacts},
        "code_sha256": {name: checksum(ROOT / "src/gst_rag" / name) for name in ["chunking.py", "benchmark.py", "cli.py"]},
        "heldout_settings": {"retriever": "jina", "context_mode": "child", "context_budget": 2048, "top_k": 10, "plan": "pro", "variant": "all"},
        "selected_candidate_before_heldout": "hybrid child-only; all three methods retained for the frozen comparison",
        "development_gate": "hybrid covers all required groups in retrieved top ten and assembled context on the six source regressions",
        "annotation_review": "assistant source audit, not independent legal/expert validation",
        "tokenizer": tokenizer,
        "notes": ["Original question-set source_audit.freeze_ready=false describes the old pre-repair pipeline; this freeze records the repaired configuration after its checks passed.",
            "No source, label, or retrieval tuning after viewing held-out scores. Any future experiment needs a new evaluation set.",
            "Hosted Jina model internals are not pinned. Existing passage vectors are reused from cache; held-out query vectors are new.",
            "No answer generation, abstention behavior, or current-law correctness is evaluated."]}
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"saved": str(target), "config_id": result["config_id"], "heldout_settings": result["heldout_settings"]}, indent=2))


if __name__ == "__main__":
    main()
