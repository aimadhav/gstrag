# Notification sync, part 1: discovery, downloads and private staging

Implemented 25 October 2026. This is the first working part of the scheduled-ingestion plan, **not an enabled GitHub schedule or a complete/current GST feed**.

## Explain it to a beginner

Before, `prepare_notifications.py` knew three specific PDF addresses. It was like having three bookmarks, not a subscription to updates.

Now a new command reads two configured official notification lists, finds English PDFs, checks which documents it has already seen and downloads a bounded number. Docling can then turn them into page-cited draft chunks. SQLite remembers what happened, including failures and document revisions.

Think of this as an **incoming tray**, not the chatbot's approved bookshelf. Every parsed document waits for source metadata review. The job does not guess effective dates, declare that a notification overrides a book, or make its chunks searchable by customers.

## What exists now

- Two GST Council adapters: Central Tax and Central Tax (Rate).
- `discover`: read-only source discovery, English-only PDF selection, bounded pagination and explicit coverage warnings.
- `sync`: duplicate-safe downloads into app-owned storage, immutable PDF content hashes and an SQLite version/run registry; optional `--parse`.
- `stage`: process already downloaded PDFs without accessing the notification website or embedding/generation providers.
- `status`: inspect source/version/run counts without network access.
- A single-process sync lock, retryable interrupted parsing, per-document errors and download ordering that does not starve older unchecked entries.
- Staged Docling HybridChunker records with PDF-page provenance. These are generic drafts, not source-audited complete operative clauses.

At the end of this part-1 milestone, active-corpus publication, the admin ingestion-review screen, hosted sync endpoint/worker and GitHub Actions workflow were unbuilt. The subsequent [source-review/publication backend](BACKEND_05_SOURCE_PUBLICATION.md) implements authenticated APIs and verified snapshot activation; its new React panel and hosted schedule remain unbuilt. Existing answer review is a separate feature and does not approve staged sources.

## Before and after

| Concern | Historical sample setup | New ingestion command |
|---|---|---|
| Discovery | Three hard-coded source URLs | Configured official tables and English column |
| Repeat downloads | File-existence check | SHA-256 identity/version registry |
| Changed PDF | Reject changed sample | Retain new immutable revision alongside the old one |
| Processing state | Per-sample files | SQLite runs, candidates, versions and safe failure codes |
| Parsing | Docling experiment output | Separate app-owned Docling parse and draft chunks |
| Legal metadata | Narrow source-audited sample | Unknown fields remain null pending review |
| Active chatbot corpus | Existing reviewed snapshot | Unchanged by every importer command |

The original setup scripts and frozen retrieval experiments remain intact.

## Commands

Run from the repository root, using the existing virtual environment. No `.env` loading, Jina/Pinecone/Gemini credentials or model API calls are required by these commands.

```powershell
# No file/database writes: inspect a bounded official listing.
.\.venv\Scripts\python.exe -m gst_rag.notification_sync discover --source cgst_rate --max-pages 1

# Download at most one PDF and parse it into PRIVATE staging.
.\.venv\Scripts\python.exe -m gst_rag.notification_sync sync --source cgst_rate --max-pages 1 --max-documents 1 --parse

# Download only, without running Docling.
.\.venv\Scripts\python.exe -m gst_rag.notification_sync sync --source cgst_tax --max-documents 1

# Retry downloaded/interrupted/failed parses without fetching the website.
.\.venv\Scripts\python.exe -m gst_rag.notification_sync stage --max-documents 1

# No network access.
.\.venv\Scripts\python.exe -m gst_rag.notification_sync status

# Offline deterministic regression checks.
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_notification_sync.py
```

Without `--source`, discovery/sync covers both currently configured CGST lists. `--source` is repeatable. `--max-pages` defaults to one **per source**, with a maximum of 30; `--max-documents` defaults to two, maximum 20. Defaults intentionally do not backfill the entire archive.

`--since-year` defaults to 2025 and filters the notification identity's year, **not its legal effective date**. An unnumbered corrigendum has unknown year and remains a candidate for review rather than being silently dropped. A deployment needing older amendment chains must choose an explicit backfill policy; the default is not complete legal coverage.

The `--root` option selects a dedicated staging directory. Do not point it at an existing experiment directory. Discovery does not create that directory. On a new host, set up Docling models and the cached `jinaai/jina-embeddings-v3` tokenizer first; staging loads the tokenizer locally only. Docling may need its ordinary model downloads on first setup. A tokenizer is not an embedding API call.

## Storage and states

Default directory: `data/app/notification_sync/`, ignored by Git.

```text
registry.sqlite3                 candidates, versions, runs, stage checksums
run-lock.sqlite3                 OS-released exclusive run lock
pdfs/<content-sha256>.pdf        immutable downloaded content
staging/<version-id>/
  manifest.json                 Docling source/settings/version provenance
  docling.json                  full structured parse
  document.md                   readable parsed text
  staged.json                   draft chunks + unknown legal metadata
```

Regular identities distinguish series/number/year/language. Corrigenda receive separate URL-derived candidate identities without inventing their amendment target. Each candidate/content-hash pair has one version. Two different identities can share a content file without becoming the same notification.

States: `downloaded → parsing → pending_source_metadata_review`; a failure becomes `parse_failed` and can be retried with `stage`. Staging is **not** publication. Completed documents are checksum-verified, then skipped on a repeat parse. A changed PDF creates a new version rather than overwriting the previous PDF. Unexpected corruption is reported, not silently repaired.

Interrupted runs are marked as interrupted on the next exclusive run; interrupted parsing can resume. Jobs use one local worker/SQLite lock, not distributed scheduling. JSON/PDF writes use a temporary job-owned file and atomic replacement. A crash between storing a PDF and recording its version can leave an unregistered content file; the next matching download can reuse it. No automatic garbage collection/deletion is implemented.

## Fetch and discovery decisions

- Exact official-host allowlist; HTTPS with normal certificate validation. Every redirect is checked before following it; application credentials are not loaded or attached.
- Robots rules are checked per host. An explicit missing robots file (404) is allowed; blocked/unavailable/challenge responses fail closed. No CAPTCHA, access-control or certificate bypass.
- Public requests use a descriptive user agent, a small delay, timeouts, streamed size bounds and bounded retries. Long `Retry-After` requests are deferred as failures instead of retrying early.
- Listings are capped at 2 MB and PDFs at 20 MB. PDF content type/signature/EOF are checked before storage; these envelope checks are not a complete PDF-structure audit. Docling conversion is an additional stage and can still fail.
- Find identity/English/subject columns by headings, not hard-coded positions; the tax table has an extra serial-number column.
- Treat missing/empty/ambiguous tables, unexpected rows, unsafe links, repeated page bodies and missing next-page markers as discovery failures—not successful “no new notifications” results.
- Report truncated pagination explicitly. Failed page sets are not downloaded. A bounded but successful page window may be processed, with the incomplete window recorded.
- New unchecked entries are processed first, then the least recently checked. Example: with a two-document limit, the next run can pick entries 3–4 instead of downloading entries 1–2 forever. Later runs re-fetch selected PDFs to detect changed bytes; this is not an ETag/304 optimization yet.

The source adapter is based on the public GST Council table, not a reverse-engineered private API. Public source material is retained locally, not republished through GitHub artifacts.

## Actual live verification

On 25 October, a read-only two-page scan of each configured listing returned **20 candidates**, no discovery errors, and explicit `bounded_scan: true` because both had more pages. No storage was written by that discovery command.

A separate bounded `sync --source cgst_rate --max-pages 1 --max-documents 1 --parse` run:

- Discovered 9 candidates in that selected year/page window, including one unnumbered corrigendum.
- Downloaded **1 PDF**, deferred **8 candidates**, and staged **1 draft chunk** from **1 original PDF page**.
- Source: [Notification 08/2025 Central Tax (Rate), official English PDF](https://gstcouncil.gov.in/sites/default/files/2025-01/ctr08-2025.pdf).
- PDF SHA-256: `9210875981c1668848f289e8624fe3d200c12330117308abf53c1972adc89837`.
- Draft chunk: 464 local tokenizer tokens; page `[1]`; no token-budget overrun. This is structural evidence, not a legal-correctness or retrieval-quality score.
- State: `pending_source_metadata_review`, `eligible_for_retrieval: false`; issue/effective dates remain unknown in the staged schema.
- No run errors, no external embeddings/generation, no Pinecone writes and **0 published documents**. The active corpus still contains 149 records across five source PDFs.
- A subsequent offline `stage` run found no remaining eligible work and created no additional chunk or publication.

The generic offline Transformers Mistral-regex warning appeared for the existing XLM-R tokenizer. The cached original tokenizer backend was compared with the wrapper on the new chunk: **0 token-ID mismatches and 0 token-count mismatches**. Snapshot `ab036b023d30b4d1138c4c3bfa9f0c445ab455d6`. The new loader explicitly retains `fix_mistral_regex=False`, consistent with the earlier project diagnostic; no Mistral-specific replacement or frozen-experiment change was made.

The GST Council robots request succeeded through the Python transport and allowed these paths. The CBIC Tax Information probe failed certificate validation in this environment. TLS was not disabled, and no CBIC adapter or complete-current-feed claim is made. The existing [source research and coverage caveats](NOTIFICATION_SYNC_PLAN.md#official-source-research) still apply.

## Tests and interview explanation

There are **38 new offline tests** in `tests/test_notification_sync.py`. They exercise the transport policy, robots, redirects, retries, size/type failures, source identities, language columns, pagination, revisions, deduplication, corrupt storage, interrupted/overlapping runs, bounded-run fairness, retryable parsing, no-write discovery, offline status/staging and the no-publication boundary. Parser fixtures are synthetic and do not call Docling or embedding providers; the real Docling path was checked separately by the bounded live smoke above.

Final regression run: **248/248 Python tests pass** (210 existing plus 38 new), using `python -m unittest discover -s tests`. A pre-existing FastAPI/Starlette test-client deprecation warning remains; no test failed. The React frontend was unchanged in this milestone; its last verified result remains 33 passing frontend tests.

**What problem did you solve?** “I built an idempotent, bounded importer for official notification PDFs, with content-version tracking and a separate unreviewed staging area. Repeated runs do not duplicate versions, failures can be retried, and newly downloaded documents cannot silently enter the answer corpus.”

**Why not index immediately?** Finding a PDF does not establish its identity, effective dates or relation to earlier law. The current mandatory notification-check lane needs reviewed metadata. The running app also needs a new verified corpus snapshot, not merely another vector in Pinecone.

**Why no Celery?** The demo needs one one-shot ingestion command, persistent SQLite bookkeeping and one worker. GitHub Actions will supply the external trigger after the hosted endpoint exists; it is not persistent source storage.

**What must you not claim?** A complete/current government feed, autonomous legal-update interpretation, fully automated active-corpus publication, an installed cron/GitHub schedule, or successful hosted deployment.

## Next step

The next milestone, [reviewed metadata and controlled corpus publication](BACKEND_05_SOURCE_PUBLICATION.md), is now implemented and tested offline. Next add the authenticated hosted job trigger/status path and GitHub Actions schedule once the deployment target is known. A sufficiently current primary CBIC discovery adapter and the remaining central-government GST series still need separate verification.
