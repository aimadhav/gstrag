# Fresh project brief

Restarted on 19 October 2026. This brief supersedes the archived prototype and earlier implementation claims.

## What we are building

A GST assistant that answers from a small document corpus, shows source/page references, restricts retrieval by Plus/Pro access, and queues high-risk drafts for admin review. The project should demonstrate RAG engineering decisions through a working application and reproducible experiments.

It is a resume project for AI/ML, GenAI, backend, and full-stack roles. There is no fixed deadline. Prefer free services where practical, with a small API budget. The developer knows APIs and app development; accompanying notes should explain retrieval decisions deeply.

Current application status (25 October): [React user/admin screens](FRONTEND_01_REACT.md) now include an [admin overview, notification source-review form/inspector, publication desk and import controls](FRONTEND_02_ADMIN_WORKSPACE.md). They extend the live-tested Pinecone/FastAPI/SQLite foundation and offline-tested Gemini adapter. [Notification sync](BACKEND_04_NOTIFICATION_SYNC.md) provides partial official discovery, versioned downloads and private Docling staging, including a bounded live PDF check. [Source review/publication](BACKEND_05_SOURCE_PUBLICATION.md) and [hosted sync jobs/opt-in GitHub workflow](BACKEND_06_HOSTED_SYNC.md) provide the controlled backend paths. All 333 Python tests and 57 frontend tests pass, plus the production build. Browser checks exercised the new built UI against disposable synthetic source/answer/publication/import workflows with local BM25 verification. No deployment, enabled schedule, real staged-source approval, new live cloud publication, live Gemini request or answer-quality claim is made. Earlier milestone entries below are historical snapshots. Admin PDF upload/replacement, question classification, conversational rewriting and NeMo remain unbuilt.

## Decisions carried forward from the user

- Only admins upload or replace PDFs.
- Plus: ICAI books and notifications. Pro: those sources plus the firm book.
- Plans are assigned manually.
- Keep customer context minimal: no Included sources catalogue or provider details; preserve approved answer citations. A small Recruiter? popup exists, but its full technical walkthrough is deferred until project completion.
- English; follow-up questions supported.
- All high-risk answers require asynchronous admin review.
- Users see source names and page references; PDF links are admin-only.
- Old approved answers remain readable after downgrade within the answer-retention period. New questions use current access.
- Answers are retained for 30 days. Source documents remain the maintained corpus.
- Preserve case discussions in source order. Do not force facts/issue/ruling extraction.
- Keep the architecture small and document each completed feature.
- Added 25 October: scheduled discovery/download/ingestion of official central-government GST notification PDFs; individual state feeds later. The user intends to host the app separately; GitHub Actions triggers a durable backend job rather than keeping app data on a temporary runner. See the [notification sync plan](NOTIFICATION_SYNC_PLAN.md). Discovery/download/staging, the source-review/publication backend, hosted jobs and an opt-in workflow are implemented. No real new source has been activated and scheduling is not enabled. Hosting remains to be chosen; the proposed daily 07:17 Asia/Kolkata time is configurable and not yet confirmed.

## Why Docling

The previous prototype used pdfplumber to get a quick text extraction result. That substituted a tool without explaining the departure from the agreed design, then accumulated chapter-specific heuristics. We are replacing that experiment with the original Docling-first approach.

Docling's document representation can retain document elements, hierarchy, layout locations, and provenance, including a separation of body content from headers/footers. These are relevant to GST headings, tables, and source-page citations. They are capabilities to evaluate on our corpus, not a guarantee that every heading or table will be parsed correctly. [Official document model](https://docling-project.github.io/docling/concepts/docling_document/)

Parsing and chunking are different steps. Parsing reconstructs document elements; chunking groups those elements into passages for retrieval. Docling's hierarchical chunker attaches document context to detected elements. Its hybrid chunker adds token-aware splitting and optional merging to hierarchical chunks. This is not the same as embedding-similarity semantic splitting. [Official chunking explanation](https://docling-project.github.io/docling/concepts/chunking/)

## Build order

### Milestone 1: Inspect a real Docling conversion

Set up an isolated Python environment, record actual dependency versions, and convert the supplied firm-book PDF. Save the structured Docling JSON and readable Markdown. Inspect headings, reading order, real tables versus bordered notes, TOC continuation, and source-page provenance against representative PDF pages.

Save conversion settings and elapsed time. Note missing/incorrect elements explicitly. Keep the original document and parsed text local. The setup may download parsing models; no paid model API is required for this milestone.

Completion evidence: one reproducible command, actual conversion artifacts, and a short report showing what was verified and what failed. Do not claim a general parser based on success on one chapter.

### Milestone 2: Compare chunking on the same parsed document

Compare three variants: a fixed-size baseline, Docling HierarchicalChunker, and Docling HybridChunker. Use the same source content, tokenizer, and documented size settings. Preserve source item IDs and page provenance for all variants. Inspect definitions, conditions, exceptions, tables, and case discussions. No separate case field schema is required.

Then compare child-only, neighboring-context, and parent-context retrieval. Keep expansion distinct from splitting so improvements can be attributed correctly.

Completion evidence: actual chunks, configurations, and examples explaining the practical differences. Chunk counts alone do not establish which method retrieves better.

### Milestone 3: Measure retrieval

Write about 30 questions with manually checked source-page evidence. Start with this chapter, then add a permitted ICAI sample and a notification. Use the same Jina embedding model and search settings across chunk variants. Keep a held-out subset for final reporting.

Measure whether all required evidence is retrieved, how early the first useful passage ranks, and retrieval/context size and latency. Compare equal context budgets as well as top-K. Record required evidence as source spans, because chunk IDs differ across variants. Do not announce a winning method before measurement.

Completion evidence: reproducible runs, per-question results, a comparison report, and analysis of at least one failure.

### Milestone 4: Build cited answers

Connect retrieval to Gemini in one FastAPI app. Give the model identified source passages and require source IDs in its output. Resolve those IDs to document/page references in backend code. Return an insufficient-evidence result when the corpus cannot support the answer.

A source-ID check validates that a citation exists; it does not prove the claim follows from it. Review claim support and missed exceptions in the evaluation questions.

Use ICAI, firm-book, and notification namespaces chosen by server-side access rules. A metadata label by itself does not enforce access. For book updates, compare relevant provisions and effective dates in the loaded corpus; unresolved relationships enter review.

### Milestone 5: Add the demonstrable app flow

Build React chat and a basic admin screen backed by SQLite. Include manual Plus/Pro roles, admin PDF upload/viewing, approved answers, and a pending-review state. Polling is sufficient for asynchronous review.

Store high-risk drafts privately and show only approved content. Recheck the user's current role on new questions. Prevent old Pro content from becoming evidence through chat history after downgrade, while preserving historical answer visibility.

Use a few explicit review rules initially. NeMo Guardrails was in the original proposal; evaluate its role once the basic answer flow exists rather than adding it as an unexplained dependency. No payments, microservices, Kubernetes, or separate queue infrastructure are required for the demo.

## Documentation alongside implementation

After each milestone, record:

1. What now runs, with a command or demo.
2. Why this approach was selected and the alternative considered.
3. A concrete input/output example.
4. What was measured or manually checked.
5. What remains unimplemented or unreliable.
6. Interview questions and answers tied to that completed work.

All future resume claims must match implemented behavior and saved measurements. Experiment 01 preserves the initial parsing/chunking run. [Experiment 02](EXPERIMENT_02_REPAIRS.md) records the firm-book repairs, six targeted development questions, and frozen held-out comparison. [Experiment 03](EXPERIMENT_03_ICAI.md) is the ICAI pre-repair baseline; [Experiment 04](EXPERIMENT_04_STRUCTURE_REPAIR.md) records its parent-structure repair, both-book preservation checks, before/after retrieval results, and 47 passing tests at that stage. The ICAI repair includes a source-bound manual outline review, not generic automatic structure inference. The subsequent notification evaluation is recorded below; answer generation and the web app remain planned.

Update: [Experiment 05](EXPERIMENT_05_NOTIFICATIONS.md) completes that small notification sample: three fully parsed PDFs, four selected reviewed clause chunks, document-qualified evidence matching, a mandatory topic/date check, candidate book links, safe public status projection, and 77 passing tests. The sample has 12 supplied date/status scenarios and seven evidence questions, all covered by checked context; Jina ordinary context also covers all seven. It is not a complete law corpus or automatic topic/legal classifier. An integration-discovered prefix-retokenization budget bug is fixed with the initial runs preserved. Next: expose retrieval/review states in a small FastAPI/SQLite app, then integrate cited Gemini drafts and the user/admin UI.

Application update: [Backend milestone 01](BACKEND_01_FASTAPI_SQLITE.md) implements that FastAPI/SQLite foundation: signed login, current-DB manual plans, owner checks, persistent queued/pending states, private manual drafts, explicit review decisions, protected source downloads, downgrade handling, follow-up ownership, and 30-day expiry/purge. All 114 tests and a real localhost HTTP smoke pass. No permanent demo credentials were created. Gemini generation, conversational rewriting, React, Pinecone, and source upload/replacement remain planned. The next implementation is Gemini writing only to the private draft boundary.

Pinecone update (22 October): [Backend milestone 02](BACKEND_02_PINECONE.md) adds the hosted 149-vector sample in the three planned source namespaces, local source hydration/version checks, explicit indexing, 35 new offline tests and a successful 13-check live HTTP smoke. The same 12 development top-10 sets match local cosine; exact order matches 10/12 and strict numerical score parity fails, preserved in the findings. Complete evidence remains 7/7. This local `.env` selects Pinecone. No billing upgrade, deletion, Gemini generation, case schema, or React UI was added. Next is private Gemini drafts plus citation checks.

Drafting update (22 October): [Backend milestone 03](BACKEND_03_GEMINI_DRAFTS.md) adds the optional Google adapter, strict structured claims, source/quote checks, private generated drafts, pre/post-generation entitlement checks and a missing-key manual fallback. No source text was sent to Gemini. Firm content is blocked from generation by default pending explicit privacy opt-in. 58 new tests bring the suite to 207; 15 fake-generation HTTP checks and 14 no-key checks pass. Next: bounded live verification when a suitable key is available, or independent React user/admin screens.

Frontend update (23 October): a ChatGPT image was generated and shown first, then implemented as a local React/TypeScript UI. The [frontend guide](FRONTEND_01_REACT.md) records the exact scope, image reference, no-key preview, real-API fixture, 28 frontend tests, three additional backend static-boundary tests and mobile CSS before/after fixes. No hosting or real-account seed was performed. Next: connect an admin-only PDF replacement/ingestion workflow; live Gemini verification remains pending a key and suitable processing terms.

## Archive and inputs

Upload/replacement update (25 October): [Backend milestone 07](BACKEND_07_PDF_UPLOADS.md) adds admin-only binary PDF uploads for all three source labels, bounded/hash-bound private storage, a durable single-host parse worker, actual Docling/HybridChunker staging, book review and explicit replacement publication. Old retrieval chunks are retired only on activation; original PDF identities remain for historical citations. Unknown layouts require review and do not automatically inherit the audited chapter-specific outline/diagram repairs. The suite now has 360 Python and 67 frontend tests; the production build passes. Synthetic browser QA exercises real local Docling and the complete release flow; the real corpus is unchanged. Live Gemini verification, general conversational rewriting/classification, NeMo and hosting/scheduler enablement remain separate unfinished work.

The previous scripts, extracted JSON, renders, README, and notes are stored under `.archive/prototype-before-docling-2026-10-19/` for recovery only. The original files in Downloads and Desktop were not moved or edited. Git history was not reset.
