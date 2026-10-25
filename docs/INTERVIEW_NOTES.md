# Interview notes for the implemented experiment

## What currently works?

"I converted a 45-page GST chapter with Docling, compared chunking methods with Jina, repaired source structure and completed a frozen retrieval comparison. The FastAPI/SQLite backend uses Pinecone namespaces, private drafts, citation checks and mandatory review. React/TypeScript now covers researcher conversations, human answer review, access management, incoming source review, publication and import monitoring. I checked the built admin screens against actual FastAPI/SQLite using disposable synthetic sources, including explicit source approval, local BM25 verification/activation and researcher viewing of an approved answer. The bounded government importer had an earlier live PDF check. A durable queue and opt-in GitHub scheduler are implemented, but not deployed/enabled. No real new notification was approved or cloud-published. There are 333 Python tests and 57 frontend tests. Gemini's adapter is mock-tested, not live-verified."

See [admin frontend decisions, beginner examples and browser findings](FRONTEND_02_ADMIN_WORKSPACE.md). Admin upload/replacement remains the next main feature; the recruiter-popup walkthrough is still deferred.

## How does scheduled ingestion work?

"GitHub is just the alarm clock. A dedicated credential can enqueue a bounded import and check status, not read books or publish content. SQLite persists the job; a single backend worker runs the importer on durable storage. A stable idempotency key handles lost responses, a unique active-job constraint prevents overlapping triggers, and an OS-released worker lock protects recovery. Execution is at-least-once after crashes, with version hashes preventing duplicate source versions. Completion means private staging, not current-law coverage or approval. I tested the client-to-staging flow with synthetic sources; a real hosted run remains to be verified."

See [the hosted sync guide](BACKEND_06_HOSTED_SYNC.md) for the beginner explanation, changed code, setup and limitations.

## Why Docling?

"The book has headings, tables, author notes, and page-based references. I needed structured source elements and provenance for both chunking and citations. I retained the original conversion so I could inspect errors instead of treating the parser output as perfect."

## What did you have to correct?

"Docling's headings needed structural depth restoration, and my first regex missed terminal dots on two section numbers. A regression test demonstrated the error, then I used one numbering helper for both depth and parent selection and checked actual rebuilt ownership. I also added a manually reviewed source supplement for a missing image-only diagram, preserving its original picture/page reference. That is a specific repair, not a general diagram extraction system."

## What does hybrid chunking mean here?

"It starts from Docling's document structure, splits oversized content by token budget, and merges small compatible peers. It is not embedding-distance semantic splitting and it is unrelated to the term hybrid search, which combines retrieval signals."

## Why keep hierarchical as a separate method?

"It isolates structure-preserving element chunks from token-aware merging and splitting. Some elements are tiny and some exceed 512 tokens. That changes specificity and how much supporting context accompanies a match."

## How did you make the comparison fair?

"Every variant uses the same filtered parse, table serialization, heading-prefix format, tokenizer, embedding model, queries, and exact cosine search. I report both top-K evidence retrieval and coverage under a fixed context budget. The units are not identical sizes; that is a characteristic of the methods, so I measured it rather than ignoring it."

## Why did you benchmark Jina locally before adding Pinecone?

"Jina provides the embeddings. On this small corpus I can rank every vector directly with cosine similarity, which removes hosted search as a variable in the chunking experiment. I then added Pinecone to the application with three namespaces and compared it against those same vectors. All 12 development top-10 sets matched, but order matched 10/12 and a strict numerical score check failed. Budgeted evidence remained complete on 7/7 labeled questions. I do not claim exact numerical equivalence or a speed improvement."

See [Pinecone implementation and findings](BACKEND_02_PINECONE.md) for the preserved failed check, costs, access tests and beginner examples.

## How do you know a result contains the needed evidence?

"The labels refer to original source item IDs and short exact excerpts. An excerpt must actually appear in the retrieved text. Using only a shared item ID would overcount success when different chunks contain different parts of the same paragraph or table. Multiple required evidence groups must all be covered for a complete retrieval."

## What do the results show?

"On the repaired pipeline, evidence recall at five on 18 answerable development questions was 97.22% for fixed windows, 87.50% for hierarchical, and 100% for hybrid. Hybrid and hierarchical covered all six targeted regression questions; fixed missed the diagram question. The frozen held-out comparison was a coverage tie: all three covered all nine answerable questions. One unsupported question was excluded. This is a small source-close retrieval benchmark, not chatbot accuracy or proof of universal hybrid superiority."

## Did parent-child retrieval help?

"Not on this initial set: hybrid child-only retrieval already covered all labeled evidence within the context budget. Parent expansion matched that coverage and used slightly more context. Naive neighboring-context expansion reduced coverage by consuming budget before another required passage was included. The result supports keeping expansion optional and evaluating harder questions."

## What happens if a parent is too large?

"The current policy includes the full parent only if it fits the remaining context budget. Otherwise it keeps the matching child. I avoid taking only the beginning of a long parent and losing the passage that caused the match. A more selective parent window would be another experiment, not an implemented feature."

## What do access labels enforce today?

"The source filter runs before ranking and during context assembly. In the local API, authentication identifies the user and the current database plan controls new retrieval. Admin-only PDF endpoints, owner-isolated queries, and downgrade handling are tested. Old approved answers remain readable, but are not replayed into new retrieval context. The CLI experiment remains a separate operator-controlled benchmark, not an authentication boundary."

## What are the limitations of citations?

"Each chunk has source item references and PDF pages, but an excerpt split from a multi-page item may inherit the broader item page span. I have not implemented printed-page mapping or claim-level citation entailment. Source provenance is necessary but does not prove an answer is correct."

## What would you improve next?

"The source experiments, notification controls, hosted retrieval, local review backend, mock-tested Gemini adapter and React screens are implemented. Next I would add admin PDF replacement/ingestion, then question classification and safe conversation rewriting. With a suitable key/account I would verify one live draft and evaluate actual answer support on new development questions rather than tune against the already scored held-out set."

## How do you know the audit fixes worked?

"The heading test failed before the change and passes afterward. Actual artifact checks verify parent membership, not just parent names. For the diagram I compared its transcription with the image, kept its picture/page provenance, checked all prior refs were retained, and asked a retrieval question about both branches. Those original 21 repair tests and the readiness check passed; the suite has since grown to 114. The original artifact directory still exhibits the old defects, preserving a baseline."

## What stopped you from tuning on the test set?

"I froze source artifacts, labels, settings, and implementation hashes before the held-out run. The command rejects changed inputs or an existing held-out result. I reported the tie rather than changing settings afterward. The annotations were assistant-authored and source-audited, not independently expert-labeled, so the benchmark still has limits."

## What changed when you added a second publisher's PDF?

"Docling labeled repeated page headers as section headings, and ICAI's local integer numbering differed from the firm book's multipart numbering. I added a position/repetition furniture check and a PDF/parse-checksum-bound reviewed outline for the ambiguous layout. I also checked reading order and footnote ownership. All 98 ICAI canonical references have their expected owner, and firm-book chunk content is unchanged. This is not fully automatic structure inference."

## Did that improve all the benchmark results?

"No. On the same 13 answerable ICAI development questions, complete context improved from 12 to 13 cases for hierarchical, stayed at 13 for hybrid, and dropped from 10 to 9 for fixed windows. Neighbor expansion also got worse. That shows why I test structure and budgeted retrieval separately. These are development evidence checks, not independent answer-accuracy results."

The full before/after examples, exact code changes, limits, and 47-test verification are in [Experiment 04](EXPERIMENT_04_STRUCTURE_REPAIR.md).

## Why isn't top-K retrieval enough for notifications?

"Similarity does not enforce an effective date or guarantee that a related amendment is included. I added a separate metadata lane using supplied topic/date inputs. On seven evidence-labeled development cases Jina context was already complete, but ordinary retrieval included not-yet-effective notifications in five date scenarios. The checked lane excluded them and kept complete conditions. This demonstrates date-selection controls, not improved embeddings or automatic legal reasoning."

## How did you preserve notification conditions and trustworthy citations?

"I grouped the relevant insertion and continuation even when a table spanned two PDF pages, retained the original item/page anchors, and matched evidence by document ID plus item reference plus quoted span. Source references restart in each PDF, so an unqualified item ID can cite the wrong document. I also keep central-tax component rates distinct from combined GST conclusions."

## What engineering bug did integration testing uncover?

"One keyword run exceeded the 2,048-token context cap by one token. A prefix cut using the full passage's offsets tokenized differently when encoded on its own. I now recount the actual prefix and move the cut back until it fits. A deterministic regression reproduces that behavior, and both the original diagnostic and corrected runs are saved."

## Is human review implemented?

"Yes: queued queries, private evidence/drafts, explicit approval, edited approval, refusal and clarification are persisted in SQLite. The React review inbox lets an admin inspect evidence, edit/save a draft, choose citations and explicitly confirm publication. User screens hide pending drafts and PDF links. Gemini's adapter is implemented but only fake-provider workflows have been tested so far; manual drafting works without a key. Citation-span checks are not legal validation."

See [Experiment 05](EXPERIMENT_05_NOTIFICATIONS.md) for the exact scope, source PDFs, 77-test verification, costs, and reproduction commands.

## Why check the database if the JWT already has a plan?

"A valid token can outlive a downgrade. I authenticate the token but read the current account role/plan for each request and again when a worker claims a query. A plan change during retrieval discards the old result; a pending Pro result cannot be approved after downgrade without reprocessing. An already approved historical answer remains readable for its retention window, but is never automatically replayed as new Plus evidence."

## How is the asynchronous workflow kept simple?

"POST returns 202 with a persisted query ID, and the client polls. One local worker claims SQLite rows with a short transaction. State/revision checks prevent duplicate claims or stale review overwrites; interrupted processing is requeued on restart. This is a single-process demo, not an exactly-once distributed queue."

The [backend guide](BACKEND_01_FASTAPI_SQLITE.md) contains endpoint examples, a real HTTP smoke, 114-test verification, security/retention boundaries, and setup instructions.

## Can you honestly claim Gemini is integrated without a key?

"The provider adapter, schema, validation, worker/storage integration and review API are implemented and tested offline. I cannot claim Google accepted a live request or that generated GST answers are accurate. A fake provider separates workflow correctness from model quality, and a mocked HTTP transport checks the intended request shape."

## Do exact supporting quotations prove the answer is correct?

"No. They catch unknown source IDs and invented quoted spans. A real quotation can still be attached to an unsupported conclusion. One test deliberately demonstrates that gap. Every draft remains private until an admin checks the meaning and approves it."

See [the Gemini guide](BACKEND_03_GEMINI_DRAFTS.md) for setup, no-key behavior, privacy opt-in, before/after examples, code changes and the 58 new tests.

## Current resume wording (updated)

Admin upload/replacement is now implemented too. The [upload guide](BACKEND_07_PDF_UPLOADS.md) explains reservation versus transfer, hash-bound review, single-host asynchronous parsing and non-destructive replacement with examples. The milestone passes 360 Python tests, 67 frontend tests and the production build; a synthetic browser workflow uses real Docling and local BM25 publication, not live provider indexing.

**Why don't you overwrite a PDF in place?** "Because an older approved answer may cite its page and source identity. I prepare a new snapshot without the old chunks, retain the original PDF as archived and switch new retrieval only after verification and explicit activation. Retaining a PDF is separate from permitting new retrieval."

**Is upload parsing generic and fully automatic?** "No. Docling and HybridChunker create private drafts with heading/page/item provenance. Unknown outlines, diagrams and layout errors need human inspection; the audited chapter-specific repairs aren't blindly applied to arbitrary books. Oversized or wrong-page chunks cannot be approved."

"Built a Docling/Jina GST RAG project with Pinecone source namespaces, a FastAPI/SQLite review backend and responsive React/TypeScript researcher/admin UI, featuring server-enforced access, private drafts, explicit approvals and downgrade-safe history."

The [frontend guide](FRONTEND_01_REACT.md) documents design-to-code work, sample-versus-real mode, in-memory tokens, actual browser/API checks, and the mobile CSS defects found after component tests passed. The Gemini provider remains mock-tested, not live-verified.

If reporting a metric, state the denominator and scope: complete labeled retrieval evidence on 9/9 answerable held-out questions from one chapter, with the unsupported question excluded. All three methods achieved that coverage. Do not turn this into a claim of 100% chatbot accuracy. Original, audited, and repaired results are versioned separately; an assistant audit is not independent expert/legal validation.
