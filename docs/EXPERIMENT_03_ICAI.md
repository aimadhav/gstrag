# Experiment 03 ICAI topic pipeline test

Historical baseline (`0.2.0`): the structural warnings described here were subsequently repaired in [Experiment 04: before and after](EXPERIMENT_04_STRUCTURE_REPAIR.md). This report and its saved benchmark scores describe the pre-repair run. Its chunk/retrieval commands refer to that historical implementation; use Experiment 04 for the current rebuild and verification commands.

Completed on 21 October 2026 after reading all ten selected pages as text and original-page renders, including footnotes, tables, and examples. The user explicitly confirmed permission for retrieval/RAG use, including sending text to Jina. This records the user's confirmation, not an independent verification of a permission document.

## Result

The pipeline successfully parsed, chunked, embedded, and retrieved the ICAI material on PDF pages 70-79. Hybrid child-only context contains every labeled evidence group for all 13 answerable development questions. All 24 unit tests pass, and the original firm-book frozen experiment remains unchanged.

**This is a pass with structural warnings, not a clean bill of health for the parser.** The existing heading logic does not generalize correctly to this ICAI layout. Some repeated page headers become parent titles, and single-integer headings are not recognized as numbered subsection boundaries. These defects remain unmodified so this run measures the existing chunker rather than a tuned repair.

This is a development smoke test on a small topic slice, not an independent held-out benchmark, legal validation, or chatbot answer-accuracy result. No Gemini answer generation or Pinecone indexing was performed.

## Source and complete page review

Source: [official ICAI chapter](https://resource.cdn.icai.org/87067bos-aps1530-p2b-m1-may2026-ch2.pdf), Chapter 2 Supply under GST, Intermediate Course Paper 3 Section B. The PDF contains 104 pages and states a law cutoff of 30 April 2025. Only PDF pages 70-79 were parsed in this experiment. Printed labels 2.70-2.79 were checked visually; this is not a general printed-page detection feature.

| PDF page | Content reviewed and test concern |
|---:|---|
| 70 | Section 8 table and introduction; contains a short carryover from the preceding topic. |
| 71 | Composite and principal-supply definitions; preserve conditions and ancillary relationship. |
| 72 | Natural-bundling indicators and supporting examples. |
| 73 | Indicators are not a universal test; conference package begins and continues on the next page. |
| 74 | Conference conclusion, goods/transport example, TV/travel examples, and assumed-rate illustration. |
| 75 | Printing examples with contrasting conditions; circular reference appears in a footnote. |
| 76 | Hospital-food distinctions, bus-body and retreading qualifications; cinema discussion begins. |
| 77 | Cinema discussion continues, independent and bundled cases differ, then mixed-supply definition. |
| 78 | Mixed-supply tests and separately priced/supplied exception. |
| 79 | Assumed-rate example, separately valued car servicing, and quiz. |

The examples' rates and the book's stated treatments are not presented as independently verified current law. Circulars mentioned within the book are not separately ingested notification documents.

## What changed in the code for this test

The parser previously always converted the full PDF. We added an optional page range to `parse_pdf()` in `src/gst_rag/ingestion.py` and a small runner, `scripts/parse_icai_topic.py`, which supplies `(70, 79)` to Docling.

The original PDF was not split, rewritten, or renumbered. The manifest records 104 source pages, 10 parsed pages, and the original converted page positions 70-79. This avoids a common citation bug: calling the first selected page "page 1" even though the reader must open page 70 of the original PDF.

The selected view has its own document ID, `icai_book-140dc5f4c5e8c8fe-p70-79`. It also records the full-PDF source identity. This prevents parse-relative source IDs from different page selections being mistaken for the same content or receiving the same chunk-configuration fingerprint. Cached parses must match the requested range.

Three new tests cover range validation, distinct selected-view identity, and rejection of a mismatched cached range. The existing 21 tests still pass. The frozen `chunking.py`, `benchmark.py`, `cli.py`, firm-book artifacts, and held-out results were not changed.

## Actual pipeline artifacts

Local directory: `data/processed/icai_composite_mixed_p70_79/`.

- Docling conversion: success, 82.074 seconds including initialization; OCR disabled, table structure enabled, four CPU threads.
- Canonical units: 77; distinct source references: 98; parents: 17.
- Chunks: 10 fixed, 77 hierarchical, 18 hybrid.
- All three variants cover every canonical reference and retain original PDF page provenance.
- All six circular-reference footnotes appear in the canonical source.
- Every fixed and hybrid chunk fits the 512-token cap including heading context; hierarchical's largest element is 237 tokens in this sample.
- Source metadata is `icai_book` with `plan_required=plus`, so it is eligible for both Plus and Pro.

Configuration ID: `a35ee776840a`; the chunker remains pipeline version `0.2.0`. The existing Jina-v3 tokenizer, hosted model ID, exact cosine ranking, top-ten retrieval, and 2,048-token context budget were used.

## Development questions and results

Fifteen questions were authored after reading the source and before retrieval scoring. Thirteen are answerable; the others describe missing evidence and an underspecified question. Evidence requirements cover definitions, cross-page context, contrasting conditions, examples, and exceptions. Each excerpt was bound to an actual Docling source item and original PDF page. The annotations are assistant-reviewed, not independently expert-labeled.

| Method | Mean evidence recall at 5 | Mean evidence recall at 10 | Complete evidence at 10 | Mean evidence recall in context | Questions with complete context |
|---|---:|---:|---:|---:|---:|
| Fixed windows | 88.46% | 100% | 13/13 | 80.77% | 10/13 |
| Hierarchical | 91.28% | 97.44% | 12/13 | 97.44% | 12/13 |
| Hybrid | 100% | 100% | 13/13 | 100% | 13/13 |

Fixed windows have only ten indexed chunks, so top-ten retrieval visits the entire index. Its perfect recall at ten is consequently a weak comparison; the top-five and budgeted-context results are more informative here. No score is reported for correct refusal or clarification behavior: the two no-evidence questions are excluded from recall means, and no answer policy was executed.

### Concrete failures

Fixed windows retrieve the full evidence at ten but lose the composite and principal definitions in the final context for ic01 and ic02. They also lose half of ic11's mixed-supply evidence. This is a context-selection failure, not proof that the text was absent from the PDF parse.

Hierarchical retrieval misses the individual-examination qualification for ic03 within ten results. It finds the two requested indicators but not the qualification that stops them being treated as a universal formula.

### Hybrid context expansion

| Mode | Mean context evidence recall | Complete-context questions | Mean context tokens |
|---|---:|---:|---:|
| Child only | 100% | 13/13 | 2,048 |
| Parent expansion with child fallback | 100% | 13/13 | 2,048 |
| Neighbor insertion | 94.87% | 12/13 | 2,048 |

Neighbor insertion leaves only one of the three required groups for ic03 in the assembled context. Parent expansion does not improve measured evidence coverage over child-only. These results do not validate the correctness of parent boundaries; that is checked separately below.

## Layout warnings explained simply

Imagine putting study notes into folders named after section titles. The current code knows the firm book's numbering format, such as `7.2.10.`, but ICAI uses headings such as `4.` and `1.`. Those are not recognized by the same numbered-outline helper.

Docling also labels several repeated running headers as ordinary section headings. The words `SUPPLY UNDER GST` then become folder names, even though they are page furniture rather than actual topic boundaries. Four parents have that repeated heading as their top title. For example, one such parent spans pages 73-75 rather than representing a trustworthy numbered subsection.

The evidence can still be found, which explains why hybrid's score is good. But the organization is not reliable enough to claim that the parent-child structure works generically across books. Passing question checks cannot substitute for inspecting heading ownership.

No header-removal heuristic or integer-heading interpretation was implemented during this test. The next repair should distinguish running furniture using layout/repetition evidence and reconstruct the ICAI outline without confusing local numbered examples with main section numbers. Preserve this run as the pre-repair baseline and use a new artifact/configuration version for that work.

## Source access tests

On the ICAI-only corpus, the Plus and Pro hybrid runs produce identical ranked hits and context, as expected: the source is permitted to both plans.

An additional mixed-corpus lexical smoke test combines the 18 ICAI hybrid chunks with the 130 firm-book hybrid chunks. It asks about a firm-book opinion and uses the actual source filter before ranking and context assembly.

- Plus has 18 eligible chunks, all ICAI. Its hits and assembled context contain no firm-book records.
- Pro has 148 eligible chunks across both sources. Its context includes the relevant firm-book opinion.

This confirms the local source-policy behavior on actual records. It is not a combined dense-retrieval quality benchmark, JWT authentication test, proof of semantic noninterference, or an implemented user/admin application.

## Verification and usage

`scripts/check_icai_pipeline.py` reports `passed_with_structure_warnings`. It checks the original checksum, selected page positions, all source alternatives, all six footnotes, variant coverage/token caps, source policy labels, Plus/Pro agreement, hybrid evidence completeness, the mixed access smoke, and preservation of the old frozen experiment.

Incremental Jina usage: 15,249 provider-reported tokens across eight requests, with 13.002 seconds of aggregate API request time. The Pro, parent, and neighbor reruns reused vectors with zero additional embedding requests. Parsing and local ranking are separate from these API timings; no monetary cost estimate or end-to-end answer latency is claimed.

The same generic offline Transformers Mistral-related warning appeared for the existing XLM-R tokenizer. No Mistral regex patch was applied and no tokenizer setting was changed for this comparison; the earlier tokenizer-snapshot diagnostic is documented in Experiment 02.

## Reproduce and inspect

```powershell
uv run python scripts/parse_icai_topic.py
uv run gst-rag chunk data/processed/icai_composite_mixed_p70_79
uv run python scripts/build_icai_labels.py
uv run gst-rag benchmark data/processed/icai_composite_mixed_p70_79 data/benchmark/icai_topic_questions.json --retriever jina --plan plus --output-tag icai_v02
uv run gst-rag benchmark data/processed/icai_composite_mixed_p70_79 data/benchmark/icai_topic_questions.json --retriever jina --plan pro --variant hybrid --output-tag icai_v02
uv run gst-rag benchmark data/processed/icai_composite_mixed_p70_79 data/benchmark/icai_topic_questions.json --retriever jina --plan plus --variant hybrid --context-mode parent --output-tag icai_v02
uv run gst-rag benchmark data/processed/icai_composite_mixed_p70_79 data/benchmark/icai_topic_questions.json --retriever jina --plan plus --variant hybrid --context-mode neighbors --output-tag icai_v02
uv run python scripts/validate_experiment.py --directory data/processed/icai_composite_mixed_p70_79 --questions data/benchmark/icai_topic_questions.json
uv run python scripts/check_icai_access.py
uv run python scripts/check_icai_pipeline.py
uv run python -m unittest discover -s tests -v
```

The final verification script also expects the saved Pro hybrid run. Keep the existing baseline when experimenting with repairs. Raw book text, labels, cached vectors, renders, and complete outputs remain in ignored local paths. No new held-out set was created or scored for ICAI, and the earlier firm-book held-out set was not rerun.

## Interview explanation

"I tested the same chunker on a second publisher's layout, using the same topic. I preserved original page numbers, checked source conditions and exceptions, and compared retrieval under the same context budget. Hybrid covered all labeled evidence on the 13 answerable development questions, but the source audit still found bad parent headings. I reported that as a layout limitation rather than claiming the good score meant the parser was fully correct."
