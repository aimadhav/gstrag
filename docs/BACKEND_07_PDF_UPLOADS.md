# Admin PDF uploads and non-destructive replacement

Implemented 25 October 2026. This extends the existing FastAPI/SQLite ingestion registry, publication gates and React admin workspace. It is a single-host résumé-project implementation, not a managed document platform.

Verification: **360 Python tests and 67 frontend tests pass**, with a successful production build/type check. This adds 27 Python and 10 frontend tests to the prior milestone.

## Explain it to a beginner

Uploading a PDF is like leaving a new edition in the librarian's incoming tray. It must not immediately change what the chatbot reads.

The flow is:

```text
Admin selects original PDF + source label + optional replacement target
  -> browser calculates the file's SHA-256 fingerprint
  -> backend reserves a private upload identity
  -> browser sends the exact PDF bytes
  -> backend checks size, fingerprint and PDF structure
  -> local worker runs Docling and creates private draft chunks
  -> admin compares the parse with the original PDF
  -> explicit source approval
  -> prepare candidate corpus
  -> explicit backend verification/index command
  -> explicit activation
  -> new questions use the new corpus
```

For example, suppose an old firm book contains chunk A and a replacement contains chunk B. Uploading or approving B does not remove A. After the candidate containing B passes verification and the admin activates it, new retrieval uses B. The original PDF for A is retained under its original identity, so an admin can still inspect citations from an older approved answer. An administrative replacement is **not** a declaration that the old law has been repealed.

Answer approval remains a separate human decision. No customer sees an unapproved answer, private source review or PDF download link.

## What changed, and why?

Before this milestone, the notification importer could download/stage government PDFs, and the admin could review sources and publish snapshots. There was no working browser upload/replacement route for books. The library deliberately did not pretend to offer one.

Now **PDF uploads** accepts `icai_book`, `firm_book` and `notification`. The source library opens this form with a selected replacement target. The publication desk also accepts approved uploaded books, not just notifications.

| Decision | Reason / alternative |
|---|---|
| JSON reservation, then raw `application/pdf` PUT | Metadata and exact bytes are separately validated. Avoids base64 overhead and a multipart dependency. This is a bounded, whole-file transfer, not resumable streaming storage. |
| SHA-256-bound reservation and generated paths | A retry of the same file/settings reuses its reservation; a changed file cannot silently satisfy it. Client filenames never become server paths. |
| Persisted SQLite status + one local thread | Parsing survives browser navigation and interrupted work can be requeued on restart. Celery/Redis is unnecessary for this demo. |
| Original PDF + immutable parse/review hashes | A review is about particular bytes and provenance, not just a friendly document title. |
| New snapshot for replacement | Old chunks are removed from the candidate's retrieval records, while old PDFs and citation identities remain registered. No physical overwrite or vector deletion is needed. |
| Explicit indexing command | Prevents a browser click from silently spending API credits or mutating Pinecone. Existing dry-run and verification gates are reused. |

`pypdf` is added for structural validation (locked to 6.21.2 for this milestone). **Docling remains the parser**; this does not restore the archived pdfplumber pipeline.

## Parsing and review policy

- Text-based PDFs only in this UI: up to **25 MiB and 500 pages**. No OCR option, encrypted PDFs or active/embedded content.
- Book parsing uses existing conservative furniture filtering and Docling `HybridChunker`, with a 512-token Jina-v3 tokenizer budget. Heading context, original PDF page positions and Docling item references are retained.
- All original pages must be converted successfully. Empty/no-searchable-content conversions fail privately.
- The original Docling artifact remains available; removed furniture candidates are shown for review.
- The UI does **not** force case title/facts/issue/ruling/opinion fields.
- Unknown book layouts do not automatically inherit the audited ICAI outline or the earlier firm-book diagram supplements. They require admin inspection. This upload path does not claim generic parent/child reconstruction or automatic diagram understanding.
- A book approval requires an explanatory note, original/source-type check and structure/completeness check. Oversized chunks, missing/incorrect page provenance or an unsafe plan label block approval rather than silently dropping content.
- There is no browser chunk/outline repair editor. A failed-quality parse must be corrected in the ingestion implementation or a separately audited source workflow; clicking retry alone does not repair deterministic layout defects.
- Rejection requires a reason, not false positive checkboxes. The original PDF is retained.
- Notifications use the existing, separate identity/date/complete-clause review. Series, number and year are explicitly entered before upload and checked against source anchors during review. Filenames are not treated as reliable legal metadata.

Source policy remains server-controlled: `firm_book` is Pro-only; ICAI and notifications are Plus/Pro. A replacement must retain its source type. The same PDF fingerprint cannot be relabelled across source types in the registered or staged corpus. Uploaded notification replacements must also retain the notification's reviewed identity; a genuinely new notification is a new source, not a silent replacement.

## States and failure behavior

```text
awaiting_upload -> uploaded_queued -> parsing
                                    |-> pending_source_metadata_review
                                    |-> upload_parse_failed -> explicit retry
```

Review status (`approved` / `rejected`) is stored separately. Approval does not activate the source. Reviewed artifacts are initially private; only the separate publication path can make their records available to retrieval.

The upload worker has a lifetime lock. Parsing, importer writes and publication mutations share the existing ingestion lock; a long conversion may temporarily prevent another mutation. This deliberate single-host simplification is not a distributed job queue. Upload parsing marked interrupted at restart is requeued; a failed parse requires explicit retry. Raw parser exceptions and local paths are not returned to users.

PDF checks are structural safeguards, **not malware scanning, authenticity verification or an adversarial parsing sandbox**. Trust is still placed in the administrator. Rate limiting, isolated resource-bounded parsing and object storage are not implemented.

## API and files

All routes require a currently authorized admin account, including after a role change:

| Route | Purpose |
|---|---|
| `POST /admin/uploads` | Validate metadata, reserve upload |
| `PUT /admin/uploads/{id}/pdf` | Receive bounded, hash-matching raw PDF |
| `GET /admin/uploads` / `GET /admin/uploads/{id}` | Safe status/history |
| `GET /admin/uploads/{id}/detail` | Integrity-checked staged chunks and source items |
| `GET /admin/uploads/{id}/pdf` | Authenticated staged original PDF |
| `POST /admin/uploads/{id}/retry` | Requeue a failed private parse |
| `PUT /admin/uploads/{id}/review` | Revision-bound book approval/rejection |

Uploaded notifications instead use the existing `/admin/ingestion/notifications/{id}/review` route and its quote/date validation. PDF responses are protected and marked `no-store`; customer projections do not gain source download links.

Main changes:

- `src/gst_rag/uploads.py`: transfer validation, private staging, book review, worker/recovery.
- `models.py`, `auth.py`, `api.py`: strict payloads, worker setting and admin-only endpoints.
- `notification_publication.py`: generic source policy and non-destructive replacement in prepared snapshots.
- `notification_sync.py`: importer staging excludes browser-upload jobs, leaving their specialized worker responsible.
- `frontend/src/UploadDesk.tsx`: upload/retry/review UI and explicit confirmations.
- `api.ts`, `types.ts`, `App.tsx`, `AdminIngestion.tsx`, `sampleUploads.ts`, `admin.css`: client transport, library/publication integration, isolated samples and responsive layout.

Private upload files live under `data/app/notification_sync/`; prepared source PDFs are registered under `data/sources/books/` or `data/sources/notifications/`. Old registered PDFs remain present after replacement. Registered-PDF totals can therefore grow even when the number of active retrieval records does not.

## Run it locally

```powershell
uv sync --locked
./scripts/frontend.ps1 build
uv run uvicorn gst_rag.api:create_app --factory --host 127.0.0.1 --port 8000
```

Use one backend process and an initialized application corpus/admin account, as described in the earlier backend guide. `GST_UPLOAD_WORKER_ENABLED=true` is the default for local environment settings and is shown in `.env.example`; the real `.env` was not changed. Constructed test settings keep it off unless explicitly enabled.

Docling needs its local model assets; a first conversion may download them and take substantially longer. The Jina-v3 **tokenizer** must be cached locally; parsing does not request hosted embeddings. A missing tokenizer/model or bad conversion leaves the source private and retryable.

In **PDF uploads**, choose the label/target, upload, inspect and approve. Then open **Corpus publications**, prepare the reviewed version and use the command displayed there. The verification CLI supports `bm25`, `jina` and `pinecone`; real provider modes need their normal keys and may incur costs. Dry run first, then explicitly add `--apply`. Activate only after verification succeeds.

For a disposable demonstration, without touching the real corpus:

```powershell
.venv/Scripts/python.exe scripts/run_admin_fixture.py --port 8011 --real-upload-parser
```

The fixture prints its temporary root, public test credentials and a synthetic upload PDF. With this flag only uploaded PDFs use real Docling; seeded notification items remain constructed fixtures. Default fixture mode uses a fake upload parser for quick UI checks. Both are labelled synthetic and are not GST/legal evidence. If verifying a fixture publication, always supply **that exact temporary root** to the CLI; never run its snapshot ID against the real root.

## Verification and honest limits

- Backend tests cover validation, permissions, source-policy binding, hashes, retries/recovery, provenance/token-budget approval gates, notification review, explicit publication, stale targets and old-PDF preservation.
- Frontend tests cover binary transport/reservation, actual controls, replacement type locking, private status, review confirmation/rejection and failures. jsdom cannot validate its mocked uploaded FileList like Chromium; component tests submit that form event directly while retaining the real required-file field. Native browser submission is checked separately.
- A repeated frontend run exposed a 5-second timeout in an existing long source-review test. Its helper now simulates pasting the three prepared text fields instead of triggering a render for every typed character; assertions and the real approval gates are unchanged. The final full run passes without increasing the timeout.
- Browser QA uses real FastAPI/auth/SQLite with a disposable synthetic PDF: native file selection/upload, real Docling conversion, staged review, protected original download, candidate preparation, local BM25 verification and explicit activation. No real book/notification is approved during this QA.
- The fixture replacement finishes with **2 active records / 3 registered PDFs**, zero old-firm-book retrieval chunks, an archived original PDF and Pro-only new firm chunks. Both preparation and verification leave the previous active corpus unchanged; only explicit activation switches it.
- The embedded PDF viewer may be blank in the in-app browser; its authenticated **Download PDF** fallback works. The downloaded synthetic original was compared byte-for-byte with the upload.
- Browser checks at the default desktop viewport and a 390×844 mobile viewport show the upload form and working mobile admin navigation; the mobile document has no horizontal overflow. The real Plus account has no admin/upload navigation. The temporary viewport override is reset afterward.
- This is workflow/provenance testing, not a new chunking benchmark or a claim that arbitrary PDFs ingest perfectly.
- Existing live Jina/Pinecone results remain historical checks. This milestone makes **no new live provider or Gemini-quality claim**, enables no hosted schedule and performs no deployment.

The real `data/app/corpus.json` retains SHA-256 `83a8245e8a93738c900655e55db0a96abb57d1e7e7b416c83d14a7e105b5fec3`; no real publication directory was created. Synthetic UI screenshots are saved under `output/admin-workspace/` locally, not evidence of real-source legal approval.

## Interview answers

**Why not embed immediately after upload?** A valid PDF can still have poor reading order, wrong headings or incomplete legal conditions. I stage and inspect it before a separate release gate.

**What happens if the browser closes?** Once the bytes are received, status and the PDF are durable in SQLite/local storage. Parsing continues in the backend; the browser polls when reopened. An incomplete transfer can be retried against the same reservation; I did not build a resumable upload protocol.

**How do replacements avoid breaking citations?** I remove the old source's chunks from a new candidate snapshot, archive its registry entry and keep the old PDF ID. New retrieval and historical citation resolution are separate concerns.

**Does preserving old PDFs leak Pro content?** No: protected routes still require admin access, and new retrieval still uses current plan/source filters. Retaining an already approved answer after downgrade does not authorize reusing its firm-book evidence in a new Plus answer.

**What would you improve for production?** Isolate parsers with resource limits, use durable object storage and a real worker queue, then measure unknown-layout extraction quality. Those are future steps, not capabilities claimed by this demo.
