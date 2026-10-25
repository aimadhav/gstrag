# Experiment 02 source repairs and frozen evaluation

Completed on 21 October 2026. Both identified ingestion defects are repaired and verified. Twenty-one unit tests pass, the rebuilt artifact checks pass, and the six new targeted development questions have complete evidence in hybrid retrieval and its assembled context. The configuration was frozen before a single held-out comparison.

Hybrid remains the selected development candidate. **The nine answerable held-out questions were a coverage tie across all three methods**, not evidence that hybrid is universally superior. The tenth held-out question has no source evidence and is excluded from recall averages. No answer generator or abstention policy was tested.

## The fixes explained for a beginner

Think of our system as preparing a searchable set of study notes from a book. It first reads the PDF, divides the content into small passages called **chunks**, and attaches the section title and page number to each passage. A **parent** is the larger subsection containing several of those chunks.

We found two problems while checking those notes against the original PDF. One put passages under the wrong section. The other left a diagram's content out of the searchable text. Neither problem required changing Gemini: these were document-preparation problems, before answer generation even exists.

### Issue one was an extra dot in a heading

**Example.** These are shortened heading names, keeping the numbering from the book:

```text
7.2.9 Ice creams
7.2.10. Solar EPC
7.2.11. Various clarifications
```

All three should be separate subsections at the same level. But notice the extra dot after `10` and `11`.

**Why it happened.** Our code used a regex, which is a text-pattern matching rule. The old rule expected a space immediately after the section number. It recognized `7.2.9 Ice creams`, but not `7.2.10. Solar EPC`, because it encountered a dot where it expected a space.

The code then treated the unrecognized heading as a smaller heading inside the previous subsection. As a result, the solar and clarification material was grouped under 7.2.9. It is like putting your solar notes into a folder labeled ice creams. The words still exist, but their section context is wrong and parent expansion can bring in unrelated material.

**What code changed.** In [chunking.py](../src/gst_rag/chunking.py), we replaced two separate numbering checks with the shared `heading_number()` function.

Before, the heading-depth check used:

```python
number = re.match(r"^(\d+(?:\.\d+)+)\s", item.text)
```

The important final part, `\s`, requires whitespace directly after the number.

Now, the shared helper uses these lines, with its docstring omitted here:

```python
def heading_number(text):
    match = re.match(r"^(\d+(?:\.\d+)+)\.?(?:\s+|$)", text.strip())
    return match.group(1) if match else None
```

The added `\.?` means "allow one extra dot, but do not require it." The next part accepts whitespace or the end of the heading. Both heading formats therefore return the same clean number:

```text
heading_number("7.2.10 Solar EPC")   -> "7.2.10"
heading_number("7.2.10. Solar EPC")  -> "7.2.10"
```

[restore_heading_depth()](../src/gst_rag/chunking.py) now uses that helper to assign heading levels, and [parent_headings_for()](../src/gst_rag/chunking.py) uses it to choose parent boundaries. Fixing only one check would have left the other inconsistent.

**How we checked it.** A test expected all three subsection levels to be `[3, 3, 3]`. Before the fix, it failed with `[3, 4, 4]`. After the fix, it passed. We also rebuilt the actual book passages and checked their parent ownership, rather than trusting the small test alone. The parent count increased from 25 to 27 because the two missing subsection boundaries were restored.

### Issue two was a diagram that search could not read

**Example.** Imagine a rule written inside a flowchart image rather than typed as PDF text. A person can read the boxes and follow the arrows. Our text-based retrieval cannot search those words unless we turn them into text first.

**Why it happened.** Docling detected the page-21 diagram as a picture. However, the default chunking serializer, the component that turns document elements into searchable text, did not describe the picture's internal boxes or arrows. A caption could be included, but that is not the same as indexing the diagram itself. The image existed in the parsed document while its actual contents were missing from search.

**What code changed.** We added a reviewed text description in a separate local file, the picture transcription supplement (`data/audit/chapter7_picture_transcriptions.json`, kept private and not included in the repository). It records the diagram's nodes and arrows, the original picture ID `#/pictures/1`, PDF page 21, and the PDF's checksum. A checksum is a fingerprint used here to check that the supplement belongs to this exact PDF.

[load_picture_transcriptions()](../src/gst_rag/chunking.py) checks that fingerprint, the picture ID, the page, the review status, and that the text is not empty. Then `ReviewedPictures.serialize()` makes the reviewed text available to the chunkers while keeping its original picture reference.

Before, our serializer setup only customized tables:

```python
return ChunkingDocSerializer(
    doc=doc,
    table_serializer=MarkdownTableSerializer(),
)
```

After, [the serializer setup](../src/gst_rag/chunking.py) also uses our picture serializer. The call below is formatted across lines for readability:

```python
return ChunkingDocSerializer(
    doc=doc,
    table_serializer=MarkdownTableSerializer(),
    picture_serializer=ReviewedPictures(),
)
```

Inside [ReviewedPictures.serialize()](../src/gst_rag/chunking.py), these lines attach the new text to the original picture and keep any existing caption text as well:

```python
description = create_ser_result(
    text="Diagram transcription reviewed against the PDF image:\n"
         + picture_text[item.self_ref]["text"],
    span_source=item,
)
parts = [description, original_result] if original_result.text else [description]
return create_ser_result(
    text="\n\n".join(p.text for p in parts),
    span_source=parts,
)
```

`span_source=item` means "this text comes from this original picture." Keeping that link lets us retain the source page instead of adding an untraceable paragraph. `original_result` is the default serialization captured earlier in the function; preserving it prevents the fix from deleting existing caption evidence.

**How we checked it.** We verified the transcription visually, checked that every chunking method included the new picture reference, and confirmed that none of the 285 previously indexed source references disappeared. We then asked a question requiring both branches of the flowchart. Hybrid and hierarchical retrieved all its labeled evidence; fixed windows did not. Simply putting content in the index is not enough: the search must find it too.

This is a manually reviewed repair for one diagram, not a feature that automatically understands every image. The original PDF was not edited, and Docling remains the main parser.

### Why the earlier good score did not catch these bugs

A test only checks what its questions ask about. Our earlier questions did not directly require the missing diagram, and a small passage could sometimes answer a question even with the wrong parent label. A perfect score on that set could therefore coexist with ingestion bugs.

We added six questions specifically covering the diagram and later qualifications, such as an appeal changing an earlier ruling. We also added tests for the repaired code in [test_ingestion_repairs.py](../tests/test_ingestion_repairs.py). The complete test suite now has 21 passing tests. These are checks of particular behaviors, not proof that every possible PDF will work.

Finally, we added [verify_heldout_freeze()](../src/gst_rag/benchmark.py). It checks the frozen files and settings before the final held-out evaluation and refuses to overwrite an existing held-out result. This helps prevent accidentally changing the experiment after seeing its test results. It is an evaluation safeguard, not another document-reading fix.

**Simple interview answer:** "One bug was my numbering rule: it rejected headings with an extra dot and put their passages under the wrong parent. I fixed the shared rule and tested real parent ownership. The other was an image-only diagram missing from searchable text; I added a reviewed transcription with the original source reference and tested whether retrieval could actually find it."

## Changes and proof

### Numbered headings and parent ownership

Both heading-depth restoration and parent selection now use one numbering helper. It accepts `7.2.10 Solar` and `7.2.10. Solar`, while rejecting inline references such as `See 7.2.10` and malformed number prefixes.

Before the change, the new regression test produced heading levels `[3, 4, 4]` for subsections 7.2.9, 7.2.10, and 7.2.11, incorrectly treating the latter two as subordinate headings. After the change it produces `[3, 3, 3]`.

The rebuilt source has separate parents for the solar and subsequent clarification sections. The artifact check validates actual parent membership for 26 canonical units, not merely the existence of the two parent names. Section 7.2.9 now ends on PDF page 14; the solar subsection spans pages 14-17, and the clarification subsection spans pages 17-19. Shared boundary pages are expected.

### Searchable diagram without replacing ingestion

The image-only page-21 flowchart now has an assistant-reviewed transcription of its input nodes, both branches, and both outcomes. This is a small document-specific source supplement, not automatic diagram understanding or a general OCR capability.

The supplement is bound to the document ID, full PDF checksum, original picture reference, and PDF page. Missing review status, wrong-document supplements, empty text, wrong pages, and invented picture references are rejected. The same Docling serializer includes this text for all variants, retaining the picture as the source span. Existing caption text and caption provenance are preserved too.

The source PDF and raw Docling parse are unchanged. Cases remain normal source-order passages; no facts/issue/ruling schema was introduced.

| Artifact | Original experiment | Repaired experiment |
|---|---:|---:|
| Numbered subsection parents | 25 | 27 |
| Canonical units | 244 | 244 |
| Distinct canonical source references | 285 | 286 |
| Fixed chunks | 80 | 81 |
| Hierarchical chunks | 244 | 244 |
| Hybrid chunks | 129 | 130 |

The canonical unit count need not increase: a picture and its existing caption can be serialized together. The new picture reference is added without losing any of the original 285 source references. Every variant covers all 286 refs and retains PDF provenance and Pro-only source labels. Fixed and hybrid chunks remain at most 512 tokens including heading context; hierarchical deliberately retains two oversized elements, with a maximum of 590 tokens.

## Controlled rerun

Original artifacts remain in `data/processed/chapter7/`. Repaired artifacts are in `data/processed/chapter7_repaired/`. The raw parse and cached vectors were copied; source content was not reparsed with a different extractor. Unchanged embedding inputs reused their model/task/text-keyed cache entries.

Repaired configuration ID: `cd6743ef7d8e`, pipeline version `0.2.0`. The comparison uses the same Jina-v3 tokenizer and hosted embedding model ID, normalized exact cosine ranking, top ten hits, and a 2,048-token assembled-context budget. The original 30 audited questions retain their wording and split.

### Original development questions

Twenty questions comprise 18 answerable questions, one out-of-scope question, and one clarification question. Only answerable questions enter these recall means.

| Method | Mean evidence recall at 5 | Mean evidence recall at 10 | Complete evidence at 10 | Mean context evidence recall |
|---|---:|---:|---:|---:|
| Fixed windows | 97.22% | 100% | 18/18 | 91.67% |
| Hierarchical | 87.50% | 94.44% | 17/18 | 94.44% |
| Hybrid | 100% | 100% | 18/18 | 100% |

Hierarchical still misses q05. Fixed windows retrieve its required evidence at ten but lose q04 and part of q05 during budgeted context assembly. This shows why top-ten retrieval coverage and evidence actually passed to a generator are different measurements.

### Six targeted development regressions

The new set tests the summary diagram, a later sharpener-rate note, the Pattabi AAR/AAAR distinction, Vertiv's appeal qualification, the DISCOM circular/court contrast, and Five Star Shipping's changed classification. They were authored and source-audited specifically for known weaknesses, so they are regression cases rather than an independent generalization benchmark.

| Method | Mean evidence recall at 5 | Complete evidence at 10 | Mean context evidence recall |
|---|---:|---:|---:|
| Fixed windows | 83.33% | 5/6 | 83.33% |
| Hierarchical | 100% | 6/6 | 100% |
| Hybrid | 100% | 6/6 | 100% |

Fixed windows fail r01, the flowchart question, despite containing the source text somewhere in the index. Ingestion presence is therefore not proof of retrieval success. Structural/hybrid chunks retain a coherent diagram passage and retrieve its labeled conditions and outcomes.

For these six questions, child-only, neighboring-context, and parent-expansion hybrid modes all have 100% context evidence recall and use a mean of 2,048 tokens. No expansion benefit was demonstrated here. Keep child-only as the simple candidate and preserve parents for subsequent independent experiments; do not claim parents never help. Parent expansion continues to fall back to the matching child when a whole parent will not fit.

## Freeze and held-out result

Before held-out scoring, `experiment_freeze.json` recorded the source/parse, chunk, parent, unit, label, tokenizer, and implementation hashes together with the predeclared evaluation settings. The selected candidate was hybrid child-only, while all three methods were retained for the frozen comparison.

The held-out command checks the hashes and settings before any embedding request. It refuses scoring without a freeze, changed frozen inputs/settings, or an already existing held-out result. Four unit tests cover these local evaluation safeguards. They are experiment discipline, not production security controls.

| Method | Mean evidence recall at 5 | Complete evidence at 10 | Mean context evidence recall | MRR at 10 |
|---|---:|---:|---:|---:|
| Fixed windows | 100% | 9/9 | 100% | 0.8889 |
| Hierarchical | 100% | 9/9 | 100% | 0.9444 |
| Hybrid | 100% | 9/9 | 100% | 0.8704 |

All nine answerable held-out questions have complete labeled evidence within five results and in assembled context for every method. MRR measures the first hit covering any required group, not complete evidence. The one unsupported question, q28, has `null` recall and is excluded; this run does not show whether a chatbot would refuse it correctly.

No source, labels, chunking, or ranking settings were tuned after these scores were inspected. The completed-result verifier checks that the frozen implementation and artifacts remain unchanged. A future optimization needs new evaluation data, not repeated tuning against these ten questions.

## Verification and usage

Twenty-one synthetic unit tests cover the original retrieval/access contracts plus heading recognition, parent boundaries, supplement validation, and freeze safeguards. Actual artifact checks additionally verify complete transcribed diagram text, all prior source references retained, actual subsection membership, source-label policy, source excerpts, and matching frozen results. A Plus-policy BM25 smoke run on this firm-book-only corpus returns zero hits and context; this is not yet JWT-authenticated access control.

The repaired development run required 38,005 newly embedded provider-reported tokens across seven requests. The new regression queries required 314 tokens in one request, and the held-out queries required 353 tokens in one request. Parent and neighboring regression runs reused vectors without new API calls. Total incremental usage was 38,672 tokens across nine requests and 13.349 seconds of aggregate API request time. These are not monetary cost or end-to-end response-time measurements.

The local tokenizer snapshot is `ab036b023d30b4d1138c4c3bfa9f0c445ab455d6`. An offline Transformers load emitted a Mistral-related warning for this XLM-R tokenizer. Rather than apply a Mistral-specific regex replacement, a diagnostic compared wrapper token IDs with the cached original tokenizer backend on 491 strings; all matched. The check includes the tokenizer-file checksum. Hosted Jina model internals remain unpinned.

## Commands and artifact locations

```powershell
uv run python -m unittest discover -s tests -v
uv run python scripts/validate_experiment.py --directory data/processed/chapter7_repaired
uv run python scripts/validate_experiment.py --directory data/processed/chapter7_repaired --questions data/benchmark/chapter7_source_regressions.json
uv run python scripts/verify_source_audit.py --directory data/processed/chapter7_repaired --require-ready --require-regressions
```

Do not rerun chunking into the frozen directory or overwrite the completed held-out report. A new source/chunking experiment belongs in a new directory. The original historical artifact directory is unchanged.

Key local outputs include the three `chunks_*.jsonl` files, `parents.json`, `picture_transcription_audit.json`, `tokenizer_verification.json`, `experiment_freeze.json`, and `source_audit_verification.json`. Retrieval runs have explicit suffixes `audited_main`, `source_regressions`, and `frozen`, preventing the different question sets from overwriting one another. Source text, supplements, quote labels, and full results remain in ignored local data paths.

## Interview explanation and next stage

"My source audit found two bugs that a perfect development retrieval score had not exposed: a numbering edge case and an unindexed diagram. I reproduced the heading bug in a failing test, fixed the shared numbering rule, and validated rebuilt parent ownership. I added a reviewed diagram supplement with original source provenance and measured whether retrieval could actually find it. After development checks, I froze the inputs and compared all three methods on held-out questions. They tied on the nine answerable held-out cases, so I report that result without claiming universal superiority or chatbot accuracy."

The next stage is multi-source evaluation: add a small ICAI sample and actual notification PDFs, verify source access and dated updates, then connect Gemini with supported source/page citations and manual-review routing. This experiment uses only the firm-book chapter. Notification updates mentioned inside it are book passages, not a working ingestion/linking layer for separate notification documents.

Still unimplemented: Pinecone, answer generation, claim-level citation verification, authenticated roles, chat history, React UI, admin uploads, and asynchronous approval. Source ambiguities identified in the earlier audit remain explicit; no current-law legal validation has been performed. The diagram repair is document-specific and does not solve arbitrary image/table extraction. The evidence checker uses reference overlap plus normalized exact excerpts in a retrieved record, not semantic entailment or item-level span binding within merged passages. The question sets are small, source-close, and assistant-authored, limiting generalization claims.
