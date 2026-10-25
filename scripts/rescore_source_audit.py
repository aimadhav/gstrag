"""Re-evaluate saved DEV hits and contexts against audited labels, offline.

Never embeds, changes chunks, scores held-out retrieval, or overwrites old runs.
"""

import copy
import hashlib
import json
from pathlib import Path

from gst_rag.benchmark import evidence_recall, group_covered

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed/chapter7"
LABELS = ROOT / "data/benchmark/chapter7_questions.source_audited_v2.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    labels = load(LABELS)
    questions = {q["id"]: q for q in labels["questions"] if q["split"] == "dev"}
    fields = ["evidence_recall_at_5", "evidence_recall_at_10", "complete_at_10",
              "reciprocal_rank_at_10", "context_evidence_recall", "context_tokens", "search_ms"]
    runs = ["benchmark_jina_dev_child_pro_all.json", "benchmark_jina_dev_neighbors_pro_hybrid.json",
            "benchmark_jina_dev_parent_pro_hybrid.json"]
    summaries = {}
    for name in runs:
        source = DATA / name
        old = load(source)
        assert old["split"] == "dev"
        result = copy.deepcopy(old)
        result["original_question_set_sha256"] = old["question_set_sha256"]
        result["question_set_sha256"] = hashlib.sha256(LABELS.read_bytes()).hexdigest()
        result["annotation_status"] = labels["annotation_status"]
        result["annotation_version"] = labels["annotation_version"]
        result["offline_rescore_of"] = name
        result["api_usage_this_run"] = {"tokens": 0, "requests": 0, "seconds": 0}
        result["notes"].append("Offline development-only label rescore: identical saved hits/context and pipeline configuration; no new retrieval, model calls, or held-out scores. Search timing is inherited from the original run.")
        for variant, stats in result["variants"].items():
            records = {r["chunk_id"]: r for r in (json.loads(line) for line in (DATA / f"chunks_{variant}.jsonl").read_text(encoding="utf-8").splitlines())}
            for row in stats["rows"]:
                q = questions[row["question_id"]]
                assert row["question"] == q["question"]
                groups = q["evidence_groups"]
                hits = [records[h["chunk_id"]] for h in row["hits"]]
                first = next((i + 1 for i, h in enumerate(hits) if any(group_covered(g, [h]) for g in groups)), None)
                row.update(evidence_recall_at_5=evidence_recall(groups, hits[:5]),
                    evidence_recall_at_10=evidence_recall(groups, hits[:10]),
                    complete_at_10=evidence_recall(groups, hits[:10]) == 1 if groups else None,
                    reciprocal_rank_at_10=1 / first if first else 0 if groups else None,
                    context_evidence_recall=evidence_recall(groups, row["context"]))
            for field in fields:
                values = [r[field] for r in stats["rows"] if r[field] is not None]
                stats["summary"][field] = round(sum(values) / len(values), 4) if values else None
        target = source.with_name(source.stem + "_source_audited_v2.json")
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summaries[name] = {v: {**s["summary"], "incomplete_at_10_ids": [r["question_id"] for r in s["rows"] if r["complete_at_10"] is False],
            "incomplete_context_ids": [r["question_id"] for r in s["rows"] if r["context_evidence_recall"] is not None and r["context_evidence_recall"] < 1]} for v, s in result["variants"].items()}
    (ROOT / "data/audit/development_rescore_summary.json").write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
