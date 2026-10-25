# Hosted notification trigger and GitHub scheduler

Later follow-up: the [admin frontend](FRONTEND_02_ADMIN_WORKSPACE.md) now provides import controls using current-role-checked admin JWT routes, not the scheduler secret. Source review/publication also have React screens. The original verification counts and remaining-work notes below describe this earlier backend milestone; hosting/enablement and PDF upload/replacement remain pending.

Implemented 25 October 2026. Code is ready for a **single hosted backend with persistent storage**; it is not deployed, and no GitHub variables/secrets or live schedule have been configured. The existing real staged notification still awaits admin review. This milestone made no live government downloads, Jina/Gemini calls, Pinecone writes or source approvals.

## Explain it to a beginner

Before: we could run a Python command to collect notification PDFs, but somebody had to start it manually.

Now: GitHub can act as an alarm clock. It tells our server, “Please check for notifications.” The server saves that request in SQLite and answers immediately with a job number. Its background worker downloads and parses PDFs. GitHub checks the job number until the work finishes or its waiting time expires.

Imagine GitHub loses the first response and rings again. Both requests carry the same ticket number (`Idempotency-Key`), so the server returns the same job instead of repeating the import. If another, different request arrives while a job is active, it gets a conflict rather than creating a backlog.

Downloading is **not** approving. New PDFs go into an incoming tray, not directly onto the chatbot's bookshelf. The admin still confirms metadata/clauses, prepares a snapshot, explicitly indexes/verifies it, and activates it. Answer approval remains another separate operation.

```text
GitHub daily/manual workflow (opt-in; not enabled here)
  → HTTPS trigger with dedicated sync credential + stable request key
  → persistent SQLite job → single background import worker
  → two official partial-mirror listings → bounded PDF downloads → Docling staging
  → admin source review → prepare/index/verify/activate snapshot
  → new questions can retrieve published notification evidence
```

## What code changed, and why?

| File | Responsibility |
|---|---|
| `src/gst_rag/sync_jobs.py` | Persistent jobs, idempotency, one active job, restart recovery, worker ownership and safe status summaries |
| `src/gst_rag/api.py` | Narrow sync trigger/status endpoints, lifespan startup/shutdown, readiness reporting |
| `src/gst_rag/auth.py` | Separate opt-in, secret and bounded import settings |
| `scripts/trigger_notification_sync.py` | Standard-library HTTPS client: retry the same trigger, poll the same job, redact failures |
| `.github/workflows/notification-sync.yml` | Opt-in daily/manual invocation, default-branch guard, concurrency, pinned checkout, read-only repository permission |
| `.env.example` | Blank secret, disabled default, explicit limits; the real `.env` was not edited |
| `tests/test_sync_jobs.py` | Offline queue, API, transport, workflow and end-to-end fixture checks |

The existing importer still owns official-host allowlisting, robots checks, bounded downloads, hashing and staging. This feature calls it with server-selected arguments; it does not duplicate the parsing logic or change frozen retrieval experiments.

## API contract

Both endpoints require `Authorization: Bearer <dedicated sync secret>`. A user/admin login JWT is **not** this credential. The sync secret cannot log in, read admin PDFs/source excerpts, approve sources, publish snapshots or approve answers.

### Start or recover a request

`POST /internal/notification-sync/jobs`

- JSON body must be `{}`. Extra fields such as `url`, `publish` or parser options are rejected.
- Required `Idempotency-Key`: 1–128 characters from letters, digits, `:`, `_`, `-`.
- Returns HTTP 202 and job ID/status. Even a completed duplicate returns its existing job; 202 alone does not mean work finished.
- Same key always returns the same job while the persistent database is retained, including after completion/failure.
- Different key while a job is queued/running: HTTP 409 `sync_job_in_progress`. No second job is silently created.
- Disabled or unavailable worker: HTTP 503. Missing/wrong enabled-service credential: HTTP 401.
- After a failed terminal job, use a **new** request key for an intentional retry. A GitHub rerun uses the original key and checks that original outcome; a fresh manual workflow run has a new run ID.

### Check status

`GET /internal/notification-sync/jobs/{job_id}`

States: `queued` → `running` → `completed`, `completed_with_errors` or `failed`. Status remains readable with the configured secret if the worker has stopped but the API is still serving. Successful trigger/status responses use `Cache-Control: no-store`.

The response includes timestamps, attempt count and a restricted summary: new/unchanged/staged/deferred counts, error count, bounded-scan flag, partial-source coverage, `published: 0` and `active_corpus_changed: false`. It excludes raw exception bodies, local paths, source passages and detailed URLs. Detailed importer reports stay in the backend registry.

**`completed` means a bounded import finished without recorded processing errors. It does not mean the government feed is complete/current, that any notification is legally applicable, or that anything was published.** An import can complete with zero new PDFs. A successful bounded scan may still have unvisited pages/deferred documents.

`GET /health` reports `notification_sync: disabled | ready | unavailable`, without exposing credentials or source data.

## Reliability choices, without extra infrastructure

- Jobs live in `data/app/notification_sync/hosted-jobs.sqlite3`, independently of the user-question queue and importer execution logs.
- SQLite transactions and a partial unique index enforce one queued/running hosted job, even with racing requests.
- The worker holds a separate OS-managed SQLite owner lock for its lifetime. A second worker fails startup rather than resetting a live job. The lock is released on process death; no expiring lease can accidentally grant two workers ownership.
- Only the lock owner recovers `running` jobs to `queued` on startup. This is **at-least-once execution**, not exactly-once execution. The importer's content-addressed versions/hash checks make repeat staging safe; a crash can still repeat network work or parsing.
- Existing importer/publication locking still serializes actual storage mutations. If a local import/publication holds that lock, the hosted job tries up to three times, two seconds apart, then fails with `importer_busy`. Other failures are redacted as `import_failed`.
- Polling the database every two seconds means the wake-up event is only an optimization; losing that event does not lose a persisted job.
- Graceful shutdown requests a stop and joins for two seconds. It cannot forcibly interrupt Docling midway through a PDF. An in-progress job may finish while the process lives; if the process is killed, the next startup recovers it. The old worker retains its owner lock until it actually exits.
- A fatal worker/storage error marks readiness unavailable; the API refuses new jobs. Restart is the recovery path, not a production supervisor.

Run **one Uvicorn process/worker and one instance** on a persistent local disk. Do not place this SQLite lock design on an unverified network filesystem, use multiple replicas, or use ephemeral/serverless storage. Persistent storage must include the existing corpus/source files and the entire `data/app` directory, not just the new job database.

Docling also needs adequate CPU/RAM, its parser assets and the cached `jinaai/jina-embeddings-v3` tokenizer used by staging. Jina/Pinecone/Gemini credentials are not needed for this import path; the tokenizer is local, not a remote embedding call. Missing model/tokenizer assets remain a deployment prerequisite, not something GitHub secretly installs for the backend.

## Enable later, when hosting is chosen

No secrets are supplied here. Generate a strong random URL-safe secret (32–256 characters, preferably at least 32 random bytes before encoding). Use a password manager or local secret generator; do not paste it into chat or commit it. **Never reuse the JWT signing key.** This is a simple shared service credential, not GitHub OIDC or a complete public-service security layer. Restrict/rotate it and protect the hosted endpoint with HTTPS.

### Backend environment

```dotenv
GST_NOTIFICATION_SYNC_ENABLED=true
GST_NOTIFICATION_SYNC_SECRET=<dedicated random secret, not this placeholder>
GST_NOTIFICATION_SYNC_MAX_PAGES=1
GST_NOTIFICATION_SYNC_MAX_DOCUMENTS=2
GST_NOTIFICATION_SYNC_SINCE_YEAR=2025
```

Pages are bounded per listing (1–5); documents are bounded per job (1–5). The year filters listing identity, **not effective date**. Current adapters cover only Central Tax and Central Tax (Rate) through partial GST Council mirrors; not all central series or individual states. Starting the worker does not itself trigger a new scan, but previously queued/interrupted jobs resume.

Start the existing application as one worker using the normal backend command:

```powershell
.venv/Scripts/python.exe -m uvicorn gst_rag.api:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

That loopback command is for a local/reverse-proxy setup, not a complete hosting recipe. Configure the selected host's HTTPS ingress and persistent storage separately. Do not use the development reloader in deployment. `GET /health` must show the sync worker ready.

### GitHub repository settings

On a trusted repository/default branch, add:

| Type | Name | Value |
|---|---|---|
| Actions variable | `GST_BACKEND_URL` | Hosted HTTPS API base URL, optionally with a simple path prefix; not localhost |
| Actions secret | `GST_NOTIFICATION_SYNC_SECRET` | Same dedicated credential configured on the backend |
| Actions variable | `GST_NOTIFICATION_SYNC_ENABLED` | `true` only when deliberately enabling the workflow job |

Keep provider credentials on the backend. The runner checks out code and runs the small standard-library client; it does not install Docling, download PDFs, upload artifacts or copy the SQLite database. Checkout is commit-pinned with credential persistence disabled. Secret-bearing execution is guarded to the default branch, including manual runs. Do not weaken that guard to execute untrusted branch code with the secret.

The proposed daily time is **07:17 Asia/Kolkata**, expressed as **01:47 UTC**. It is a code default, not a user-confirmed or enabled schedule. Both the repository opt-in and backend opt-in must be configured. When repository opt-in is unset/false, GitHub may create a scheduled workflow entry but the import job is skipped; no backend request is made.

Test one manual **Run workflow** before relying on the daily schedule. The client retries transient trigger/transport failures at most three times with the same key, polls for at most ten minutes and returns nonzero for errors/partial completion. A polling timeout does **not** cancel the backend job or prove it failed. GitHub's twelve-minute job timeout/concurrency are additional runner safeguards, not backend cancellation.

GitHub schedules run from the default branch and can be delayed/dropped; public-repository schedules may be disabled after 60 inactive days. They are not a precise freshness guarantee. Check account-specific Actions allowances rather than promise free execution. [Official scheduling documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [workflow permissions/concurrency reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

The HTTPS client refuses redirects, verifies TLS normally, rejects credentials/query strings in the configured base URL and constructs the status URL itself. It never trusts a server-provided redirect/status URL with the secret. It uses no ambient proxy or `.netrc` credentials. Logs contain a job ID/terminal status or a safe error code, not raw backend responses.

To disable future triggers, set the repository variable false/disable the workflow; disable the backend worker setting if wanted. Neither action rolls back approved sources or cancels an already-running import. Existing job/source state is retained. No cleanup/deletion job was added.

## Verification and honest interview answers

The targeted suite has **42 passing tests**, and the full regression suite passes **325 tests** (283 prior + 42 new). Tests use temporary SQLite databases, synthetic HTML/PDF bytes, fake parsing and fake HTTP transports. A fixture integration runs the actual trigger client, FastAPI routes, persistent queue worker and existing importer through two synthetic notifications. Both reach `pending_source_metadata_review` with retrieval disabled; the pre-existing corpus sentinel remains byte-identical and no publication directory is created. This is not a new live Docling/hosted/GitHub smoke. The real active corpus hash was also checked unchanged, and no real publication directory was created.

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_sync_jobs.py
.venv/Scripts/python.exe -m unittest discover -s tests
```

The tests cover repeated/racing triggers, conflicting keys, crash recovery, competing worker ownership, bounded importer-lock retries, credential separation, strict payloads, worker readiness, redacted failures, safe HTTPS transport, polling timeouts and workflow guardrails. The existing Starlette/httpx deprecation warning remains; it is not a test failure. Frontend code is unchanged; its last result remains 33 tests plus production build, not a fresh browser verification.

**Why GitHub and not run ingestion inside the web request?** “GitHub is only an external alarm clock. The API durably records work, returns a job ID quickly, and a worker parses on our persistent backend. That avoids tying a long PDF parse to one request or losing the database on an ephemeral runner.”

**Why no Celery/Redis?** “For one résumé-demo backend, SQLite transactions and one worker demonstrate durable jobs, idempotency and recovery without another service. Multiple replicas or larger workloads would need a different ownership/queue design.”

**Is it exactly once?** “No. Request creation is deduplicated, but a crashed import can execute again. Version hashing and immutable source artifacts make retries safe without claiming network calls or CPU work happen only once.”

**Does this keep GST law up to date?** “Not by itself. We have only two partial official-mirror adapters and a bounded scan. Sources require admin review/publication, and answers still need review. I distinguish import success from source completeness, legal precedence and answer correctness.”

Remaining: choose/deploy a suitable host, configure secrets/variables, verify one real hosted manual run, then enable scheduling. A React source-review panel and admin PDF replacement/upload remain separate next features. No full recruiter-popup walkthrough has been added yet.
