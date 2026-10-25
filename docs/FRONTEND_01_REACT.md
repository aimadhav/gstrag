# React frontend: from image concept to a working review interface

Follow-up (25 October): the [admin workspace milestone](FRONTEND_02_ADMIN_WORKSPACE.md) extends these screens with source review, publication and import controls. Current results are 57 frontend tests, 333 Python tests and a passing production build. The original counts below are historical.

Completed 23 October 2026. The user first requested a ChatGPT-generated frontend image, then implementation based on it. The built-in image tool produced the concept before frontend implementation began. The Sites skill's local-only workflow was used for the existing app: **no Site registration, source upload, hosting or deployment was performed**.

The frontend production build and TypeScript checks pass. **33 frontend tests pass** after the visual refinement and navigation-scroll fix. At this UI milestone the Python suite passed **210 tests** (207 prior plus three static-serving boundary tests); that backend suite was not rerun for those UI-only revisions. Later [notification sync](BACKEND_04_NOTIFICATION_SYNC.md), [source-publication](BACKEND_05_SOURCE_PUBLICATION.md) and [hosted sync](BACKEND_06_HOSTED_SYNC.md) milestones increase the Python suite to 325 passing tests without changing this frontend. A real browser was also used against a disposable synthetic backend in the original milestone, not just the in-browser sample mode.

## Explain it to a beginner

The backend was already the engine: it could sign people in, find evidence, save pending questions and process admin decisions. But users needed API calls to operate it.

The frontend is now the dashboard around that engine. Researchers have a conversation screen and history. Admins have a private review inbox, an answer editor, evidence inspection, account/plan controls and a source library. The browser still cannot decide what someone is allowed to retrieve: the backend makes that decision.

The image is a design reference, **not a screenshot pasted over buttons**. The implementation is React, TypeScript and responsive CSS. Its colours, serif headings and three-column desktop layout follow the concept, while the actual content and state come from the API.

## What you can operate

| Screen | Implemented behavior |
|---|---|
| Sign-in | Existing username/password login, safe errors and in-memory session token |
| User workspace | Ask a dated/topic-labelled question, submit a follow-up, poll every five seconds, display approved answers or pending/refusal/clarification states |
| Conversation history | Search question text, group follow-ups, reopen a thread; paginate through API history rather than stop at 100 questions |
| Research context | Show current Plus/Pro plan, review expectations, incomplete coverage and 30-day retention; no source catalogue or customer-facing provider details |
| Recruiter? | Open a short placeholder from sign-in or the sidebar; the full technical walkthrough is deliberately deferred |
| Admin review | Load pending questions, expand excerpts, edit/save private drafts, choose citations, confirm approval, refuse, ask for clarification or reprocess |
| People & access | Create researcher accounts with an initial password and manual Plus/Pro plan; change plans through the backend |
| Source library | List registered source PDFs, original page counts and access labels; authenticated admin-only PDF viewing |
| Sample preview | Explicitly labelled, in-memory sample workspace/admin modes with no API calls or real tax answers |

The current inbox is refreshed with **Refresh inbox**; it does not silently replace an admin's draft while they type. User questions poll in the background. Accounts remain limited to the backend's first 100 listed users, clearly labelled in the screen. Review inbox and conversation history paginate the corresponding API endpoints.

The library does not pretend that the original PDF's page count equals the indexed page coverage. ICAI's registered original has 104 pages, but our indexed topic slice remains pages 70–79. PDF upload/replacement controls are **not** part of this milestone; the library explains that files are currently maintained through ingestion scripts.

## Three modes — do not confuse them

### 1. Real application

Normal sign-in uses the existing API, real authentication, current database plans, persistent query/review records and registered corpus. Its retrieval mode still comes from backend configuration. No key is needed for manual drafting. Gemini generation remains implemented/mock-tested but not live-verified.

There is **no browser role switcher for real accounts**. Choosing a Pro plan does not grant admin rights. Researchers never fetch admin evidence or the source registry.

### 2. Interface preview

On the login screen choose **Preview workspace** or **Admin preview**. A banner says it is sample data with no API calls or tax advice. The preview-role selector exists only here. Each preview client has isolated state; it cannot set real plans, create actual accounts, publish a real answer or obtain real PDFs.

Sample PDF viewing deliberately explains that the preview contains no PDFs. It does not invent a URL. Preview edits live only in that tab and reset when the preview is exited or a new preview role is selected. The real login client is separate.

### 3. Disposable API integration fixture

For end-to-end UI checks, `scripts/run_ui_fixture.py` runs the **real** login, owner checks, queue, SQLite and review endpoints with synthetic evidence and a temporary database. It never reads `.env`, provider keys or actual source PDFs. A distinct banner says **API integration fixture**.

Its deliberately public temporary accounts are `ui-user` and `ui-admin`, password `ui-fixture-only-12345`. They have no access to the real corpus. These are test fixtures, not default application credentials. The fixture binds only to `127.0.0.1`; stopping it normally removes its temporary database. Do not deploy it or use these credentials for actual accounts. No permanent user/admin was created during this milestone.

## Run the interface

### On this Windows machine

The system Node is 22.11, below the frontend's requirement of 22.12+. A bundled Node 24.19 runtime was available and used; the global installation was not upgraded. A helper chooses a sufficiently recent installed Node or that bundled runtime:

```powershell
# From the repository root. Dependencies are already installed here.
.\scripts\frontend.ps1 -Action dev
```

Open `http://127.0.0.1:5173/`. The labelled preview works without a backend. For real login, run the existing backend in a second terminal:

```powershell
# Initialize an admin only once, if you have not already done so.
uv run python -m gst_rag.manage init-admin --username admin
uv run uvicorn gst_rag.api:create_app --factory --host 127.0.0.1 --port 8000
```

Choose your own admin password in the hidden prompt. The browser does not offer public registration; use the admin account to create researchers.

To use the isolated fixture **instead of** the real backend:

```powershell
uv run python scripts/run_ui_fixture.py
```

Do not run both on port 8000. If needed, run the fixture with `--port 8001` and set `$env:GST_API_TARGET='http://127.0.0.1:8001'` in the terminal before starting the frontend. This variable configures the dev proxy; it is not a browser secret or provider key.

### Conventional Node setup elsewhere

Use Node 22.12+ and npm:

```powershell
cd frontend
npm ci
npm run dev
npm run build
npm test
```

On this machine the helper also supports `-Action install`, `build` and `test`. It avoids the Windows npm-shim path problem encountered by the generic setup helper. Dependency versions are captured in `frontend/package-lock.json`.

### Serve the built UI from FastAPI

```powershell
.\scripts\frontend.ps1 -Action build
uv run uvicorn gst_rag.api:create_app --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/app/`. FastAPI mounts only `frontend/dist` when a build exists; it does not serve the repository or `data/`. With no frontend build, the API still works normally. Tests verify that `.env`, private files and parent-directory paths do not become static assets.

In development, requests use `/api/...` and Vite proxies to the existing root API routes. In the built app, requests go directly to those same-origin root routes. No permissive CORS middleware or cloud service was introduced. [Vite's development/build model](https://vite.dev/guide/) informed this small client-app setup.

## Authentication and rendering decisions

- Tokens stay in a client-instance variable, not local storage, session storage, URLs or cookies. Refreshing signs you out. Sign-out clears browser memory; it does not revoke an already copied stateless JWT before expiry.
- Every request still relies on server authentication. Hiding a button is a UX choice, not authorization.
- A 401 clears the current session. An old in-flight request's 401 cannot clear a newer token; a regression covers that race.
- The profile refreshes periodically, but new-query access is enforced immediately by the server even if a plan badge has not refreshed yet.
- Pending responses never render an answer or citations, even if unexpected extra fields arrive.
- Answer text is rendered as escaped React text with simple headings. There is no raw model HTML, `dangerouslySetInnerHTML`, or automatic clickable model URL.
- PDF data is fetched from a fixed admin route with the bearer header, then shown through a temporary blob URL. Tokens are never placed in the PDF URL. Blob URLs are revoked when closed or unmounted.
- Provider keys remain backend-only. The frontend directory has no provider-key configuration.

Memory-only tokens reduce persistence but are not an XSS cure. This is a local resume project, not an enterprise session-management design.

## Review behavior and limitations

The review screen uses the current server revision for every save/decision. A stale revision or changed plan produces a readable error rather than silently overwriting a decision. Approval requires selected supporting citations and a separate confirmation dialog; modified text uses the backend's edited-approval action.

Save/reset the draft before switching to another review or refreshing it. A global unsaved-navigation guard across all screens is not implemented; save before leaving the review screen. Public refusals and clarification requests use a separate reviewer-written message, not the unapproved answer text.

Quotation/source checks still do not prove legal correctness. The notification sample is incomplete, conversation rewriting and question classification remain unbuilt, and every answer still requires review. There is no streaming “instant AI answer”, public signup, payment integration, deployment, upload/replacement workflow or new live Gemini verification.

## What browser testing found — with before/after

### Mobile menu hidden behind its scrim

**Before:** a mobile selector containing `.application:has(.sample-banner) .sidebar` set `transform: translateX(-100%)`. The less-specific `.menu-open .sidebar` rule could not override it. The dimming scrim appeared, but the sidebar remained off-screen. Component tests passed because JSDOM does not perform real responsive layout.

**After:** the open-state selector now matches/exceeds that specificity. Closed mobile navigation is also `visibility: hidden`, removing its controls from the accessibility tree. Browser inspection confirmed the open sidebar's left edge was `0`, with no horizontal overflow at the 390px breakpoint.

### Footer controls unreachable on a short screen

**Before:** the fixed-height sidebar had no vertical overflow rule. At a small height, Sign out could sit below the viewport and could not be brought into view.

**After:** the sidebar has `overflow-y: auto`, contained overscroll and a thin scrollbar. The browser successfully scrolled to and activated Sign out. These are observed layout fixes, not changes to subscription logic.

### Test selectors were ambiguous

The first UI test run also caught two test-selector issues: “Interface preview” appears in both the banner and runtime information, and multiple source cards have PDF buttons. Tests now identify the explicit sample banner and scope the PDF action to its source card. Type-checking also caught unsupported Testing Library `exact` options copied from browser locator syntax; these were removed without loosening the assertions.

## Verification record

- Python: **210/210 tests pass**; the three additions cover optional static mounting and private-path boundaries.
- Frontend: **33/33 tests pass** using Vitest, Testing Library and JSDOM.
- TypeScript and Vite production build pass. The Windows helper's bundled-runtime path was also exercised successfully.
- Built `/app/` HTML and both referenced JS/CSS assets returned HTTP 200 from the fixture backend.
- The real browser signed into the disposable API as researcher, opened approved history with plain citations, submitted a follow-up, observed queued → pending review, and saw no private draft.
- The browser then signed in as admin, expanded evidence, saved a private draft (revision increment verified), confirmed approval, changed the temporary researcher's plan, signed back in as that researcher and read the newly released answer. Admin navigation remained absent for the researcher despite Pro access.
- Desktop DOM geometry was checked at 1440px: all three workspace columns were present and the document did not overflow horizontally. The 390px layout and mobile menu were checked too; temporary viewport overrides were reset.
- Full-width screenshot capture was limited by the in-app browser's visible pane. The saved implementation proof is the normal narrow-pane view, not a claimed full desktop screenshot or pixel-perfect comparison.
- No Gemini/Jina/Pinecone calls were made by these frontend tests/fixture. Original PDFs, frozen chunking labels and retrieval benchmarks were not changed.

Browser checks are supervised integration observations, not a claimed automated cross-browser suite or accessibility certification. Native PDF viewer rendering was not visually checked using a real private PDF in this fixture; the authenticated fetch/type checks are covered by frontend tests and the existing backend PDF tests.

Local design artifacts (ignored by Git):

```text
output/design/gst-workspace-concept-v1.png       ChatGPT-generated concept
output/design/frontend-workspace-mobile-v2.png  Actual implemented UI, sample preview
```

The original generated image remains untouched. The exact final image prompt and mode are in [the design-reference note](FRONTEND_DESIGN_REFERENCE.md). Preview/test servers started for this work are stopped during handoff; run the commands above to reopen. No permanent demo account was seeded.

Cleanup note: the tooling interruption stopped both owned servers, but filesystem policy blocked removal of the leftover synthetic fixture folder `C:\Users\madha\AppData\Local\Temp\gst-ui-fixture-mpiix4pq`. It contains only the verified two public fixture accounts, three synthetic queries, a temporary SQLite database and empty corpus stub—no real PDFs, keys or accounts. It remains in Windows Temp; no deletion workaround was attempted. The real `data/app/gstrag.sqlite3` was not created.

## Code map and interview answers

| File | Responsibility |
|---|---|
| `frontend/src/App.tsx` | Login, user workspace/history, review desk, people, library, dialogs and role-based navigation |
| `frontend/src/api.ts` | Typed requests, memory-only token, expiry handling, pagination and authenticated PDF fetch |
| `frontend/src/types.ts` | Separate public query/citation contracts from private admin evidence |
| `frontend/src/sample.ts` | Explicit, isolated sample-mode client; never authenticates to the real API |
| `frontend/src/helpers.ts` | Conversation grouping, source/topic labels, readable statuses and dates |
| `frontend/src/styles.css` | Generated-concept visual language, responsive breakpoints and mobile fixes |
| `frontend/vite.config.ts` | Dev proxy and `/app/` build base; no backend keys exposed |
| `scripts/frontend.ps1` | Portable local commands with a suitable Node runtime on this machine |
| `scripts/run_ui_fixture.py` | Disposable real-API/synthetic-evidence browser-test environment |
| `src/gst_rag/api.py` | Optional public-assets mount without exposing the source/data tree |

**Why React/Vite rather than another full-stack framework?** FastAPI already owns authentication, retrieval and review. A small typed client avoids adding another server architecture. No SEO or server-rendered marketing page is required.

**Does removing the source catalogue secure Plus access?** No. The backend chooses allowed namespaces and rechecks plans. The UI only presents access; a user changing browser code still cannot authorize a forbidden retrieval.

**Why sample mode?** It makes the interface demonstrable before credentials/model keys are available, without fabricating a successful live AI answer. It is visibly labelled and isolated from the real client. Separately, the synthetic API fixture proves that the actual UI calls can operate the backend.

**Why did you need browser checks after unit tests passed?** JSDOM does not model CSS layout. The mobile selector-specificity and scrolling defects were invisible to component tests but obvious in an actual browser. I documented the failed behavior and the exact CSS repairs.

**What can you claim now?** “Built a responsive React/TypeScript user/admin interface for a FastAPI GST research backend, with private review, explicit approvals, source citations, plan management and authenticated PDF access; tested with 33 frontend tests and disposable real-API browser workflows.” Do not claim live Gemini answer accuracy, completed upload/replacement, production security, full accessibility certification or public deployment.

## Customer simplification and recruiter placeholder — 23 October

The approved design originally showed an **Included sources** list, including a locked firm-book row for Plus. The user asked to keep customer information minimal. That catalogue is now removed; the plan card no longer names internal collections, and provider/retriever status is admin-only. Customer help explains asking, review, follow-ups and retention without an implementation walkthrough. Approved answer citations and backend permissions are unchanged. Admin source-library inspection is unchanged.

**Recruiter?** is a small, explicitly opened button on sign-in and in the workspace sidebar. It reuses the native dialog with a close button and Escape handling. It does not open automatically, fetch private data, or require an account. For now it only says that the technical walkthrough will be added after project completion.

Deferred content checklist (not implemented in the popup): architecture and request flow; Docling/chunking choices and parent-child retrieval; reproducible benchmark results and limitations; Plus/Pro enforcement; asynchronous review; frontend/API integration; engineering trade-offs and lessons. Populate it only after the project is complete, using actual measured results and clearly separating implemented, tested and planned features. Do not turn it into a production-readiness or legal-accuracy claim.

New component coverage verifies minimal Plus/Pro context, unchanged approved citations, recruiter access without login/network calls, workspace access, close-button handling and Escape cancellation. Build and all 31 frontend tests pass.

Browser verification for this revision used the labelled no-network sample preview: opened the popup from sign-in and the mobile sidebar, closed it with the X and Escape, and inspected the rendered context to confirm no source catalogue or runtime badge for researchers. Screenshot: `output/design/frontend-recruiter-placeholder-v1.png` (local ignored QA artifact). No real accounts, backend records, provider calls or deployments were needed.

## Visual refinement and a navigation fix — 23 October

The user requested a more polished interface. This pass keeps the ivory/forest-green identity and adds clearer answer headers, more readable body text, softer question bubbles, a visible composer focus state and a distinct but small recruiter invitation. Sign-in wording is less technical. No customer source catalogue was reintroduced.

The recruiter popup now has a dark editorial introduction, three **planned** outline rows and a **Back to project** button. The rows are ordinary list items, not dead links or buttons. They deliberately contain no finished architecture walkthrough, fabricated metrics or completion claims. Close and Escape still work. A short-screen breakpoint keeps the full popup visible at the normal 870 × 612 preview size; narrower screens retain native dialog scrolling when necessary.

### Explain the issue to a beginner

Before: if you scrolled down to click **Preview workspace** on sign-in, the new workspace could inherit that scroll position. Imagine opening a book and landing halfway down the first page: the content is correct, but the introduction seems missing.

Why: React changed the screen's contents without a full page navigation, so the browser kept its existing scroll position. A component test cannot visually reveal that problem.

After: a small effect in `WorkspaceApp` calls `window.scrollTo(0, 0)` when the view or selected conversation changes. Opening the workspace, changing screens or starting a fresh conversation shows its beginning. A normal follow-up in the same conversation does not change those dependencies, so this effect does not reset scroll on each polling update or keystroke.

### Code and verification

- `frontend/src/App.tsx`: dedicated recruiter outline, optional modal styling, small entry cards, answer identity and navigation scroll reset.
- `frontend/src/refinements.css`: a separate readable refinement layer, imported after the base CSS in `frontend/src/main.tsx`; no new runtime packages, external fonts or generated image dependency.
- Component tests verify that planned topics are not published links, **Back to project** closes the popup and entering a fresh conversation resets scroll. All **33 tests pass**, and the final TypeScript/production build passes.
- Browser checks covered the 1440 × 900 three-column desktop layout, 390 × 844 mobile layout and the normal 870 × 612 preview. No horizontal overflow was observed; Plus context remained minimal, the mobile sidebar closed before the popup opened, Escape worked, and the short-screen popup fit without internal scrolling after refinement. Temporary viewport overrides were reset.

Saved local QA artifacts: `output/design/frontend-workspace-refined-v1.png` and `output/design/frontend-recruiter-refined-v2.png`. Earlier screenshots remain as before-state references. The first popup draft needed unnecessary scrolling on the short screen; removing repeated copy and tightening that height breakpoint fixed it. No backend, retention, citation or access-control changes; no provider calls or deployment were performed.
