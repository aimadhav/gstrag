# Gemini private drafts: implemented without a live API key

Completed 22 October 2026. **207 tests pass**: 149 prior tests plus 40 generation/transport tests and 18 generation/API tests. A real localhost HTTP smoke passes **15/15 checks** using a local fake model with the actual audited corpus. A second smoke passes **14/14 checks** without any Gemini key, preserving manual drafting.

Subsequent milestone (23 October): [the React user/admin interface is now implemented](FRONTEND_01_REACT.md), with 210 Python tests and 28 frontend tests. This guide's generation metrics remain the historical stage results; no live Gemini verification has been added.

**No live Gemini request was made.** Model access, actual Google schema acceptance, live completion quality, latency and answer accuracy remain unverified until a key is configured and a bounded live check is authorized. Fake outputs are workflow fixtures, not model-quality measurements.

## Explain it to a beginner

Think of retrieval as finding pages, Gemini as writing a first draft from those pages, and the admin as the person who decides what can be sent to the user.

Previously, the admin had to write every draft. Now the worker can ask Gemini for a structured draft. The backend checks its shape, citation IDs and supporting quotations before saving it in the private review record. The user still sees only a pending status. An admin must explicitly approve, edit and approve, refuse, or request clarification.

If the key is absent, the book is not permitted for external generation, or the model fails, the system keeps the retrieved evidence. The admin can write the answer manually. A missing key does not break login, retrieval, stored chats or review.

## Before and after

| Item | Previous milestone | This milestone |
|---|---|---|
| Draft creation | Admin types it | Optional Gemini draft; admin fallback remains |
| Model input | No model | Current question/date/topics plus permitted excerpts only |
| Output format | Manual free text | Strict structured response, rendered by the server |
| Citation checks | Reviewer selects valid evidence IDs | Also validate each generated claim's IDs, source kind and quoted span |
| User visibility | Approved answer only | Unchanged: never expose a pending draft |
| Provider failure | Not applicable | Keep evidence, record a safe reason, allow manual review |
| Subscription change | Worker discards stale retrieval | Check before generation and discard both draft/evidence if access changes in flight |
| Private book privacy | Firm text stays with retrieval services already authorized | Gemini firm-content calls blocked by default until explicit opt-in |

No case-title/facts/issues/ruling schema was introduced. This is an **answer output schema**, not additional book restructuring.

## The implemented flow

```text
Question → persisted queue → claim current database plan
  → existing BM25 / local Jina / Pinecone retrieval
  → mandatory notification topic/date check and 2,048-token evidence packing
  → recheck job ownership/state/expiry/current plan
  → optional Gemini call using allowed excerpts only
  → validate structure, source IDs, quote spans, source kinds and plain text
  → one SQLite transaction saves private evidence + draft as pending_review
  → admin explicitly decides → public answer plus server-owned plain citations
```

The 2,048-token cap uses the existing Jina tokenizer for consistent retrieval experiments; it is not an exact Gemini input-token count. Generation additionally has a 24,000-character serialized input cap, 4,096 output-token request cap, 128 KiB response-body check and 16,000-character rendered-answer limit. Requests have 5-second connect / 45-second read timeouts, redirects disabled and no automatic retries. These are simple bounds, not a production rate-limit or absolute wall-clock guarantee.

## What Gemini receives — and does not receive

Input is a JSON object with the current question, transaction date, supplied topic IDs, `current_law_verified: false`, and evidence entries containing:

```json
{
  "citation_id": "S1",
  "source_type": "icai_book",
  "excerpt": "The actual permitted retrieved excerpt goes here.",
  "truncated_for_budget": false
}
```

The model does not receive API keys in its prompt, PDF URLs/files, local paths, source-registry names, source item IDs, previous answers or conversation history. The API key is only in the Google request header. The provider has no tools, search grounding, URL fetching or function calls enabled.

The system instruction labels both question and document text as untrusted data and asks the model to ignore embedded instructions. This is defense in depth, **not a guarantee against prompt injection**. A malicious excerpt can still induce bad text; schema checks and quotations are not a full semantic defense. Mandatory human review remains the boundary before publication. NeMo Guardrails has not been integrated.

## The response schema

The model must return:

- `status`: `draft`, `insufficient_evidence`, or `needs_clarification`.
- `book_explanation`, `latest_notification`, `practical_effect`: bounded claim lists.
- For each claim: `text` and one or more `{citation_id, quote}` support items.
- `limitations`, `review_flags`, and `clarification_question`.

Unknown fields and types are rejected. The model cannot set an approved state or supply structured PDF/page metadata. References such as `[S1]` are added by the server, not accepted inside generated claim text. Source names and physical PDF page positions come from the existing retrieval metadata and public citation projection.

Book explanations must cite book sources; the notification section must cite notification sources. Practical-effect claims can cite either. Each supporting quotation must occur in that precise retrieved excerpt after Unicode/whitespace normalization. A quote from a truncated-away passage, another PDF, an unknown citation ID or the wrong source kind is rejected.

Rendered text separates:

```text
Book explanation
Synthetic book explanation. [S1]

Latest notification (loaded evidence only)
Synthetic notification explanation. [S2]

Practical effect
Synthetic practical conclusion for human review. [S2]
```

These are synthetic workflow examples, not GST advice. Every rendered draft also says that the supplied corpus does not verify current law. “Latest” is limited to loaded evidence; neither the prompt nor the date filter completes the amendment chain.

## A concrete issue and why we added these checks

Suppose the model writes a claim with `S999`, but retrieval supplied only `S1` and `S2`. A valid-looking JSON response would still have an invented citation. The backend now rejects it as `generated_citation_unknown`, keeps the evidence, and saves no candidate draft.

Next, suppose it cites a real `S1` but invents a quotation about an exception. Checking that `S1` exists is insufficient. The backend now requires the exact normalized quoted span to exist inside `S1`'s retrieved excerpt.

Finally, suppose an admin approves a draft containing `[S1]` and `[S2]` but selects only `S1` for the public citation list. Previously, valid selected IDs alone would not catch the missing referenced source. Approval now rejects that mismatch until the selected citations include every inline source ID. The same rule applies to manually edited answers.

### What quotation checks do NOT fix

A model could quote a genuine sentence and attach an unrelated or legally incorrect conclusion. The quote-existence check would pass. A regression test deliberately demonstrates this limitation: the candidate remains private and pending, not automatically trusted.

We do not claim automated claim entailment, legal correctness, current-law verification, automatic notification supersession or answer accuracy. Source conflicts, date ambiguity and firm opinion need expert review. The draft status name `validated_private_draft` means **structural and citation-span validation only**.

## Risk and review behavior

All outputs require admin review, not just those tagged high-risk. Model review flags include conflicts, uncertain effective dates, opinion, uncertainty and compliance action. A small keyword rule also tags questions mentioning penalties, deadlines, liability, compliance, due dates, filing or interest. It is an intentionally simple reminder, not a reliable legal-risk classifier. Every packet containing firm material is conservatively tagged for opinion review when generation is allowed.

If the model reports insufficient evidence or asks for clarification, that suggestion is saved only in the private packet. The admin decides whether to publish a safe refusal or clarification request. Missing required topic/date inputs still use the earlier deterministic clarification path without calling the model.

If the provider blocks the prompt/answer, returns incomplete output, malformed JSON, invalid citations, unknown fields, oversized output, links or an error, no usable generated draft is saved. The reason code is private and sanitized; raw rejected completions, provider error bodies and secrets are not stored. Retrieval evidence remains available for manual work.

## Downgrade and persistence checks

1. The worker claims a query using the current database plan, not a stale JWT plan.
2. After retrieval, it rechecks status/revision, expiry, active account and current plan before sending anything to Gemini.
3. After generation, one transaction rechecks those conditions before saving the packet and draft together.
4. A downgrade during the call discards the Pro draft and evidence and requeues the question. It cannot retract data already sent before the downgrade.
5. A pending Pro draft cannot be approved after downgrade without reprocessing.
6. An already approved Pro answer stays visible during its retention window, but is not sent into new Plus retrieval or generation.

No database migration was needed: `draft_text` already existed. Model name, prompt hash, structured validated response, safe usage counters, source IDs and review flags are kept in the private packet. Manual edits change the saved draft while the original generated candidate remains private provenance; that candidate is not represented as the reviewer's final text. Existing expiry/purge behavior remains unchanged.

## Configuration when you add the key later

No key is needed to run tests or the current manual workflow. Later, add the key to your **ignored local `.env`**, never a browser or committed file:

```dotenv
GEMINI_API_KEY=your_local_key
GEMINI_MODEL=gemini-3.5-flash-lite
GST_GENERATION=gemini
GEMINI_ALLOW_FIRM_CONTENT=false
```

Restart the backend after changing environment configuration. The adapter uses a fixed Google `v1beta` `generateContent` endpoint with JSON-schema output via `generationConfig.responseFormat`. It reuses `requests`; no additional model SDK was installed. The configurable default is documented by Google as [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite). The request follows the [structured-output REST documentation](https://ai.google.dev/gemini-api/docs/generate-content/structured-output). These references guided implementation; they do not replace a live compatibility test.

`GET /health` reports configuration only: `not_configured`, `disabled`, or `configured_not_live_verified`. It does not call Google, validate a key, prove model access or attest to live answer quality. An invalid key therefore becomes a private provider-failure result when a query is processed, not a startup connectivity guarantee.

Set `GST_GENERATION=off` to disable generation even with a key present.

### Why firm-book generation needs a separate opt-in

Google's [Gemini API terms](https://ai.google.dev/gemini-api/terms) distinguish unpaid and paid service data use. Unpaid-service inputs/outputs may be used for improvement and reviewed by humans; the terms warn against confidential/sensitive/personal submissions. Paid-service handling has different conditions. Do not assume a free key is suitable for a proprietary book or confidential user questions.

Consequently, if any retrieved evidence is from `firm_book`, the default returns `firm_content_requires_privacy_opt_in` without sending the packet to Google. It keeps the complete evidence for manual review rather than silently dropping firm content and pretending to answer the same question.

Only set `GEMINI_ALLOW_FIRM_CONTENT=true` after confirming the source permission and the account/project's applicable processing terms are suitable. This flag is a developer acknowledgement, **not automatic billing verification, a license check or a paid-plan upgrade**. Even Plus queries must not contain confidential user information under unsuitable service terms. No account setting or billing change was made in this milestone.

## Tests and actual verification

**207 offline tests pass.** The 58 new tests cover transport shape, bounded requests, missing/disabled configuration, data policy, Plus/Pro isolation, quote/source checks, oversized/rejected output, safety blocks, private storage/public projection, approval citations, persistence/reprocessing, stale tokens, downgrades before and during generation, and historical-answer isolation. The earlier ingestion/chunking/Pinecone/API tests remain in the suite.

```powershell
uv run python -m unittest discover -s tests -q
uv run python scripts/smoke_api.py --fake-generation
uv run python scripts/smoke_api.py
```

The default retriever for these smoke commands is explicitly BM25, regardless of the local `.env` Pinecone setting. This isolates generation changes and makes no hosted embedding/vector requests. The fake-generation mode always uses a local provider substitute and a synthetic placeholder key, never the real Google client, even if `.env` later contains a key.

The real localhost fake-generation smoke uses the 149-record audited corpus, actual evidence/quote checks, the real worker, SQLite, source downloads and HTTP API. It passed **15 checks**, including private generation for both Pro and downgraded Plus, explicit approval, protected PDF access and history isolation. It made **two local fake-provider calls and zero external provider calls**. The no-key smoke passed **14 checks**, including manual drafting and approval with evidence retained.

Reports are aggregate, timestamped and ignored by Git:

```text
data/app/generation/http_local_fake_provider_20261022T005015929945Z.json
data/app/generation/http_no_key_manual_20261022T005046413059Z.json
```

Temporary users and databases were cleaned up, no persistent admin was created, and both test servers were stopped. These are workflow checks, not a new held-out benchmark or legal-answer evaluation. Historical chunking labels and frozen score artifacts were not changed. The earlier Pinecone strict score-parity failure remains preserved and has not been reclassified as passing.

## Code map and interview explanation

| File | What changed / why |
|---|---|
| `src/gst_rag/generation.py` | Provider adapter, prompt, strict answer schema, evidence preflight, quote checks, rendering, safe failure and private review outcomes |
| `src/gst_rag/auth.py` | Optional key/model/mode/privacy settings; secret omitted from settings representation |
| `src/gst_rag/service.py` | Optional drafting after retrieval, without discarding retrieval on generation failure |
| `src/gst_rag/store.py` | Pre-call job/access check, transactional draft+packet save, and approval/inline-citation consistency |
| `src/gst_rag/api.py` | Wire configurable drafting into worker; report configuration without a provider health call |
| `scripts/smoke_api.py` | Real HTTP tests for missing-key/manual and fake-generated workflows, with no live Gemini calls |
| `tests/test_generation.py` | 40 provider/schema/grounding-boundary tests |
| `tests/test_generation_api.py` | 18 end-to-end API/state/privacy tests |

**Why structured output?** It lets the backend reject malformed claims and inspect each claim's source IDs and quotation before rendering. JSON validity alone is not factual validity.

**Why can you build this without a key?** Retrieval, provider transport, validation, persistence and publication are separate. A fake provider exercises the complete workflow and a fake HTTP session verifies the Google request/response handling. Neither proves that the live provider accepts the request or writes good answers.

**What does “grounded” mean here?** Citation IDs resolve to permitted evidence and quoted spans exist in supplied excerpts. Semantic support and legal correctness are still human-review responsibilities; a test demonstrates the gap instead of hiding it.

**What can go on a resume today?** “Implemented a configurable Gemini private-draft adapter with structured source references, quoted-span checks, mandatory human approval and downgrade-safe persistence; verified with offline provider mocks and real HTTP workflow tests.” Do not claim live Gemini integration was validated, production-grade guardrails, automatic legal accuracy or generated-answer benchmark scores.

**Next:** when a key is available, verify privacy settings and run one bounded, non-confidential live draft through the same checks. Then evaluate actual answer support on new development questions. React user/admin screens can be built independently; automatic topic classification, conversational rewriting, NeMo and PDF upload/replacement remain unbuilt.
