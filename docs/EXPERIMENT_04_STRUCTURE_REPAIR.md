# ICAI parent structure: fix, before/after, and interview explanation

Completed: 21 October 2026. Pipeline version: `0.3.0`.

## Outcome

The known parent-grouping defects are fixed for the audited ICAI pages 70-79. Running headers no longer become section titles, local integer headings remain inside the main section, the cinema discussion stays together across pages, and its following mixed-supply definition has the correct owner. Circular-reference footnotes are attached to their source-checked topics.

All 98 ICAI canonical source references have the expected parent in the verification check. The 45-page firm-book sample retains the same chunk text and parent ownership. **47 unit tests pass.**

This is a repair for two known document layouts, not proof that arbitrary PDFs are ingested correctly. Part of the ICAI repair is an explicit, assistant-reviewed outline supplement; it is not fully automatic heading understanding. There is still no case-title/facts/issue/ruling schema.

## Explain it to a beginner

Think of a parent as a folder and a child chunk as a small note inside that folder. We search the notes, and can optionally load their folder for more context.

The old program sometimes used the words printed at the top of every page as a folder name. That is like filing a hospital-food explanation under "Page header" instead of its actual topic. It also understood numbering such as `7.2.10.` but not ICAI's `4.` and local `1.` to `5.` headings.

Simply allowing `4.` in a regex is not enough. Section 4 contains a smaller numbered list starting at 1. Calling both level-one headings would still create the wrong folder structure.

There was another issue on page 77: the parsed order placed the mixed-supply definition before the cinema discussion that appears above it on the actual page. A correct heading name cannot fix a paragraph that arrived in the wrong order. We checked the page image and corrected that ordering in the working copy used for chunking.

We did not rewrite the PDF, rewrite the raw Docling JSON, or alter the legal text. We corrected the folder labels, nesting, and a few source-checked placements.

## Why the old code did this

1. `filter_document()` trusted Docling's `page_header`/`page_footer` labels. Five running headers were instead labeled `section_header`, so they survived.
2. The old heading-number regex required at least two number components. It recognized `7.2`, but not `4.`.
3. The default parent helper chose the nearest recognized numbered heading, or the first heading when none matched. ICAI's real unnumbered topic panels consequently did not have reliable ownership.
4. The old code trusted Docling's reading order. On page 77 it was not the same as the visual reading order.
5. Footnotes appear at the bottom of the page, but their markers refer to earlier topics. Page position alone does not establish which parent owns a footnote.

Retrieval could still find the words, explaining the good earlier hybrid score. A good score did not establish correct structure.

## The repair, technically

### 1. Detect repeated top-margin headings

`src/gst_rag/structure.py::repeated_edge_headers()` requires all of these signals:

- The item is currently labeled a section heading.
- Its normalized text repeats on at least three distinct pages.
- Its entire bounding box lies in the top 12% of the page.
- Its vertical position varies by at most 2% of page height, and its left position by at most 3% of page width.
- It is not a numbered heading.

Both top-left and bottom-left coordinate origins are supported. The check removes five mislabeled headers in this sample. It does not delete every occurrence of a phrase from body text, and it leaves unique and repeated mid-page headings alone.

The exclusion audit records each removed reference, page, reason, and preview. This is a conservative heuristic, not an infallible furniture detector: a genuine unnumbered section repeated at the same top margin could still need review, and a header seen on only two pages is deliberately left alone.

### 2. Recognize integer numbers without guessing their depth

In `src/gst_rag/chunking.py::heading_number()`:

```python
# Before: requires at least one dot between numeric components
r"^(\d+(?:\.\d+)+)\.?(?:\s+|$)"

# After: supports a single integer too
r"^(\d+(?:\.\d+)*)\.?(?:\s+|$)"
```

Only already-identified heading strings go through this helper. It does not promote ordinary numbered prose into headings. Multipart numbering, including the earlier firm-book trailing-dot repair, still works.

The default depth restorer now stops with a clear `--outline-review` error when integer numbering repeats or restarts. For example, `4., 1., 2., 3., 4., 5.` is ambiguous. It must not silently interpret the smaller list as new main sections. Simple monotonic integer outlines can still use the default path.

### 3. Apply a reviewed outline for the ambiguous ICAI layout

`apply_outline_review()` loads a small JSON supplement containing the 12 retained heading anchors, their levels, and whether they start a parent. For this slice:

- Main section: level 1.
- Analysis and major topic panels: level 2.
- Local clarification headings: level 3.
- The question-style bundling heading and mixed-definition subheading remain within their reviewed parents.

The review must match the original PDF checksum, the document-view ID, **and the exact raw Docling JSON checksum**. It checks the exact heading text, original PDF pages, levels, uniqueness, and coverage of every retained heading. A replaced PDF or new parse needs a fresh review; old source indices cannot be reused silently.

`parent_headings_for()` uses the nearest reviewed parent boundary when a supplement is supplied. Otherwise it retains the numbered-subsection policy used by the firm book.

This explicit correction is a deliberately small solution for the resume project's known sources. Building a generic typography/reading-order model would be a separate project. The review is source-checked by the assistant, not independently expert-validated.

### 4. Correct five reviewed placements without changing text

The supplement records five same-page body-order operations:

1. Move the mixed-definition heading, its intact list group, and its closing paragraph below the mixed-supplies title on page 77.
2. Place cinema footnote 38 with its cinema discussion, before the mixed topic begins.
3. Place footnote 35 with the hospital-food topic on page 76.
4. Place footnote 36 with the bus-body topic.
5. Place footnote 37 with the retreading topic.

All move anchors are validated before applying changes. Moves cannot cross a PDF page; list groups remain intact. These are reviewed corrections, not a global top-to-bottom sort of every PDF element. Blind sorting could damage multi-column pages or detach footnotes again.

## Before and after: actual ownership

Labels below abbreviate the full source headings for readability. Source references are the original Docling references, unchanged by the repair.

| Source item | Before | After |
|---|---|---|
| CBIC introduction, `#/texts/68` | Running page header | Section 4 > Composite supplies |
| Printing paragraph, `#/texts/70` | Standalone local topic | Section 4 > Composite supplies > Printing |
| Food circular footnote, `#/texts/92` | Cinema topic | Section 4 > Composite supplies > Hospital food |
| Cinema continuation, `#/texts/104` | Running page header | Section 4 > Composite supplies > Cinema |
| Cinema circular footnote, `#/texts/101` | Mixed-definition topic | Section 4 > Composite supplies > Cinema |
| Mixed-definition condition, `#/texts/98` | Standalone definition heading | Section 4 > Mixed supplies |

The corrected outline is:

```text
Carryover from preceding topic (kept separate; page 70)
Section 4
  Section table
  Analysis
  Composite supplies
    Bundling guidance and examples
    1. Printing
    2. Hospital food
    3. Bus-body building
    4. Retreading
    5. Cinema (continues from page 76 to 77)
  Mixed supplies (definition and examples)
  Separately taxed supplies
```

The bundling subheading does not create an additional parent. There are 11 actual parents, including the carryover parent and section-table parent.

## Structural measurements

| Check | ICAI before | ICAI after |
|---|---:|---:|
| Parents | 17 | 11 |
| Parents whose top title is the running header | 4 | 0 |
| Canonical units | 77 | 77 |
| Distinct canonical source references | 98 | 98 |
| Circular-reference footnotes retained | 6 | 6 |
| Fixed / hierarchical / hybrid chunks | 10 / 77 / 18 | 11 / 77 / 15 |

The verification compares the expected owner for **every** canonical reference, not just whether a few correctly named parents exist. It also checks that each unit's text, source references, and page list are unchanged as a multiset. The number of parents alone is not a quality metric.

For the firm book, the new build has the same 27 parents, 286 references, 244 units, and 81 / 244 / 130 chunks. Chunk text, embedding text, heading paths, parent ownership, and page provenance match its previous repaired build. Access labels remain Pro-only.

## Retrieval before and after

Same 15 ICAI development questions, of which 13 are answerable; unchanged source-quote labels. Same Jina model ID, tokenizer, top ten, and 2,048-token context budget. These questions were already used for development, so the comparison is **not held-out evidence**.

| Method | Complete context before | Complete context after | Mean context evidence recall before | After |
|---|---:|---:|---:|---:|
| Fixed windows | 10/13 | 9/13 | 80.77% | 75.90% |
| Hierarchical | 12/13 | 13/13 | 97.44% | 100% |
| Hybrid | 13/13 | 13/13 | 100% | 100% |

Hierarchical now finds the previously missed qualification for the bundling-indicators question. Hybrid retains complete evidence, with fewer chunks and cleaner headings. Fixed windows get worse: the new boundaries and heading prefixes change their ranking/context packing, and ic01, ic02, ic03, and ic11 have incomplete final context. That decline is reported, not tuned away.

All three methods now retrieve complete required evidence in their top ten. Fixed still loses evidence when packing that retrieval into a bounded context. Recall at five changes from 88.46% to 86.15% for fixed, remains 91.28% for hierarchical, and remains 100% for hybrid. The earlier fixed top-ten result searched its entire ten-chunk index; the repaired index contains eleven fixed chunks, so the index sizes are not identical.

Hybrid context-policy comparison:

| Mode | Complete context before | After |
|---|---:|---:|
| Child only | 13/13 | 13/13 |
| Parent expansion with matching-child fallback | 13/13 | 13/13 |
| Neighbor insertion | 12/13 | 11/13 |

Neighbor insertion now loses required evidence for ic02 and ic05. Larger or differently bounded parents can consume budget before another required passage is included. The implementation remains unchanged: load a complete parent only if it fits; otherwise retain the matching child. We keep **hybrid child-only as the simple default**, with parent expansion optional. Correcting structure does not prove parent expansion improves retrieval.

The six firm-book targeted development questions were also rerun: fixed remains 5/6 complete, hierarchical 6/6, hybrid 6/6. No earlier held-out question was scored again.

## Integrity, access, and cost checks

- Original PDF and raw parse files remain unchanged; ICAI page positions are still 70-79, not 1-10.
- All variants preserve canonical references and original pages; fixed and hybrid remain within 512 tokens including heading context.
- Plus and Pro return identical hybrid hits/context on the ICAI-only sample.
- The actual mixed-source lexical smoke test passes: Plus has 15 eligible ICAI chunks and no firm context; Pro has 145 eligible chunks across both sources and can retrieve the firm opinion. This is not yet JWT authentication.
- Incremental Jina usage: **16,917 provider-reported tokens, seven requests**, 10.343 seconds of aggregate embedding API time. Query vectors and unchanged passage vectors were reused. Pro, parent, neighbor, and firm-regression reruns made zero new embedding requests.
- No monetary estimate, end-to-end answer latency, generated-answer accuracy, or correct-refusal score is claimed.

The existing tokenizer diagnostic is unchanged; no Mistral regex patch was applied to this XLM-R tokenizer. See Experiment 02 for the cached-backend comparison.

## Files changed and experiment history

- `src/gst_rag/structure.py`: repeated-header detector and source-bound outline review validation/application.
- `src/gst_rag/chunking.py`: integer recognition, ambiguity guard, reviewed parent boundaries, structure audit, pipeline `0.3.0`, and a frozen-directory rebuild guard.
- `src/gst_rag/cli.py`: optional `--outline-review` argument.
- `scripts/repair_icai_structure.py`: constructs the reviewed supplement for the exact audited parse and rebuilds both sources into new folders.
- `scripts/verify_structure_repair.py`: checks every ICAI owner's source reference, preservation across both books, and optional saved retrieval/access checks.
- `scripts/check_icai_access.py`: accepts the selected artifact directories.
- `src/gst_rag/experiment_history.py` and the historical verification scripts: verify archived source against the original freeze hashes.
- `tests/test_structure_repairs.py`: 23 additional tests; total suite 47.

The current implementation has changed. Before editing it, byte-identical copies of the old frozen `chunking.py`, `benchmark.py`, and `cli.py` were saved under `chapter7_repaired/frozen_code/` and verified against the original freeze. Neither the freeze nor old benchmark scores were rewritten. Historical verification can inspect that archived code; the held-out **execution** guard still requires the actual executing code to match. An archived snapshot does not authorize scoring with changed code.

New local artifact directories and configuration IDs:

```text
ICAI baseline: data/processed/icai_composite_mixed_p70_79/
  a35ee776840a
ICAI repaired: data/processed/icai_composite_mixed_p70_79_v03/
  6a35c4e2772f
Firm frozen:   data/processed/chapter7_repaired/
  cd6743ef7d8e
Firm v0.3:     data/processed/chapter7_structure_v03/
  afd817c8ed80
```

The reviewed outline is saved locally at `data/audit/icai_composite_mixed_outline_review.json`. It is deliberately bound to this PDF/parse, not silently reused for other books. Private content and generated source artifacts remain ignored by Git.

## Reproduce

Run from the repository root. The repair runner uses existing cached Docling conversions and preserves historical directories. Rebuilding is not necessary just to inspect the saved result.

```powershell
uv run python scripts/repair_icai_structure.py
uv run gst-rag benchmark data/processed/icai_composite_mixed_p70_79_v03 data/benchmark/icai_topic_questions.json --retriever jina --plan plus --output-tag icai_v03
uv run gst-rag benchmark data/processed/icai_composite_mixed_p70_79_v03 data/benchmark/icai_topic_questions.json --retriever jina --plan pro --variant hybrid --output-tag icai_v03
uv run gst-rag benchmark data/processed/icai_composite_mixed_p70_79_v03 data/benchmark/icai_topic_questions.json --retriever jina --plan plus --variant hybrid --context-mode parent --output-tag icai_v03
uv run gst-rag benchmark data/processed/icai_composite_mixed_p70_79_v03 data/benchmark/icai_topic_questions.json --retriever jina --plan plus --variant hybrid --context-mode neighbors --output-tag icai_v03
uv run gst-rag benchmark data/processed/chapter7_structure_v03 data/benchmark/chapter7_source_regressions.json --retriever jina --plan pro --output-tag source_regressions
uv run python scripts/check_icai_access.py --icai-directory data/processed/icai_composite_mixed_p70_79_v03 --firm-directory data/processed/chapter7_structure_v03
uv run python scripts/verify_structure_repair.py --require-retrieval
uv run python -m unittest discover -s tests -v
```

The final two commands are local checks and do not call Jina. Re-running an existing development benchmark can replace that development result file and report zero incremental API usage because of caching; keep the saved original run when comparing cost. Do not rebuild into the baseline or frozen folders.

## Interview answer

"I found that accurate-looking retrieval could hide bad document structure. A publisher's running headers were labeled as section headings, and its local integer numbering didn't match the first book's outline. I added a position-and-repetition header check and a checksum-bound reviewed outline for the ambiguous layout. I also repaired a source-checked reading-order error and footnote ownership. Then I checked all source-reference owners, preserved page provenance, and reran the same development retrieval tests. Hybrid stayed complete on 13/13 answerable questions, hierarchical improved, and fixed-window context got worse. I reported those differences instead of claiming the structural repair improved everything."

If asked "Is it fully automatic?", answer **no**: cleanup is partly automatic, but ambiguous ICAI outline/order corrections use an explicit reviewed supplement. Replacing the PDF invalidates it. If asked "Does this prove the chatbot is accurate?", also answer **no**: no answer model or legal validation was evaluated.

## What next

Keep this repaired configuration as the ingestion candidate. Next, add a small permission-cleared notification sample and source-authored questions about book/notification relationships, effective dates, exceptions, and Plus/Pro boundaries. Use new evaluation cases for that expansion; the existing held-out set must not become a tuning target. Pinecone, Gemini answers, and the user/admin app remain separate unfinished steps.
