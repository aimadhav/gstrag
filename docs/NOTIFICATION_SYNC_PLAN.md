# Scheduled official-notification ingestion

Updated 25 October 2026. **Parts 1–3 are implemented:** [discovery/download/private staging](BACKEND_04_NOTIFICATION_SYNC.md), [authenticated source review/controlled snapshot publication](BACKEND_05_SOURCE_PUBLICATION.md), and [durable hosted jobs plus an opt-in GitHub workflow](BACKEND_06_HOSTED_SYNC.md). The importer had a bounded live PDF smoke; publication and hosted-job paths were verified with synthetic sources/fake transports. No real staged notification has been approved or activated. Hosting is not configured and scheduling is not enabled. The user confirmed central-government GST notifications first; individual state-government feeds are deferred.

## Explain it to a beginner

Today we have a few saved notification PDFs. Publishing a new government PDF does not automatically update our application. The proposed job acts like a librarian: check official catalogues, download new or changed English PDFs, parse them with Docling, and record their source and processing state. It must not act like a lawyer: whether a notification changes a book explanation still needs evidence and, where unresolved, admin review.

The scheduler only starts the job. One Python command does the actual ingestion and can also be run manually for demonstrations and troubleshooting. Updated deployment direction: use GitHub Actions as the external scheduler for a separately hosted backend; no laptop-dependent schedule is required for deployment.

## Official-source research

Checked 25 October 2026:

- [GST Council CGST tax notifications](https://gstcouncil.gov.in/cgst-tax-notification) and [CGST rate notifications](https://gstcouncil.gov.in/cgst-rate-notification) expose English/Hindi PDF links and subjects. They are candidate official discovery/mirror sources, **not a verified complete current feed**.
- The rate listing returned entries through 08/2025 in this check. An [official Ministry of Finance / PIB release from September 2025](https://www.pib.gov.in/PressReleaseIframePage.aspx?LID=1&PRID=2168426&RegID=3&lang=2&reg=3) refers to later notifications and points to CBIC Tax Information PDF URLs. This discrepancy means the first listing page does not establish current coverage. Pagination, archives, publication lag and corrections need checking.
- [CBIC Tax Information](https://taxinformation.cbic.gov.in/) is a primary candidate for current discovery, but the research fetch timed out. Its reliable listing/download mechanism and permitted automated access are **not yet verified**. Do not invent a stable API/RSS feed or silently use private tax-news aggregators as the authority.
- [The current cbic-gst.gov.in homepage](https://cbic-gst.gov.in/) also contains other indirect-tax material. An official domain alone is not enough: explicitly filter document type and GST series.

Before a live adapter, verify the exact official listing mechanism, pagination, English original-PDF links, robots/access conditions and representative recent documents. Do not bypass access controls or disable TLS verification when a site is unavailable. Preserve the failure and coverage limitation.

Implementation follow-up: the GST Council robots file, table structure, pagination and one English PDF were verified through Python, and the first two partial-mirror adapters now work. The CBIC Python probe failed TLS certificate validation; verification was not disabled. No sufficiently current primary CBIC feed or complete government coverage is claimed.

## Scope and identity

- Central-government GST sources only. Begin with verified Central Tax and Central Tax (Rate) adapters. Integrated Tax, Union Territory Tax and Compensation Cess series/rate variants need separate supported-source entries as adapters are verified. Do not claim complete central coverage while only two series work.
- Notifications and their corrigenda are in scope; circulars, recommendations, press releases and news are different document types, not interchangeable notification PDFs.
- Identity includes issuer/jurisdiction, series, number, year, language and revision/content hash. `01/2025 Central Tax` and `01/2025 Central Tax (Rate)` are different instruments.
- Preserve issue date, effective date, discovery time and download time separately. An unknown effective date stays unknown; never substitute the issue date as a guess.
- Retrospective provisions, multiple effective dates and ambiguous amendment targets require review. The current narrow notification schema does not support these generally.

## Proposed flow

```text
GitHub Actions daily trigger (implemented opt-in, not enabled)
  → authenticated request to the separately hosted backend
  → durable sync job → run the ingestion command; prevent overlapping runs
  → fetch configured official listings with bounded pagination
  → compare identities/content hashes with the SQLite registry
  → download new/changed English PDFs with size/type checks
  → retain original PDFs and immutable revisions locally
  → Docling parse → page-aware notification chunks
  → store candidate metadata/chunks and status in staging
  → admin confirms identity, dates, topics and candidate links
  → build a new app corpus snapshot
  → Jina embeds new/changed text; reuse the existing cache
  → index and verify the new Pinecone snapshot
  → activate/reload it for new questions
```

**Downloaded/parsed is not the same as active in retrieval.** In the first version, source metadata is confirmed before publication. Downloading, parsing and storage are automated; unresolved legal applicability is not treated as established. Answer approval remains a separate existing admin operation.

Published notification evidence is available to both Plus and Pro through the existing `notifications` namespace. No customer-upload permission or firm-book access changes. Candidate book links may be generated after source confirmation; they are not legal-precedence findings.

## Existing code we can reuse, and integration work needed

1. `scripts/prepare_notifications.py` downloads three fixed historical samples. Keep that reproducible setup intact; the live feed gets a separate app-owned registry and artifacts.
2. Reuse `parse_pdf` from `src/gst_rag/ingestion.py` for Docling parsing and original-page provenance. Failed/partial parses cannot become published sources.
3. `src/gst_rag/notifications.py` validates a narrow Central Tax (Rate), prospective-amendment sample using source anchors. Generalize reviewed metadata deliberately for other series, corrigenda and complex dates; preserve frozen experiment behavior.
4. Add a small SQLite ingestion registry for source versions, attempts and run results. Keep its states separate from user questions and answer approval.
5. `Corpus` loads a pinned bundle. The implemented publication API now atomically switches to a verified bundle, and the real query worker checks its digest between jobs to rebuild retrieval without a manual restart. An in-flight query can finish using its older coherent snapshot.
6. `Snapshot` in `src/gst_rag/vector_store.py` fingerprints the whole corpus. Adding one notification changes the fingerprint and vector IDs for existing records too. Initially publish a complete verified new snapshot using cached embeddings, then switch the app to it. Upserting only the new document under another fingerprint is not sufficient. Preserve the prior snapshot for recovery; no automatic destructive cleanup.
7. A source disappearing from a website does not establish repeal or authorize deleting evidence. Changed PDFs/corrigenda become linked revisions, not silent overwrites of cited PDFs or approved answers.

## Keep scheduling simple

The user intends to host the application elsewhere and suggested GitHub scheduling. **Implemented design: GitHub Actions triggers ingestion; the deployed backend owns the job and its persistent state.** The workflow and backend code exist, but no hosted URL, repository settings or secrets have been configured. See the [setup guide](BACKEND_06_HOSTED_SYNC.md).

Proposed frequency: once daily at 07:17 Asia/Kolkata (01:47 UTC in the workflow), subject to user confirmation/enablement. GitHub supports UTC by default and an optional IANA timezone. Manual `workflow_dispatch` is included. Scheduled workflows run from the default branch, can be delayed or dropped under load, and public-repository schedules are disabled after 60 days without repository activity. Do not use this as a precise-time or guaranteed-freshness service. [Official schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

Implemented behavior:

1. A GitHub Actions workflow makes one authenticated HTTPS request to a fixed ingestion-trigger endpoint on the deployed backend. Do not accept arbitrary source URLs or commands in the trigger payload.
2. `POST /internal/notification-sync/jobs` validates a dedicated narrowly scoped sync credential, creates/reuses a durable ingestion job and returns its ID promptly. It does not parse every PDF inside the HTTP request. A separate authenticated GET endpoint returns safe job status/counts.
3. A single backend worker runs the existing planned ingestion command against persistent source storage and the ingestion registry. No extra Redis/Celery service is needed for the initial single-instance demo.
4. GitHub may check authenticated run status with a bounded timeout. Successfully queuing a job is not a completed download, parse or publication. Report these separately, without logging source passages, proprietary files or credentials.
5. Use workflow concurrency plus backend job deduplication/overlap protection. Retries of the trigger must not create duplicate ingestion work. Backend status is authoritative even if a workflow is cancelled or times out.
6. Store only the trigger credential in GitHub Actions secrets. Keep Jina/Pinecone/provider keys on the backend. Do not embed keys in committed YAML, request URLs or logs. Verify GitHub Actions usage limits for the selected repository/account rather than promise zero cost.

Why not store the database/PDFs only inside GitHub Actions? Standard hosted runner VMs are created per job and decommissioned afterward; runner-local files are not the application's persistent storage. [Official runner lifecycle](https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/use-github-hosted-runners). The preferred design avoids copying the live SQLite database, book corpus or firm PDFs into a CI job. If heavy parsing later moves to a runner, it will require an explicit durable-storage/result-import design, not just uploading vectors and losing the source registry.

Hosting requirements remain to be selected: the backend needs persistent storage for SQLite/PDFs and support for background processing with enough resources for Docling. A short-lived serverless request alone is not the planned ingestion worker. For a small single-instance demo, a persistent mounted data directory can be sufficient; do not treat ephemeral deployment storage as durable. GitHub Actions is the scheduler, not hosting for the React/FastAPI app or its database.

The one-shot command remains runnable locally without a schedule. Windows Task Scheduler or host-native cron are optional alternatives if the eventual host makes them simpler. The hosted-job endpoints and opt-in workflow now exist as code; no credential, GitHub repository configuration, enabled schedule or cloud resource was created. The deployed URL and host choice are still needed before wiring a real trigger.

## Minimal reliability and safety

- Discovery-only dry run and bounded first import/backfill; do not automatically download the entire historical archive.
- Idempotent repeat runs: unchanged PDFs do not create duplicate active chunks or repeat embedding charges.
- Official-host allowlist, HTTPS, validated redirect destinations, bounded downloads, safe generated filenames, PDF validation, timeouts and bounded retries. No credentials in URLs/logs.
- Respect source access conditions and rate limits. Do not bypass CAPTCHAs or other blocks. PDF text is untrusted evidence, never executable instructions.
- Resume interrupted work without premature publication. One failed PDF must not conceal other run outcomes.
- Unexpectedly empty/unparseable listings are discovery failures, not successful zero-new-document runs. Detect incomplete scans/pagination.
- Recheck prior entries for replacement PDFs and corrigenda; monotonically increasing number/date checks miss corrections and late uploads.
- Index failures keep the previous app snapshot active. Successful discovery is not successful publication.
- Do not mutate frozen chunking/retrieval datasets, labels, caches or benchmark results.

## Completion evidence

Offline fixture tests first:

1. New PDF, unchanged repeat run, changed bytes under the same identity, and identical numbers in different series.
2. Pagination, relative links, English/Hindi variants, corrigenda and late uploads.
3. Timeouts, rate limits, unsafe redirects, invalid/oversized PDFs and empty/changed HTML.
4. Parser failures and unknown/ambiguous metadata remain staged, not retrievable.
5. Interrupted/repeated/overlapping runs recover without duplicate publication.
6. A verified new corpus becomes active; publication failure leaves the old corpus usable.
7. Both plans retrieve published notifications; firm books remain Pro-only.
8. Source revisions do not rewrite historical approved answers or their original citations.

Then demonstrate a bounded official discovery/download/parse run and a reviewed publication. Record actual stage counts, failures, runtime and measured provider usage. Enable the scheduler explicitly only after that.

## Next task

The importer, source-review/publication backend, hosted trigger/worker/status path, opt-in GitHub workflow and [React admin workspace](FRONTEND_02_ADMIN_WORKSPACE.md) are implemented. The UI covers source review, publication preparation/activation, human answer review and import monitoring/requests, while provider-writing indexing stays an explicit trusted-backend command. Next implement admin PDF upload/replacement with a deliberate revision/publication policy. Hosting selection and real deployment configuration can happen separately. A sufficiently current primary discovery source and additional central series still need verification. The real downloaded source still awaits admin review, and no schedule has been enabled.
