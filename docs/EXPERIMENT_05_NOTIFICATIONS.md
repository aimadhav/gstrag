# Experiment 05: notification ingestion and mandatory update checks

Completed: 21 October 2026. This is a small, local development experiment, not a current-law service.

## What now works

Three official notification PDFs were downloaded unchanged, fully read as independent PDF text and page images, and converted with the existing Docling parser. Four source-reviewed chunks cover the selected renewable-energy and pencil-sharpener provisions. Metadata records notification identity, issue date, effective date, amendment target, source clauses, and original PDF pages.

The experiment combines those chunks with the existing 145 hybrid book chunks. A separate notification-check lane selects relevant, commenced amendments independently of ordinary top-K book retrieval. It reserves complete notification conditions before filling the remaining context with book passages.

**77 unit tests pass.** Both keyword and Jina development runs pass the 12 supplied date/status expectations. All seven questions with labeled evidence have complete evidence in the checked context. Unknown applicability and incomplete amendment chains always require review; no legal answer is automatically approved.

Important limitation: the caller supplies the two reviewed topic IDs and an explicit transaction date. Automatic question/topic classification is not implemented. These results evaluate deterministic metadata selection with structured inputs, not an end-to-end chatbot.

## Explain it to a beginner

Imagine searching a tax folder and finding an older book paragraph that closely matches your question. A matching paragraph can still describe the wrong time period. A notification can also be published on one day but start operating later.

The project now does two separate jobs:

1. Search the permitted books for an explanation.
2. Independently check the loaded notification records for that topic and date.

The second job must happen even if no notification appears among the most similar ten passages. Similarity means "this text resembles the question"; it does not mean "this legal change has commenced".

If the date is missing, ask for it. If the available documents cannot establish the legal position, collect evidence for admin review instead of inventing a conclusion. The current code produces the review status and source bundle, not an actual legal answer or a working admin inbox.

## Sources and exact experiment scope

| Official source | Issue date in PDF | Commencement date in PDF | PDF pages | Selected indexing scope |
|---|---|---|---:|---|
| [24/2018 Central Tax (Rate)](https://gstcouncil.gov.in/sites/default/files/2024-05/download_2024-05-17t160748.759.pdf) | 31 December 2018 | 1 January 2019 | 4 | Conditional allocation explanation for old entry 234 |
| [8/2021 Central Tax (Rate)](https://cbic-gst.gov.in/pdf/central-tax-rate/notfctn-08-2021-cgst-rate.pdf) | 30 September 2021 | 1 October 2021 | 6 | Old-entry omission and new renewable-energy entry, including the two-page condition |
| [3/2023 Central Tax (Rate)](https://www.gstcouncil.gov.in/sites/default/files/2024-05/03_2023-ctr-eng.pdf) | 28 February 2023 | 1 March 2023 | 1 | Paired pencil-sharpener insertion and exclusion |

These are historical sample documents, not the newest notifications available in October 2026. The experiment does not establish the complete amendment chain, corresponding State/Integrated Tax instruments, subsequent changes, court orders, or current applicability. All 11 pages were parsed and reviewed, but only the selected provisions are indexed in this experiment; unrelated amendments remain in the raw conversions.

The official [2018 listing](https://gstcouncil.gov.in/node/4494), [2021 listing](https://www.gstcouncil.gov.in/en/node/4546), and [2023 listing](https://www.gstcouncil.gov.in/en/node/4578) identify the documents. The source cards retain URLs and checksums. The PDFs, parsed content, labels, vectors, and reports stay in ignored local directories. Public availability is not treated as a blanket permission to redistribute an entire website; no public redistribution or deployment is performed here.

## Technical flow

```text
Original official PDF
  -> Docling conversion: full document, original page positions
  -> source-checked clause/metadata review
  -> four intact notification chunks with original evidence spans
  -> local mixed corpus: ICAI + firm book + notifications
  -> source-type access filter
  -> ordinary book ranking AND mandatory topic/date notification check
  -> reserve full required notification evidence within context budget
  -> internal review-required result or date-clarification result
  -> public status only, never an unapproved answer
```

This remains a local retrieval experiment. No Pinecone namespace, JWT authentication, Gemini generation, persistent review queue, or React screen was added in this step.

### Source-reviewed metadata, not automatic legal understanding

`scripts/build_notification_sample.py` creates local review JSON files for the three audited parses. `reviewed_records()` validates:

- PDF checksum, document ID, and exact Docling JSON checksum.
- Explicit source-review status.
- Notification identity, including the **Central Tax (Rate)** series.
- Original item references, page lists, and actual quoted source text.
- Issue and commencement dates against their explicit English-date anchors.
- The referenced amendment target.
- Nonempty, unique selected clause IDs and known source references.

The reviewed annotations identify subject, affected provisions, and operative change. The original selected clauses retain conditions and qualifications; no model extracts a facts/issue/ruling schema or automatically enumerates every possible exception.

Metadata deliberately records `effective_to=null`, `supersession_status=not_established`, and `chain_complete=false`. Here a null end date means **unknown**, not "guaranteed to remain in force forever". The limited schema rejects retrospective effects rather than pretending to handle them.

The review is assistant source-audited, not independently expert-validated or admin-approved. Replacing a PDF or reconverting it invalidates old anchors when its hashes differ.

### Keep linked amendments and conditions together

The 2021 renewable-energy table is split by Docling into an item on PDF page 2 and its continuation on page 3. The reviewed clause includes both source items, plus the relevant schedule and insertion text. The omission of the older entry is indexed separately, but the update check collects both records.

Do not read the omission alone as an exemption. Do not retrieve only the goods list and drop the condition on the next page. Those are examples of why notification-specific grouping differs from arbitrary fixed windows.

Table cell text and order are retained, while Markdown padding and separator rules are removed in this notification serializer. That avoids spending tokens on long strings of dashes. The original table and page images remain available for review.

Notification chunk sizes including context prefixes are **295, 122, 429, and 205 tokens**. Each fits the 512-token limit. The full 11-page raw conversions remain unchanged; these four records are not a claim that every amendment in the PDFs has been indexed.

### Distinguish a tax component from a combined rate

The PDFs in this sample are Central Tax (Rate) instruments. Their chunks are tagged `rate_scope=cgst_only`. The code does not silently reinterpret a central component as the total GST charge, double it, or decide that a book's combined-rate statement conflicts merely because the two numbers differ. Applying a rate to a real transaction remains a review question.

### Automatic links are candidates, not override decisions

`book_links()` finds explicit notification-number-and-series references in book chunks. It normalizes leading zeroes, so `08/2021` and `8/2021` match, but it does not confuse Central Tax, Central Tax (Rate), and Integrated Tax notifications with the same serial number.

The actual sample produces four candidate links, all from the firm book, across the three loaded notification identities. Each is marked `candidate_pending_admin_review`. A citation to a notification establishes a possible connection; it does not establish that the whole book explanation is overridden. These candidates have not been promoted to approved legal relationships.

Plus cannot see firm-book candidate links or firm-book context. The CLI supplies the plan for these tests; the authenticated backend must eventually derive it from trusted server-side identity. A CLI flag is not an authentication boundary.

### Mandatory date check and bounded context

`check_updates()` selects all records for the supplied topic that have both been issued and commenced by the supplied date. It distinguishes an issued-but-not-yet-effective record from a commenced one. It does not choose a legal winner just by sorting publication dates.

On missing dates it requests clarification. On no matching evidence, unknown relationships, or incomplete chains it requires review; absence of a record is not proof that no notification exists.

`update_context()` puts complete selected notification clauses first, then fills the remaining 2,048-token evidence budget with permitted book hits. If mandatory notification evidence alone cannot fit, it reports an over-budget review reason instead of cutting away a condition. The budget is for evidence excerpts, not the entire future LLM prompt.

The code returns an internal source bundle. `public_status()` projects that to only `status` and a fixed safe `message`. It does not return passages, inferred practical effects, draft text, candidate links, or PDF URLs. Actual approved-answer rendering and admin-only PDF endpoints remain unbuilt.

## A citation problem prevented in the mixed corpus

Docling references such as `#/texts/11` restart in every PDF. An excerpt in one notification must not accidentally satisfy an evidence label for another notification with the same local reference.

`qualified_group_covered()` therefore requires:

1. The correct document ID.
2. The claimed source item and a matching quote in that item's evidence span.
3. That quote to remain present in the actual retrieved/budgeted text.

This also rejects a quote from another source item in the same merged chunk. The older single-document evidence checker remains unchanged for its historical experiments.

## Actual development benchmark

Twelve new scenarios were authored after source reading and saved before retrieval scoring. Seven have labeled retrieval evidence. The others test issue/effective boundaries, an unpublished document, missing dates, or a topic absent from the loaded notification sample. There is no new held-out test set.

The mixed corpus contains 15 ICAI hybrid chunks, 130 firm hybrid chunks, and four reviewed notification chunks. Plus has 19 eligible records; Pro has 149. Book passage embeddings are reused from existing caches. Search is local normalized cosine for Jina, or the existing BM25 implementation for the keyword diagnostic. No vector database was used.

Two context policies were compared at the same 2,048-token budget:

- Ordinary global top-ten ranking, with source access filtering but no temporal selection.
- Mandatory notification selection using the supplied topic/date, followed by ranked book context.

The second policy has additional structured inputs. This is **not a controlled test showing better embeddings**. It tests whether explicit metadata checks can enforce a business rule that ordinary similarity alone does not enforce.

| Retriever | Complete ordinary context | Complete checked context | Date/status checks matched |
|---|---:|---:|---:|
| BM25 keyword diagnostic | 6/7 | 7/7 | 12/12 |
| Jina dense | 7/7 | 7/7 | 12/12 |

BM25's ordinary context misses part of the labeled amendment evidence for n08, the current-position question. Jina has complete required evidence on every labeled case, so there is **no dense evidence-coverage gain** on this small sample.

Nevertheless, ordinary context from both retrievers contains not-yet-effective notification records in five scenarios: n01, n02, n03, n05, and n06. The checked context contains none. This is a deterministic date-selection result, not proof that a language model would have answered incorrectly when shown those records. A future answer can discuss an upcoming notification if it labels it correctly; this experiment conservatively excludes it from the commenced-evidence lane.

For n08, the small loaded corpus still does not establish current law in October 2026. For n09, the date must be clarified. For n10, no loaded notification covers the requested hotel topic. For n12, the text requesting firm-only material does not change Plus eligibility. These test safe routing/access behavior; they do not measure correct final refusal wording or legal decisions.

All conclusions are held for review. There is no generated-answer accuracy score and no automatic legal-precedence decision.

## Integration bug found: the one-token overflow

The first BM25 run produced 2,049 tokens for n04 despite a 2,048-token limit. The initial Jina run did not exhibit this particular overflow.

Beginner explanation: we cut a sentence after what looked like the last allowed token in the full sentence. But when the shortened sentence was tokenized on its own, its ending split differently and became one token longer. A character position from the full text is not a guaranteed token count for its prefix.

In `src/gst_rag/benchmark.py::assemble_context()`, the old behavior was effectively:

```python
text = text[:offsets[remaining - 1][1]]
used += len(tokenizer.encode(text, add_special_tokens=False))
```

The fix retokenizes the actual prefix and moves the cut back until it really fits. A regression test uses a prefix-sensitive tokenizer double that reproduces the extra-token behavior. Complete mandatory notification records still are not truncated; any final budget truncation applies to additional book context.

The initial results remain saved. Corrected runs have the `_budgetfix` suffix and record the current implementation hashes and `packing_version=retokenized_hard_cap_v2`. The same questions, evidence labels, model, and search settings were retained. The coverage counts above are from the corrected runs, whose source/access/budget verification passes.

No old frozen artifacts or held-out results were recomputed or rewritten. The archived original source snapshot still matches the original freeze; current source has evolved.

## Cost, timings, and reproducibility

Docling conversion times, as recorded by the parser, were 40.877 seconds, 62.155 seconds, and 10.161 seconds for the three PDFs. They exclude the separate human/assistant source-reading effort and are not production latency estimates.

Incremental Jina usage for the initial dense run was **1,528 provider-reported tokens across two requests**, 2.738 seconds aggregate API time. Existing book vectors were reused; there were zero conflicting seeded cache values. Corrected reruns needed zero new embedding requests. Do not mistake zero-cost cache reuse for the original embedding work costing nothing.

Provider model internals are not pinned. The existing XLM-R tokenizer diagnostic remains unchanged; no Mistral regex patch was applied. See Experiment 02 for that earlier investigation.

New runtime imports used by the retrieval code (`numpy`, `requests`, and `python-dotenv`) are now declared directly in `pyproject.toml`; the lockfile was refreshed offline. The PDF audit used the bundled pypdf reader only for independent inspection. Docling remains the ingestion parser; pdfplumber was not added.

## Files and commands

Main implementation:

- `src/gst_rag/notifications.py`: reviewed clauses, canonical identity/date checks, candidate links, update selection, context reservation, public status, and document-qualified evidence matching.
- `src/gst_rag/benchmark.py`: actual-prefix hard-cap fix.
- `scripts/prepare_notifications.py`: original official downloads and full Docling conversions.
- `scripts/build_notification_sample.py`: the explicit sample reviews, selected clauses, links, and new development labels.
- `scripts/benchmark_notifications.py`: mixed-corpus global-versus-checked comparison.
- `scripts/verify_notification_experiment.py`: local source, metadata, provenance, access, date, and budget checks.
- `tests/test_notifications.py` plus the prefix-budget regression: 30 additional tests; total suite 77.

Ignored local outputs:

```text
data/sources/notifications/             original PDFs and source cards
data/processed/notifications_v01/       complete Docling conversions
data/audit/notifications/               checksum-bound reviewed metadata
data/benchmark/notification_questions_v1.json
data/processed/notification_experiment_v01/
  notification_records.json
  book_notification_links.json
  source_report.json
  benchmark_bm25_dev.json               initial diagnostic, one cap violation
  benchmark_jina_dev.json               initial embedding usage retained
  benchmark_bm25_dev_budgetfix.json     corrected comparison
  benchmark_jina_dev_budgetfix.json     corrected cached comparison
  verification.json
```

For an initial build in a fresh workspace with the existing permitted book artifacts:

```powershell
uv sync --locked
uv run python scripts/prepare_notifications.py
uv run python scripts/build_notification_sample.py
uv run python scripts/benchmark_notifications.py --retriever bm25 --output-tag budgetfix
uv run python scripts/benchmark_notifications.py --retriever jina --output-tag budgetfix
```

The benchmark refuses to overwrite an existing result. Use a new experiment directory/version for a genuinely changed corpus or question set. Do not modify old labels to improve a scored result. Do not expect a new execution of current code to reproduce the historical pre-fix overflow; that initial diagnostic is preserved as recorded evidence.

To inspect the completed experiment without provider calls:

```powershell
uv run python scripts/verify_notification_experiment.py --require-dense
uv run python scripts/verify_structure_repair.py --require-retrieval
uv run python -m unittest discover -s tests -v
```

The notification verifier checks that review page renders exist under `tmp/pdfs/notification_review/`; after cleaning temporary images, regenerate them from the unchanged PDFs before rerunning that visual-audit-record check. File existence records the inspection artifacts but does not independently prove that a reviewer read them.

## Interview explanation

"I separated relevance from temporal applicability. Dense search already retrieved all labeled evidence on my small notification set, but it also included amendments that had not commenced for the requested date. I added a mandatory metadata check, retained cross-page conditions, qualified evidence IDs by document, and kept uncertain conclusions pending review. The experiment uses supplied topic/date inputs, not automatic legal reasoning. I also found and fixed a real token-budget overflow caused by prefix retokenization."

If asked whether the system knows every latest GST update, answer **no**. If asked whether candidate links prove a book is superseded, also answer **no**. The honest implemented claim is: source-reviewed notification ingestion and deterministic date/access/review controls on a small development corpus.

## Next build step

Expose the tested retrieval/update-check service through a small FastAPI app, with trusted manual role assignment and separate user/admin response models. Then add Gemini generation with backend-resolved citations and private high-risk drafts. Persist the pending/approved states in SQLite before building React screens. Pinecone integration remains separate from these local chunking and evidence experiments; no payments, microservices, or production queue infrastructure is needed for the demo.
