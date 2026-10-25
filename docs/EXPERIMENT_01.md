# Experiment 01: chunking and context expansion

Run on 19 October 2026. **Historical draft-label results:** the tables below preserve the initial experiment. A subsequent complete PDF audit corrected 17 question labels and rescored identical saved development hits. The identified defects were repaired on 21 October; see [Experiment 02](EXPERIMENT_02_REPAIRS.md) for the frozen results and current status. Neither experiment establishes chatbot accuracy or current legal correctness.

## Implementation and inputs

Docling conversion completed with success status, OCR disabled, table structure enabled, and four CPU threads. Conversion took 157.402 seconds in this environment; this includes cold initialization and model setup inside conversion and is not a steady-state parsing benchmark.

Versions: Python 3.12.14, Docling 2.140.0, docling-core 2.102.0, torch 2.14.1+cpu, transformers 5.20.1. Exact resolved dependencies are in uv.lock.

The tokenizer repository name and hosted embedding model ID are recorded, but the hosted provider's model internals are not pinned. Cached vectors preserve this run's actual embeddings; future uncached API runs are not guaranteed to be bit-for-bit identical.

Document fingerprint: `bddb8207104b9d462a85ecfab3e28ef0afbaa35f2b75add508131b3ca155ce96`.

The conversion preserves raw JSON and Markdown. In a separate copy used by every chunker, the pipeline excludes recognized document indexes, synopsis headings, obvious dotted-leader candidates, and chapter decorations. It retains source JSON pointers when excluding elements. Furniture is kept out of body retrieval.

The PDF's headings were detected with uniform depth. A deterministic correction uses explicit section numbering to infer levels; unnumbered headings are placed below the current numbered heading. The changes are saved for inspection. This is a heuristic, not a claim that every PDF outline can be reconstructed correctly.

Representative rendered pages 2, 3, 23, 39, 40, and 42 were inspected for TOC continuation, definitions, bordered notes, data tables, and a table continued across pages. Table continuation remains separate page-level elements; it is not automatically merged into one semantic table.

## Chunking configurations

All variants use the `jinaai/jina-embeddings-v3` tokenizer, Markdown table serialization, and the same newline heading-prefix formatter. Counts include that heading prefix but exclude model special tokens.

| Variant | Configuration | Chunks | Median tokens | Maximum tokens |
|---|---|---:|---:|---:|
| Fixed | 512-token maximum, 64-token overlap | 80 | 512 | 512 |
| Hierarchical | Docling elements; list items not merged | 244 | 159 | 590 |
| Hybrid | Docling token-aware splitting, peer merging, 512-token maximum | 129 | 252 | 512 |

Fixed windows reserve space for heading context, so body-only window lengths can vary. Hierarchical chunks deliberately have no 512-token cap: two elements exceed that threshold. Do not describe this as three identical-size chunkers.

There are 25 parent records, defined by the nearest explicitly numbered subsection. A fixed window can span multiple parents and therefore carries multiple parent IDs. Parents preserve their subordinate heading text and source references.

Every variant covers all 285 canonical source item references. No chunk is missing PDF page provenance. This verifies representation coverage at item level; it does not prove that extraction matches every word or that all item labels are correct. Split excerpts from a multi-page item inherit its broader page span. Printed-page labels have not been extracted.

Configuration ID: `749f74486094`.

## Question set and evidence labels

There are 30 draft questions: 20 development and 10 held out. Development includes 18 answerable questions, one out-of-scope question, and one ambiguous question. The latter two are recorded but excluded from evidence-recall means. No abstention or clarification policy has been evaluated.

Questions cover definitions, rules, illustrations, qualifications, author interpretation, table-plus-text evidence, and historical dates within the book. Every evidence excerpt was checked for existence in the parsed canonical source. This is not an independent expert assessment of completeness or current GST law. Some questions closely resemble source phrasing, so their difficulty is limited.

Each required evidence group has one or more acceptable alternatives. A match requires both an original source item ID and an exact excerpt after whitespace/quote normalization. Merely retrieving another part of the same source item does not count.

Local JSON format:

```json
{
  "document_id": "fingerprint-based-document-id",
  "annotation_status": "draft",
  "questions": [{
    "id": "q01",
    "split": "dev",
    "category": "definition",
    "expected": "answer",
    "question": "A question grounded in the supplied document",
    "evidence_groups": [[{
      "source_refs": ["#/texts/13"],
      "quote": "An actual short excerpt from that source item"
    }]]
  }]
}
```

Multiple groups mean independently required evidence; alternatives within one group mean any one is acceptable. Empty groups are used for questions expected to need clarification or insufficient-evidence handling. Source IDs belong to this particular parse. Held-out questions were authored but have not been scored or used to select parameters.

## Retrieval experiment

Jina API model: `jina-embeddings-v3`. Passage task: `retrieval.passage`. Query task: `retrieval.query`. Vectors are normalized and ranked locally by cosine similarity. All candidates are searched exactly; no approximate-index parameters or reranker confound the comparison. Pinecone is deferred until the retrieval choice is clearer.

The initial embedding run recorded 109,044 provider-reported tokens across 28 requests and 40.291 seconds of aggregate API request time. Cached reruns make no additional embedding calls for unchanged model/task/text combinations. These are token-usage figures, not a quoted monetary price or end-to-end answer latency.

| Variant | Mean evidence recall at 5 | Mean evidence recall at 10 | Complete evidence at 10 | Mean reciprocal rank at 10 |
|---|---:|---:|---:|---:|
| Fixed | 86.11% | 100% | 18/18 | 0.7778 |
| Hierarchical | 83.33% | 94.44% | 17/18 | 0.6947 |
| Hybrid | 100% | 100% | 18/18 | 0.7917 |

Evidence recall is computed per question and then averaged. Complete evidence requires every labeled group. MRR uses the first hit covering any required group; it does not measure full-answer completeness.

Hybrid is the provisional development candidate. The table does not establish a general winner. No answer model, citation entailment judge, or expert legal answer scoring was used.

## Parent-child experiment

Hybrid was selected for the follow-up development experiment based on its evidence coverage in the first run. Its ranked child results remain identical in all three modes. Each mode uses at most 2,048 context tokens and starts from the same top ten hits.

- Child: add ranked child passages until the budget is used.
- Neighbors: add a hit and adjacent canonical source elements within the same subsection, subject to the same budget.
- Parent: replace a matching child with its containing subsection when that subsection fits the remaining budget. Deduplicate parents. If a parent is too large, preserve the matching child as a fallback.

| Hybrid context mode | Mean evidence recall in assembled context | Mean context tokens |
|---|---:|---:|
| Child only | 100% | 2,024.25 |
| With neighboring elements | 94.44% | 2,048 |
| Parent expansion with child fallback | 100% | 2,048 |

Naive neighbor insertion crowded out required evidence for development question q05. Parent expansion did not improve coverage because child-only retrieval already covered all labeled evidence. This is a reason to retain parent relationships while keeping child-only context as the current simple candidate, pending human label review and held-out testing.

This experiment demonstrates the budget tradeoff. It does not prove that parent context never helps; the next independent evaluation needs harder questions with evidence separated across a section.

## Artifacts and verification

Local artifacts under `data/processed/chapter7/`:

- `docling.json`, `document.md`, `manifest.json`: original parse and settings.
- `exclusions.json`, `heading_adjustments.json`: auditable structural normalization.
- `units.json`, `parents.json`: canonical source units and parent relationships.
- `chunks_fixed.jsonl`, `chunks_hierarchical.jsonl`, `chunks_hybrid.jsonl`.
- `chunk_report.json`: configuration, counts, token limits, and reference coverage.
- `jina_cache.json`: cached vectors, excluded from Git along with source text.
- `benchmark_jina_dev_child_pro_all.json`: main comparison and per-question contexts.
- `benchmark_jina_dev_neighbors_pro_hybrid.json` and `benchmark_jina_dev_parent_pro_hybrid.json`: expansion results.

Ten synthetic contract tests cover source-plus-excerpt matching, independent evidence groups, excluded no-evidence cases, source permissions, parent deduplication, oversized-parent fallback, neighbor boundaries, and fixed-window provenance. Actual artifact checks also confirmed all canonical references are covered and the assembled contexts stay within the configured token budget.

An actual Plus-policy keyword-search smoke run returned zero hits and zero context tokens for every variant of this firm-book-only corpus. This is the expected access outcome, not a retrieval-quality result. A local readable evidence-review sheet is at `data/benchmark/question_review.md`, generated by `scripts/validate_experiment.py`.

Access filtering in this experiment is a local source policy, not authenticated application access control. No frontend, JWT system, citation links, answer generator, or review app exists yet.

## Next step

The assistant has now audited the complete PDF and all 30 labels; user annotation work is not required. Fix the trailing-dot subsection grouping and the omitted page-21 diagram, add targeted later-qualification development tests, then freeze the dataset and configuration before scoring the held-out subset. Add an ICAI sample and a notification before making claims about multi-source retrieval or temporal updates. Preserve development results separately from the eventual held-out report.
