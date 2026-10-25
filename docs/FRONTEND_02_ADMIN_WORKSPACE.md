# Admin workspace and human-in-the-loop controls

Later same-day milestone: [admin uploads and replacements](BACKEND_07_PDF_UPLOADS.md) supplies the previously missing library/upload controls and book-parse review. The verification counts and limitations below describe this earlier milestone, not the latest total.

Implemented 25 October 2026, extending the existing React/TypeScript frontend. This is a local résumé-project milestone, not a public deployment. **57 frontend tests and 333 Python tests pass**, and the production build/type checks pass. The previous frontend milestone had 33 tests; this adds 24 frontend tests and 8 backend permission tests.

## Explain it to a beginner

The chatbot needs three different “yes” decisions:

1. **Is this source recorded correctly?** Check the notification's original PDF, identity, dates, exact evidence quotes and complete clauses. Approve or reject its metadata.
2. **Should this collection become available to retrieval?** Prepare a candidate snapshot, verify/index it on the trusted backend, then explicitly activate it. Downloading or source approval alone does not change the live corpus.
3. **Can the customer see this answer?** Inspect retrieved evidence, edit the private answer, select citations, and explicitly approve it. Alternatively request clarification or refuse safely.

Example: importing a PDF is like putting a book in an incoming tray. Reviewing it adds a checked catalogue card. Publishing puts it on the usable bookshelf. Approving an answer is the separate decision to send a particular explanation to a particular researcher. None of those steps automatically proves that a notification overrides a book.

## Screens now available

| Screen | Working actions |
|---|---|
| Admin overview | Pending-answer count, staged-source count, active-record/PDF totals, worker readiness and navigation to each checkpoint |
| Review inbox | Search/filter pending questions, inspect private evidence and PDF pages, edit/save drafts, choose citations, approve/edit-and-approve, refuse, request clarification or reprocess with current access |
| Incoming notifications | Search/filter versions, inspect original parsed items and PDF pages, enter source-bound metadata/clauses, explicitly approve or reject with a reason |
| Corpus publications | Select up to 10 approved source versions, prepare against the displayed base digest, inspect verification instructions/history, explicitly activate a verified matching-base snapshot |
| Import history | Read latest 30 hosted jobs, worker settings/readiness and processing counts; request a bounded import with confirmation; refresh automatically every 5 seconds |
| People & access | Existing researcher-account creation and manual Plus/Pro assignment, with retained approved history after downgrade |
| Source library | Existing admin-only registered PDFs and access labels; no fake upload/replacement controls |

The existing research UI stays minimal: approved answers and citations, not a source catalogue, raw drafts, provider configuration or admin pages. The **Recruiter?** popup remains the planned outline; it was not expanded into a finished technical presentation.

## How to try it

### No backend or keys: isolated preview

From the project root:

```powershell
./scripts/frontend.ps1 dev
```

Open the printed localhost URL (use `http://localhost:5173/` if the in-app browser cannot reach the numeric loopback URL). Choose **Admin preview**, then **Admin overview** or any administration screen. The preview is visibly labelled sample-only, makes no API/provider calls and stores its data only in memory. Refreshing or switching preview identity resets it.

Preview source decisions, import results and “verified” snapshots are illustrative UI states, not actual Docling/Pinecone verification or legal decisions. Never run a sample snapshot ID against the real backend.

### Real auth/API flow with disposable synthetic data

```powershell
./scripts/frontend.ps1 build
.venv/Scripts/python.exe scripts/run_admin_fixture.py --port 8011
```

Open `http://localhost:8011/app/`. The script prints the deliberately public **fixture-only** username/password. `ui-admin` is an administrator; `ui-user` is a Plus researcher. These accounts exist only in the new temporary fixture database and cannot access your real books. No `.env`, original source PDFs or provider credentials are read.

The fixture supplies valid synthetic PDF bytes, constructed Docling source items and a word-count tokenizer. It uses the actual auth, source-review, publication, answer-review and persistent-job code, but **does not test a fresh Docling conversion, live government feed, Jina embeddings or Pinecone**. The banner distinguishes it from both the in-memory preview and the real application.

For source approval in this fixture:

- Issue date: `2025-01-01`; effective date: `2025-01-02`.
- Identity anchor: `#/texts/0`; issue-date anchor: `#/texts/1`; effective-date anchor: `#/texts/2`.
- Select `#/texts/3` as the complete synthetic clause. Fill subject, provisions and operative change with explicit synthetic descriptions.
- Recheck both completeness/source attestations and confirm approval. Dates are never prefilled as a guess for an unreviewed source.

The publication screen shows the exact snapshot ID after preparation. To verify a **fixture** candidate, run the displayed command with **`--root` set to the temporary fixture root printed by the script** and `--mode bm25`. Dry run first; then add `--apply`. Never omit that fixture root and accidentally target the real application. Refresh publications before explicit activation. Real deployment uses its configured retriever/index, not necessarily BM25.

Ordinary shutdown attempts to clean up temporary fixture data. Abrupt process termination may leave its directory behind; it is not live application storage. Do not use these public test credentials for a real account.

### Real application

Use the existing backend setup and an actual admin login. New frontend requests use the same in-memory login JWT and same-origin routes. No new cloud account, admin account or real-source approval was created by this milestone.

## What changed technically?

- `frontend/src/AdminIngestion.tsx`: overview, source-review form/inspector, publication desk and hosted-import controls.
- `frontend/src/types.ts` and `api.ts`: typed contracts and fixed authenticated routes, source pagination, revision/stage/base digests, safe error messages and staged-PDF retrieval.
- `frontend/src/sampleIngestion.ts` and `sample.ts`: isolated, role-guarded preview data. Sample approvals never authenticate to the server.
- `frontend/src/ui.tsx`: shared dialogs/status components and unsaved-change hooks.
- `frontend/src/App.tsx`: admin-only navigation, new screens, answer-review filtering, internal navigation guards and protected PDF download fallback.
- `frontend/src/admin.css`: responsive paper/sage layouts matching the established frontend, with stacked small-screen forms and an original-item inspector beside wide-screen reviews.
- `src/gst_rag/api.py`: admin-JWT-protected GET/POST `/admin/ingestion/sync`; the scheduler's `/internal/...` endpoints remain separately authenticated.
- `src/gst_rag/sync_jobs.py`: latest-job listing using existing safe summaries, not a new queue.
- `scripts/run_admin_fixture.py`: reproducible synthetic real-HTTP demonstration, without touching real ingestion state.

No Celery/Redis, new frontend framework, payment integration, streaming answer release or automatic approval was introduced. The Sites skill's local workflow was used to preserve the existing design and check the local result; no separate hosted Site was registered or deployed.

## Safety and state management

**Authorization lives on the backend.** Hiding admin buttons is helpful presentation, not the security boundary. Every admin API still checks the current active user and current database role. A stale admin JWT loses permission after demotion. A scheduler secret cannot access admin APIs, and a researcher cannot read/start imports through the new routes.

**No scheduler secret in React.** Browser import controls use the current admin JWT. The scheduler's separate secret stays on the backend/GitHub. Payloads remain `{}` with a bounded `Idempotency-Key`; the browser cannot choose arbitrary source URLs, parser commands or publication options. A failed trigger response retains its key while that screen stays mounted, so retry does not intentionally create a duplicate job. Backend active-job protection still applies after navigation/reload.

**Bind decisions to the evidence actually displayed.** Source approval/rejection sends the displayed revision and stage hash. Quote pages come from the selected original source item, not an editable guessed page. Preparation/activation sends the displayed active-corpus digest. The backend rejects stale reviews, changed source artifacts, stale bases and unsupported verification modes/indexes.

**Keep complete text, not an admin-written replacement for the source.** Admins select original Docling items for operative clauses; the backend retains those full items and validates the token budget. The written “operative change” is reviewed metadata, not a substitute for the source. Metadata quotes can be shortened to exact excerpts. A clause over 512 tokens is refused rather than silently truncated. This is not explicit case-structuring; cases remain in source order under the earlier decision.

**Source and answer attestations are not legal proof.** Clause/source checkboxes start unchecked, including when revisiting a saved review. Editing metadata clears the general source attestation; changing selected clause items clears that clause's completeness check. Retrospective effects, unsupported series/corrigenda and active-source replacement remain subject to the backend's separate-policy restrictions.

**Protect unsaved work.** Source forms and edited answer drafts warn on page unload. Internal navigation asks before discarding; changing/reloading an incoming source also asks. Draft text remains private when saved. Signing out intentionally ends the in-memory session; it is not an autosave feature.

**PDFs stay admin-only.** Both registered and staged PDFs are fetched from fixed authenticated endpoints. React uses short-lived blob URLs without putting a JWT in a URL. The viewer offers an original-PDF download fallback when the browser lacks inline PDF support. Blob URLs are revoked on close/unmount. No user-facing answer or citation receives a PDF link.

**Publication is still explicit.** The UI never runs shell commands or writes Jina/Pinecone vectors. Verification instructions are operator-only; the activation button is disabled for unverified or stale-base snapshots. Backend activation rechecks integrity and configured retrieval mode/index. Preparing/verifying/activating sources never approves a customer answer.

## Problems found while building, with examples

### Date edits could disappear in the browser check

Before: a date field could visibly accept `2025-01-01`, then reset when another controlled field changed. The browser interaction path emitted an `input` event that was not captured by the date field's existing change-only state handler. DOM state and React's stored form state differed.

Fix: source-date inputs now update React on both input and change events. A regression test enters a date with an input event, edits another field and checks the date remains. The real browser source-approval flow then succeeded. This does not establish that every browser/device was tested.

### A PDF could fetch successfully but display a blank inline viewer

Before: the protected PDF modal offered only an iframe. The in-app browser did not render the synthetic PDF inline, even though authenticated fetching worked.

Fix: an admin-only blob download link now remains visible above the iframe. The unit test checks that the link has no token, uses the fetched blob and is revoked when closed. Inline rendering remains browser-dependent; it was **not** verified in the in-app browser.

### Editing could discard a half-completed review

Before: navigating from an edited answer to another administration page unmounted the editor immediately.

Fix: shared unsaved-state reporting plus an explicit discard dialog. Source switching gets the same protection. Tests and the browser check verify staying keeps the edit, while discarding is deliberate.

## Verification actually performed

- **57 frontend tests**, including 24 new checks across typed requests and admin UI workflows: hidden researcher navigation, overview, blank initial dates, source approval/rejection, attestations, stale revision failures, unsaved edits, preparation without activation, verified activation with confirmation, disabled worker controls, duplicate-key retry, preview isolation and the PDF fallback.
- **333 Python tests**: 325 prior plus 8 new admin-import authorization/payload checks. Current role checks, service/admin credential isolation, disabled worker behavior and duplicate requests are covered.
- Production TypeScript check and Vite build pass. No new dependency installation was required.
- A real browser loaded both the in-memory preview and the built frontend served from the temporary backend.
- Browser + actual API: logged in as `ui-admin`, inspected staged items, approved synthetic metadata/clauses, prepared a snapshot, verified it with the trusted local BM25 CLI against the **temporary fixture root**, and explicitly activated it. Fixture corpus changed from 2 records/2 PDFs to 3/3, not the real corpus.
- Browser + actual API: manually drafted and explicitly approved a synthetic answer, signed in as `ui-user`, and saw only its released answer/citations without administration controls.
- Browser + actual API: a bounded fixture import completed with 1 unchanged version, 0 errors and 0 published sources. This uses fake official transport/parser, not government requests.
- The real active corpus SHA-256 remains `83a8245e8a93738c900655e55db0a96abb57d1e7e7b416c83d14a7e105b5fec3`; no real publication directory was created. No real notification/source/answer approval, cloud publication or provider call was made in this milestone.

Responsive CSS is implemented. Browser visual checks used the available desktop viewport; a separate mobile-device/browser matrix was not performed. The existing Starlette/httpx deprecation warning remains, without failing tests. No full accessibility audit or production-readiness claim is made.

The owned preview and fixture servers were stopped after verification. The environment blocked deletion of the two disposable fixture folders, so they remain at `C:/Users/madha/AppData/Local/Temp/gst-admin-fixture-9mx1qyu8` and `C:/Users/madha/AppData/Local/Temp/gst-admin-fixture-2l9oh749`. They contain synthetic test data, not real sources or provider credentials. No alternative deletion mechanism was attempted. The saved interface screenshot is `output/admin-workspace/overview.png`.

## Interview answers

**Why are there three review screens?** “Source validation, corpus publication and answer release solve different problems. A correctly recorded notification can still be irrelevant to a particular transaction, and a well-formed citation does not prove the generated conclusion. Keeping those decisions separate makes the system's guarantees explicit.”

**Why not put the cron credential in the admin UI?** “It would expose a long-lived service credential to every browser session. The browser already has an authenticated admin identity, so a separate current-role-checked API uses the same safe queue. GitHub keeps its own narrow credential.”

**What if another admin changes a review?** “I submit the revision and stage digest the form was loaded from. The backend checks them and rejects a stale decision. Publication also checks the active base digest. The UI shows a reload message instead of pretending a stale update succeeded.”

**Is the preview the real pipeline?** “No. The preview is in-memory sample data. I separately tested the built app against real FastAPI/SQLite workflows using synthetic PDFs and local BM25 verification. Live government ingestion/Pinecone were verified at earlier milestones, not revalidated through these new screens.”

## What is still not built?

Admin PDF upload/replacement and its revision/publication policy remain the next main implementation task. There is no functioning browser upload endpoint yet, no server-side resumable source-review drafts, audit-history browsing screen, automatic retries/backfills from the UI, role-promotion/account-deactivation screen or web-triggered cloud indexing. Current source decisions are recorded in the existing backend audit tables; the UI shows the latest decision/revision, not a full audit trail.

Hosting, persistent deployment storage, real GitHub settings/enablement and a sufficiently current primary government discovery adapter remain pending. Live Gemini answer validation, classification/conversational rewriting and NeMo are also separate unfinished work. Do not claim this milestone completes the original product plan.
