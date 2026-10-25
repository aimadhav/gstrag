# Pinecone milestone: hosted vector storage, without changing the evidence rules

Completed 22 October 2026. Pinecone is connected to the application and contains the audited **149-vector sample**. This is a small resume-project integration, not a full GST index or scale benchmark. Gemini generation and the React UI are still unbuilt.

Historical snapshot: [the Gemini drafting adapter was subsequently implemented and offline-tested](BACKEND_03_GEMINI_DRAFTS.md), bringing the suite to 207 tests. No live Google request has been verified; React remains unbuilt. Metrics below describe the Pinecone milestone unchanged.

## Explain it to a beginner

Jina turns each passage into a list of 1,024 numbers: an embedding. Previously we kept those numbers in a local JSON cache and Python compared a question against every passage. Now Pinecone keeps a searchable copy of the passage embeddings.

Example: a Plus user asks a question about a pencil-and-sharpener kit. The server looks up the user's current Plus plan, embeds the question with Jina, and asks only the ICAI and notification namespaces for matches. It never asks the firm-book namespace. Returned IDs are checked against the local corpus, and the original local passages provide the actual evidence and page citations.

A separate local topic/date check adds the required loaded notification clauses, even if similarity search did not return them. The packet remains private for admin review. No answer is generated or automatically published at this stage.

## Before and after

| Responsibility | Before | After |
|---|---|---|
| Passage embeddings | Local Jina JSON cache | Same local cache plus a Pinecone copy |
| Dense search | Exact NumPy cosine over all allowed vectors | Pinecone search per allowed namespace, then score-based merge |
| API retrieval mode | BM25 default; local Jina optional | BM25, Jina, or Pinecone selectable; this local `.env` now selects Pinecone |
| Source text / PDF | Local files | Still local; no passage text or PDFs sent to Pinecone |
| Citation provenance | Local PDF/item/page metadata | Same local provenance, validated against returned vector metadata |
| Notification date rules | Separate required check | Unchanged; not delegated to similarity search |
| User-visible answers | Explicit admin decision only | Unchanged |

Vectors and metadata are still derived document data, not anonymization. Pinecone receives chunk/document IDs, source type, plan label, pages, hashes, and vectors. Jina receives question text on a cache miss and passage text if embeddings must be created.

## What actually exists in the account

Index: `gstrag-jina-v1`, dense 1,024-dimensional cosine, AWS `us-east-1`, serverless, deletion protection enabled.

| Namespace | Verified expected vectors | Plus | Pro |
|---|---:|---|---|
| `icai_books` | 15 | Yes | Yes |
| `firm_books` | 130 | No | Yes |
| `notifications` | 4 | Yes | Yes |

These are expected vectors fetched and verified, not a promise that arbitrary future upserts cannot add other records. Query filters select the exact corpus fingerprint. Older snapshots are excluded, not deleted.

The create/upsert/query/fetch implementation uses the documented **2025-10 vectors REST API**, pinned explicitly rather than relying on a changing SDK default. It reuses the existing `requests` dependency. We do not use Pinecone integrated embeddings: Jina remains the embedding model. See [index creation](https://docs.pinecone.io/reference/api/2025-10/control-plane/create_index), [upsert](https://docs.pinecone.io/reference/api/2025-10/data-plane/upsert), and [vector search](https://docs.pinecone.io/reference/api/2025-10/data-plane/query).

No billing plan was changed. There is no promise of zero cost on every account: [Pinecone meters usage and offers a Starter plan](https://docs.pinecone.io/guides/manage-cost/understanding-cost). This run used one small index; no paid upgrade was requested or performed.

## Application flow

```text
POST /queries → SQLite queued row → worker claims current database plan
  → Jina question vector (cache if present)
  → Pinecone top-10 per allowed namespace
  → validate IDs, namespace, corpus/model metadata, source policy, finite scores
  → merge namespace results by score
  → hydrate local passages and take book top-10
  → independent loaded-notification topic/date check
  → notification-first context packing, maximum 2,048 tokens
  → private review packet → explicit admin decision → public plain citations
```

Namespaces help partition data, but do not understand our subscription model. The backend is the authorization boundary. The current database plan is used rather than trusting a stale plan claim in an old JWT. A downgrade during retrieval still causes the worker to discard and reprocess the result.

The separate notification lane uses the local reviewed metadata registry. Semantic search queries the allowed notification namespace too, but its matches do not determine legal applicability. This is intentional: a good similarity score does not establish that an amendment is effective on the transaction date.

## Exact code changes

| File | Change and reason |
|---|---|
| `src/gst_rag/vector_store.py` | Thin REST client, namespace policy, source snapshot fingerprints, safe index-host validation, explicit create/upsert, local hydration and fetch-back checks |
| `src/gst_rag/auth.py` | Accept `pinecone` mode and server-side index-name configuration |
| `src/gst_rag/service.py` | Route dense queries through Pinecone; preserve local BM25/Jina alternatives and mandatory date/context rules |
| `scripts/index_pinecone.py` | Explicit indexing command; validate registered PDFs, reuse cache, upload in batches of 50 and fetch every expected vector |
| `scripts/benchmark_pinecone.py` | Compare the same existing development questions and vectors against local exact search; preserve each timestamped result |
| `scripts/smoke_api.py` | Opt-in live Pinecone HTTP workflow with temporary users and SQLite; preserve the previous BM25 report |
| `tests/test_vector_store.py` | 29 offline tests of transport, metadata, source isolation, stale IDs, invalid vectors and safe failures |
| `tests/test_pinecone_service.py` | 6 offline tests of service integration, mandatory notifications, dates, private citations and provider failures |

No frozen chunking labels, held-out scores, original PDFs, or historical embedding caches were changed. No explicit case-structuring schema was added.

## Why add the fingerprint and local validation?

Imagine a chunk ID from an old edition still exists in Pinecone after the local book changes. Looking up its ID blindly could attach new text to an old vector, or cite the wrong page. A corpus fingerprint binds the bundle, model, dimension and passage task; vector IDs bind that fingerprint and the chunk ID. The query filters for the current fingerprint and model, then validates returned metadata against the local record.

For a second example, if a bad response includes a firm-book ID inside an ICAI namespace, the server rejects the query instead of hydrating it. Unknown IDs, wrong pages, duplicate matches and nonfinite scores also fail closed. Provider failures go to a private review-required packet, not an uncited answer or silent keyword fallback.

The API never creates or uploads an index during a user query. Indexing is an explicit command. It does not delete old vectors, replace another application's index, or silently upgrade the account. Repeating the same upsert uses the same IDs. Partial uploads can be rerun; this is not an atomic publication system for arbitrary replacements.

## Measured results — including the failed check

The suite now contains **149 tests**: 114 prior tests plus 35 new Pinecone/service tests. The live HTTP smoke is separate from those offline tests.

1. **Index verification:** all 149 expected records fetched; metadata matched and stored vector components differed by no more than `1e-6` from local values. Zero new Jina requests for upload.
2. **Retrieval comparison:** all 12 existing development questions had the same top-10 result set as local exact cosine. Exact ordering matched in **10/12**, not 12/12. Complete budgeted evidence remained **7/7** on the evidence-labeled cases. All access, expected date/status, and context-cap checks passed.
3. **Strict numerical parity failed:** the test expected query-score errors no greater than `1e-5`; the largest observed error was approximately **0.0003382**. The saved report retains `false`, and the comparison command exits nonzero. We did not relax the threshold, overwrite the result, or claim identical scores. Fetch-back confirmed the stored vectors; the observed query-score differences are consistent with a different search/scoring implementation, but the exact provider-internal cause is not established.
4. **Search timing:** median local exact search was **2.993 ms**, versus **696.880 ms** for sequential remote namespace search in this one run. This excludes embeddings, startup, packing and human review. Pinecone is not a demonstrated latency improvement at this scale.
5. **Actual HTTP workflow:** **13/13 checks passed** with Pinecone, including protected PDFs, hidden drafts, explicit approval, historical visibility after downgrade and no firm evidence in a new Plus follow-up. The two poll-to-review times were 93.172 and 7.734 seconds in this run with other tests running; these are observations, not steady-state performance targets. The smoke made one new Jina request, 27 tokens, and 11 Pinecone requests. Temporary users/database were removed; the server was stopped.

The comparison used assistant-labeled **development** scenarios already used earlier, not a fresh held-out set. It measures vector-storage/retrieval behavior, not answer correctness, current GST law, legal precedence, scale, or multi-user throughput. Slight score differences can change close rankings and context packing; identical evidence coverage here is not a universal guarantee. No extra reranker was added to hide that difference.

Private aggregate reports (ignored by Git; no keys or passage text):

```text
data/app/pinecone/index_20261022T001215881957Z.json
data/app/pinecone/parity_20261022T001443669369Z.json
data/app/pinecone/http_smoke_20261022T001558084227Z.json
```

## Run it locally

Keep keys only in the ignored `.env`, never in browser code or `.env.example`:

```dotenv
JINA_API_KEY=your_local_key
PINECONE_API_KEY=your_local_key
PINECONE_INDEX_NAME=gstrag-jina-v1
GST_RETRIEVER=pinecone
```

Initial indexing (already completed on this machine):

```powershell
uv run python scripts/prepare_api_corpus.py
uv run python scripts/index_pinecone.py --create
```

`--create` only creates a missing index. Existing indexes must be ready, tagged for this project, and dimension/model-compatible. Requests use bounded timeouts; readiness/visibility polling is bounded. The script retains created resources if a later step fails. No delete command is implemented. Upload acknowledgements are followed by fetch checks because visibility may lag.

Start the application using the existing backend setup:

```powershell
uv run python -m gst_rag.manage init-admin --username admin
uv run uvicorn gst_rag.api:create_app --factory --host 127.0.0.1 --port 8000
```

Initialize the admin only once; choose your own password in the hidden prompt. No persistent admin or user was created by these tests. Use one server process. No server is left running by this milestone.

Verification:

```powershell
uv run python -m unittest discover -s tests -q
uv run python scripts/smoke_api.py --retriever pinecone
uv run python scripts/benchmark_pinecone.py
```

The last command intentionally includes strict numerical parity, so the recorded run exits 1 for score differences despite matching result sets/evidence. Inspect the individual metrics; do not describe it as an all-green benchmark. New runs create timestamped reports. Live commands may consume provider quota; the unit suite uses synthetic vectors and no network.

To switch back without deleting the Pinecone index, set `GST_RETRIEVER=bm25` or `jina` and restart. Startup of Pinecone retrieval verifies the expected snapshot; an unavailable or incomplete index produces a review-required failure. There is no silent fallback.

## Interview answers you can defend

**Why not just keep NumPy?** For 149 vectors, NumPy is simpler and faster locally. I kept it as an exact baseline and added Pinecone to demonstrate external indexing, namespace fan-out, metadata/version checks and backend-enforced access. I have not demonstrated a scale advantage on this sample.

**Why three namespaces instead of one index per plan?** ICAI and notifications are shared; the firm corpus is additional Pro material. Separate source namespaces avoid duplicating shared vectors. Plus queries two namespaces, Pro queries three; returned scores use the same embedding model and cosine metric for merging.

**Does Pinecone replace Jina or SQLite?** No. Jina creates vectors, Pinecone searches vectors, local artifacts preserve text and provenance, and SQLite stores users, plans, queries and review decisions.

**Did local and hosted search match exactly?** The top-10 sets matched on all 12 development queries, but ordering matched on 10 and a strict score-precision assertion failed. I reported both, verified stored vectors separately, and checked evidence coverage after the actual context cap rather than claiming exact equivalence.

**What's next?** Gemini should produce evidence-bound private drafts with citation validation. Admin review remains mandatory. After that, build the small React user/admin screens. Source replacement, automatic topic classification, conversational rewriting and a complete notification corpus remain separate unbuilt work.
