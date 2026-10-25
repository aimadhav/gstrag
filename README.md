# GST document assistant

A fresh start for a resume project demonstrating document parsing, retrieval evaluation, cited answers, and a small full-stack application.

Latest upload milestone (25 October): [admin PDF upload and non-destructive replacement](docs/BACKEND_07_PDF_UPLOADS.md) now supports all three source labels, bounded/hash-checked binary transfer, background Docling staging, book-parse review and the existing explicit prepare/verify/activate release gates. Replacements retire old retrieval chunks but retain historical PDFs/citation identities. **67 frontend tests, 360 Python tests and the production build pass.** Browser QA uses a disposable synthetic PDF and real Docling/FastAPI/SQLite; no real source was approved or published. No new live provider verification, deployment or enabled schedule is claimed.

Earlier admin-frontend milestone: [the admin overview, source review, corpus publication and import controls](docs/FRONTEND_02_ADMIN_WORKSPACE.md) added the administration screens alongside human answer review, manual plans and the protected library. Its original 57-frontend/333-Python verification is retained in that milestone's guide.

Earlier scheduling milestone: [durable hosted sync jobs and an opt-in GitHub Actions workflow](docs/BACKEND_06_HOSTED_SYNC.md) are implemented. The scheduler client triggers a narrowly authenticated API, deduplicates retries and polls a persistent single-worker import job. Configure backend/repository settings after choosing hosting; the real `.env` was not edited.

Earlier publication milestone: [authenticated notification-source review and controlled corpus publication](docs/BACKEND_05_SOURCE_PUBLICATION.md) are implemented as backend APIs plus an explicit verification/indexing CLI. Synthetic workflows verify source approval, snapshot preparation, full fake-Pinecone verification, activation and worker refresh. No real notification was approved or published. The later admin-frontend milestone now supplies the source-review/publication screens.

Earlier ingestion milestone: [official discovery, versioned downloads and private Docling staging](docs/BACKEND_04_NOTIFICATION_SYNC.md) are implemented. Two partial GST Council adapters were live-checked; one official PDF was downloaded and remains awaiting metadata review. See the [overall plan](docs/NOTIFICATION_SYNC_PLAN.md); individual state feeds are deferred. This is not a complete/current GST feed.

Earlier frontend milestone: **React/TypeScript frontend implemented from a ChatGPT-generated design reference.** Research workspace/history, private admin review, explicit approvals, account/plan controls and a protected source library connect to the existing API. A clearly labelled sample preview works without a backend/key. Customer context is minimal; **Recruiter?** remains an outline for a future walkthrough. That milestone passed **33 frontend tests and the production build**. See [original setup and findings](docs/FRONTEND_01_REACT.md) and the [new admin workspace](docs/FRONTEND_02_ADMIN_WORKSPACE.md).

Earlier application milestone: **Gemini private drafting implemented without a live key; 207 tests passed at that stage.** Structured claims, citation/quote checks, mandatory approval and downgrade-safe draft storage are tested with a fake provider. Real HTTP smokes pass 15 checks with fake generation and 14 without a key; no live Gemini call or answer-quality measurement has been made. See [configuration and privacy defaults](docs/BACKEND_03_GEMINI_DRAFTS.md). Retrieval/manual review continue without a key.

Earlier application milestone: **Pinecone connected: 149 vectors in three source namespaces**, with backend-enforced Plus/Pro access. The suite had 149 tests at that stage, and the live Pinecone HTTP workflow passed 13 checks. On 12 development questions the top-10 sets match local search; ordering matches 10/12, and strict score equivalence fails (reported, not hidden). Budgeted evidence remains complete on 7/7 labeled cases. See [setup and measured findings](docs/BACKEND_02_PINECONE.md).

Earlier application milestone: **FastAPI + SQLite backend implemented; 114 tests passed at that stage.** Signed login, manual plans, owner-isolated queries, a persistent local queue, private drafts/evidence, explicit admin decisions, protected PDF downloads, downgrade-safe follow-ups, and 30-day expiry are working. See [backend setup and workflow](docs/BACKEND_01_FASTAPI_SQLITE.md).

Earlier retrieval milestone: **notification ingestion and deterministic update checks** (77 tests at that stage). Three official PDFs were parsed and reviewed; four selected clause chunks cover two topics. All 12 supplied date/status scenarios pass. Jina retains complete evidence on 7/7 labeled questions, while a separate update check excludes not-yet-effective notifications. Topic IDs are supplied and the amendment corpus is incomplete. See [the notification experiment and beginner explanation](docs/EXPERIMENT_05_NOTIFICATIONS.md).

Earlier ingestion milestone: **known defects are repaired on the two audited layouts** (47 tests at that stage). ICAI running headers, ambiguous integer headings, a reading-order error, and footnote ownership are fixed using conservative cleanup plus a source-bound reviewed outline. All 98 ICAI source references have the expected parent; the firm-book chunk content/ownership is unchanged. See [the beginner-friendly before/after report](docs/EXPERIMENT_04_STRUCTURE_REPAIR.md).

Hybrid retains complete labeled context on 13/13 answerable ICAI development questions; hierarchical improves from 12/13 to 13/13, while fixed declines from 10/13 to 9/13. These are development retrieval checks, not chatbot accuracy. The earlier [frozen firm-book comparison](docs/EXPERIMENT_02_REPAIRS.md) remains preserved with its original source snapshot. The old pdfplumber experiment is archived under `.archive/` and is not used by this implementation.

## Proposed stack

- Docling: parse PDFs into structured document content and provenance.
- Jina: embed questions and passages.
- Pinecone: retrieve permitted passages from three source namespaces.
- Gemini: generate answers using retrieved evidence.
- FastAPI, SQLite, React: a small backend, stored chat/review states, and user/admin screens.

FastAPI, SQLite, Pinecone and React are implemented. The Gemini adapter is implemented and mock-tested, not live-verified. The code defaults to local BM25; `GST_RETRIEVER=jina` uses local cosine search and `GST_RETRIEVER=pinecone` uses hosted search. Both dense modes use Jina embeddings. This machine's ignored `.env` selects Pinecone; first index the corpus as described in the [Pinecone guide](docs/BACKEND_02_PINECONE.md). Gemini needs `GEMINI_API_KEY`; firm excerpts additionally require the explicit privacy opt-in explained in the [drafting guide](docs/BACKEND_03_GEMINI_DRAFTS.md).

## Open the frontend

```powershell
# Repository root; uses installed Node 22.12+ or the bundled Node 24 runtime.
.\scripts\frontend.ps1 -Action dev
```

Open `http://127.0.0.1:5173/` and choose **Preview workspace** or **Admin preview** for isolated sample data. Real sign-in needs the backend below and an admin-created account. Run `-Action build` to build the UI; the backend then serves it at `/app/`. See [frontend setup and fixture instructions](docs/FRONTEND_01_REACT.md). On another machine with a suitable Node, use `npm ci` and `npm run dev` inside `frontend/`.

## Start the local API

```powershell
uv sync --locked
uv run python scripts/prepare_api_corpus.py
uv run python -m gst_rag.manage init-admin --username admin
uv run uvicorn gst_rag.api:create_app --factory --host 127.0.0.1 --port 8000
```

Choose your administrator password in the hidden prompt. There are no default credentials. Use one server process, then open [local API docs](http://127.0.0.1:8000/docs). The [backend guide](docs/BACKEND_01_FASTAPI_SQLITE.md) explains login, normal-user creation, polling and approval. The first corpus preparation requires the earlier local source/parse artifacts.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from this repository:

```powershell
uv sync --locked --python 3.12
uv run gst-rag parse "C:\path\to\your-book.pdf" --source-type firm_book --output data/processed/my_document
uv run gst-rag chunk data/processed/my_document
```

The first parse downloads Docling's local models. Parsing and chunking run on CPU without a paid API. The input is a text-based PDF by default; use `--ocr` for a scanned PDF. The processed directory must be distinct for each document or source type.

The three variants are fixed-size with overlap, Docling HierarchicalChunker, and Docling HybridChunker. Parents use reviewed boundaries when supplied, otherwise explicitly numbered subsections, including trailing-dot numbering. Ambiguous integer-number restarts require an explicit `--outline-review`; they are not guessed. All variants use the same filtered source, Markdown table format, and Jina-v3 tokenizer. Parent expansion is a separate experiment. Optional `--picture-transcriptions` accepts a reviewed, checksum-bound source supplement; this prototype does not automatically understand arbitrary diagrams or arbitrary document outlines.

## Benchmark

Keep your Jina key in the ignored `.env` file, following `.env.example`. The supplied book, its extracted text, evidence labels, embeddings, and full result files remain in ignored `data/`. They are not redistributed in this repository.

For the completed local experiment, use these validation commands:

```powershell
uv run python -m unittest discover -s tests -v
uv run python scripts/verify_notification_experiment.py --require-dense
uv run python scripts/verify_structure_repair.py --require-retrieval
uv run python scripts/validate_experiment.py --directory data/processed/chapter7_repaired
uv run python scripts/validate_experiment.py --directory data/processed/chapter7_repaired --questions data/benchmark/chapter7_source_regressions.json
uv run python scripts/verify_source_audit.py --directory data/processed/chapter7_repaired --require-ready --require-regressions
```

The original experiment remains in `data/processed/chapter7/`; the repaired frozen experiment is in `data/processed/chapter7_repaired/`. Do not rebuild into either historical/frozen directory. Start a new directory for future experiments. The default benchmark split is `dev`. Held-out scoring requires a matching freeze and refuses an existing held-out result.

The complete assistant PDF audit produced separate `chapter7_questions.source_audited_v2.json` labels. To rescore the saved development results offline and check the known defects:

```powershell
uv run python scripts/rescore_source_audit.py
uv run python scripts/verify_source_audit.py --require-ready
```

This older readiness command inspects the original, unrepaired artifacts, so it still fails as expected. The repaired-directory command above passes and verifies the completed held-out result against the unchanged freeze and archived original code. Current code has since evolved; the execution guard still rejects changed code for held-out scoring. Audited source labels are not independent legal review, and a passing check does not establish generated-answer accuracy.

For a new development comparison after building your own document and evidence labels:

```powershell
uv run gst-rag benchmark data/processed/my_document data/benchmark/my_questions.json --retriever jina --output-tag main
```

Labels need `annotation_status` of `source_audited` or `reviewed`; `--allow-draft-labels` is reserved for diagnostics. Use `--retriever bm25` for keyword diagnostics, not as a substitute for the dense comparison. Different question sets should use different `--output-tag` values.

To use another document, create its own source-quote labels and document fingerprint. Do not reuse chapter-seven evidence for a different PDF. The dataset format is explained in [the experiment protocol](docs/EXPERIMENT_01.md).

## Notes and current boundaries

- [Actual results, protocol, and limitations](docs/EXPERIMENT_01.md)
- [Repairs, frozen evaluation, and current results](docs/EXPERIMENT_02_REPAIRS.md)
- [ICAI selected-page pipeline test](docs/EXPERIMENT_03_ICAI.md)
- [ICAI parent repair: beginner explanation, code, before/after](docs/EXPERIMENT_04_STRUCTURE_REPAIR.md)
- [Notification ingestion, date checks, and token-budget fix](docs/EXPERIMENT_05_NOTIFICATIONS.md)
- [FastAPI/SQLite backend: setup, flow, tests and interview explanation](docs/BACKEND_01_FASTAPI_SQLITE.md)
- [Pinecone storage, namespace access and measured parity limits](docs/BACKEND_02_PINECONE.md)
- [Gemini private drafts, no-key setup, citation checks and offline tests](docs/BACKEND_03_GEMINI_DRAFTS.md)
- [React frontend: design reference, setup, browser checks and interview notes](docs/FRONTEND_01_REACT.md)
- [Complete source audit and fix verification](docs/SOURCE_AUDIT.md)
- [Technical interview explanations](docs/INTERVIEW_NOTES.md)
- [Project scope](docs/PROJECT_BRIEF.md)

The corpus includes the 45-page firm-book chapter, a ten-page ICAI topic slice, and selected provisions from three historical notifications. Original, repaired frozen, ICAI, and notification development results are kept separately. Notification review and topic labels are explicit; no automatic legal-update understanding is claimed. Authentication, persistent review, Pinecone retrieval, an offline-tested Gemini adapter and React user/admin screens are implemented. Manual review remains available without a key. Live Gemini answer validation, automatic question classification/conversational rewriting, NeMo and admin upload/replacement remain unbuilt/unverified. No public deployment or production-readiness claim is made.
