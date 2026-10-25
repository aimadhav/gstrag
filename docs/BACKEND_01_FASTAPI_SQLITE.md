# Backend milestone 01: a small API and persistent review workflow

Completed: 21 October 2026. **114 tests pass**, including 37 new API/state tests. A separate real localhost HTTP smoke test passes using the actual 149-record corpus and five registered PDFs.

Historical milestone: [Pinecone was subsequently added](BACKEND_02_PINECONE.md), bringing the suite to 149 tests. This guide describes the original BM25/manual-draft stage; the local `.env` now selects Pinecone. Gemini remains unbuilt.

Later update: [Gemini private drafting is now implemented and offline-tested](BACKEND_03_GEMINI_DRAFTS.md), with a no-key manual fallback and 207 tests. Live Google generation is not verified. Earlier stage counts and behavior below remain historical.

This step turns the earlier offline retrieval experiment into a local application backend. It does **not** generate Gemini answers yet. An administrator currently writes the draft or final answer manually.

## Explain it to a beginner

Previously, a script retrieved passages and printed a report. There was no signed-in user, inbox, saved pending question, or approval step.

Now a user submits a question to the API and immediately gets a query ID. Think of it as a ticket number. A small background worker checks the permitted sources and saves its evidence privately. The user can check the ticket's status, but cannot read the internal evidence or an unapproved draft.

An admin opens the review record, inspects source passages and PDF pages, writes a draft, and explicitly approves it. Only then does the user get the answer and plain source/page citations. The same API also supports refusal and clarification requests.

SQLite is the project's local notebook for accounts, tickets, drafts, decisions, and approved answers. A signed token identifies who is calling. It is not permission to read every ticket or PDF.

## Before and after

| Capability | Before | Now |
|---|---|---|
| Identity | Scripts supplied `--plan` | Signed login token identifies a stored account |
| Plan enforcement | Tested source filter in an experiment | Every new query uses the account's current database plan |
| Queries | JSON benchmark rows | Persistent SQLite records with owner checks |
| Async work | None in the application | `202` acknowledgement, persisted queue, worker, polling |
| Review | Safe status projection only | Private evidence/drafts plus explicit admin decisions |
| Citations | Offline provenance | Approved source names/pages; PDF endpoint is admin-only |
| Downgrade | Library filtering tests | Old approved answers stay readable; fresh evidence uses current access |
| Retention | Agreed requirement | Expiry checks and explicit 30-day purge maintenance |
| Follow-ups | Planned | Owned parent/conversation links, with no automatic answer replay |
| Generated drafts | Not implemented | Still not implemented: manual drafting is explicit |

## The flow that actually runs

```text
User logs in -> short-lived signed bearer token
  -> POST /queries
  -> SQLite queued row; HTTP 202 with query ID
  -> one local worker claims the row using the current DB plan
  -> missing topic/date? save a clarification request
  -> otherwise filter permitted sources, rank books, check notifications
  -> persist private evidence; mark pending_review
  -> user polls GET /queries/{id}: status only

Admin opens /admin/queries/{id}
  -> reads passages and protected PDF/page references
  -> optionally saves a private draft
  -> approves / edits and approves / refuses / requests clarification
  -> approved text + plain citations become visible to the owning user
```

No external queue, scheduler, Redis, microservices, or payment system is involved. The default retriever is free, local BM25. Jina mode is optional and explicitly configured.

## Start locally

Run from the repository root with the previously prepared experiment artifacts available:

```powershell
uv sync --locked
uv run python scripts/prepare_api_corpus.py
uv run python -m gst_rag.manage init-admin --username admin
uv run uvicorn gst_rag.api:create_app --factory --host 127.0.0.1 --port 8000
```

The bootstrap command asks for a password privately and asks you to confirm it. Minimum length is 12 characters. It creates only the **first** administrator; it does not overwrite an existing admin. There is no default password, public signup, or auto-created permanent demo account.

Open [local interactive API docs](http://127.0.0.1:8000/docs). Use `POST /auth/token` with the JSON username/password, copy its access token into the **Authorize** bearer-token dialog, and call the admin routes. Clear/switch the token when testing a normal user. Never put a token in a PDF URL or paste real credentials into a report.

The local app is intended for **one Uvicorn process and one worker owner**. Do not start multiple workers or several instances sharing this database: startup recovery is deliberately a single-owner design. No server from the smoke test is left running.

### Create a normal account

As admin, call `POST /admin/users` with a chosen username, password, and `plan=plus` or `plan=pro`. The role is always `user`; the request cannot create an administrator. Then sign in as that user and submit:

```json
{
  "question": "Which loaded notification conditions apply to pencil sharpeners?",
  "as_of": "2023-03-01",
  "topic_ids": ["pencil_sharpeners"]
}
```

The server generates the query ID and associates it with the authenticated account. Do not send a user ID, plan, namespace list, role, or context budget in this request; extra fields are rejected.

Topics currently are `renewable_energy`, `pencil_sharpeners`, or `other_gst`. The last option explicitly means the small notification sample may not cover the topic. Missing topic/date produces a clarification request without making a retrieval/provider call. This is structured input, not an implemented Gemini classifier.

### Review and publish

1. Admin calls `GET /admin/reviews` and opens a query.
2. The private record includes question, date, topics, conversation/parent IDs, revision, retrieval plan, evidence, and protected source links.
3. Save a draft with `PUT /admin/queries/{id}/draft`, supplying the current `revision` and `draft_text`.
4. Submit the new revision to `POST /admin/queries/{id}/decision`.

Supported decisions:

| Action | Required input | Public result |
|---|---|---|
| `approve` | Existing saved draft and query-local citation IDs | Approved draft |
| `edit_and_approve` | Explicit final text and query-local citation IDs | Edited and approved answer |
| `refuse` | Explicit safe public message | Safe refusal |
| `request_clarification` | Explicit public question/message | Clarification request |

Citation IDs such as `S1` are local to that query's evidence packet. The backend resolves them to source names/types/pages; the admin cannot supply arbitrary source metadata through the decision request. The owning user's ordinary `GET /queries/{id}` then returns the published outcome.

Approval checks that citations exist in that query's permitted evidence. It does not prove every sentence is legally supported. In this milestone, the human reviewer is responsible for that judgment. Public answer bodies are plain text: URL and Markdown link syntax are rejected; source names/pages are separate fields.

## Why a current database plan, not just the JWT plan?

JWTs are signed but can remain valid after a subscription changes. A token issued while an account is Pro still contains its Pro snapshot after an admin downgrades the account.

The API validates the token's signature, issuer, audience, and expiry, then loads the current account from SQLite. Current database role/plan controls the request. A browser cannot elevate access by editing its JSON or a token claim.

The admin changes a plan using `PATCH /admin/users/{user_id}/plan`. The worker checks the plan again when it claims a job. If the plan changes during retrieval, the old result is discarded and the job is requeued. If a Pro result is already awaiting approval when a downgrade occurs, publishing it returns `409 access_changed_reprocess_required`. The admin can reprocess it, which clears the old packet and draft and retrieves under the current plan.

This is intentional: **an existing approved historical answer may remain readable, but a new answer must not be published using stale Pro evidence**.

## Ownership and private/public separation

- Regular query lookups filter by both query ID and authenticated owner ID. A different user gets `404`, not another user's answer.
- Follow-up parent IDs must belong to the same user and must not be expired.
- Only admins can create accounts, change plans, inspect the review queue, save drafts, decide reviews, or download registered PDFs.
- Public query responses contain no private packet, draft, evidence excerpts, internal candidate links, source filesystem paths, or PDF URLs.
- Approved citations contain only citation ID, source name, source type, and page list.
- Request-validation responses omit raw input, so a rejected password is not echoed by the validator.
- Provider/retrieval failures become private `retrieval_unavailable` review records. Raw error bodies or keys are not returned to users. With no evidence, approval cannot proceed; refusal or reprocessing remains possible.

Separate public/admin Pydantic response models help prevent an accidental `return whole_database_row` from exposing the draft. Tests also check the actual JSON, not only the model declarations.

"Private" here means protected by the API's authentication/authorization boundary. SQLite evidence and drafts are not encrypted at rest; anyone with access to the database file can inspect them. Protect local files and do not expose this demo directly to the internet.

Passwords are stored using Argon2 hashes, not plaintext. Tokens use an explicitly configured HS256 algorithm and expire after 30 minutes. This follows the basic approach in the [FastAPI security guide](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) and [PyJWT usage documentation](https://pyjwt.readthedocs.io/en/stable/usage.html). Login is a simple JSON endpoint with HTTP bearer authentication, not a claim that a complete OAuth authorization server has been built.

`GST_JWT_SECRET` can supply a random signing secret of at least 32 bytes. If blank, a local random key is created in ignored `data/app/jwt.key` and reused after restart. Do not share that file or commit it. This demo relies on the local user's filesystem permissions; it is not hardened secret management.

## Admin-only PDF endpoint

The corpus snapshot registers five PDFs by document ID, source type, path, checksum, and page count. The supplied firm PDF is copied into ignored `data/sources/firm/`; its original in Downloads is not moved or modified. The ICAI and notification originals remain unchanged.

`GET /admin/sources/{document_id}/pdf` accepts a registered ID, not a client-supplied filesystem path. The resolved file must stay under `data/sources/`, and its checksum must match the registered evidence. Changed files require re-ingestion rather than silently serving a different PDF for an old citation.

The download sends `Cache-Control: no-store`. Admin evidence links include `#page=...`; an eventual admin UI must fetch the PDF using an Authorization header before opening a viewer. A bare browser navigation does not magically carry the bearer token, and putting credentials in query parameters is not supported. No browser PDF viewer was built in this step.

There is no upload/replacement endpoint yet. This API serves only the audited, registered corpus snapshot. Admin-only upload, replacement/versioning, and automatic re-indexing are future work.

## SQLite and queue design

Three small tables are sufficient:

| Table | Purpose |
|---|---|
| `users` | Username, password hash, admin/user role, Plus/Pro plan, active flag |
| `queries` | Owner, conversation/parent, question/date/topics, status, revision, private evidence/draft, approved answer/citations, expiry |
| `review_events` | Admin actor, action, timestamp, selected citation IDs; removed with expired query |

Each database operation uses its own short-lived connection. SQL values are parameterized. WAL mode and short write transactions fit this local workload.

Claiming a queued row uses `BEGIN IMMEDIATE`, so two claim attempts cannot both take that row. Finishing a job checks state, revision, expiry, and current plan before saving results. Human review actions also require the current revision; stale tabs or duplicate decisions return `409` instead of overwriting a published outcome.

Queued and pending records survive restart. A single worker's interrupted `processing` records are reset to `queued` on startup. This is restart recovery, not an exactly-once distributed processing guarantee. An interrupted provider call could be repeated. There are no leases, multi-process coordination, or automatic retry/backoff policies; these are deliberate prototype limits.

## Follow-ups and the downgrade boundary

New questions can specify `parent_query_id`. They inherit the conversation ID, with no fixed turn-count limit. Lists are paginated, not limited to one response forever. Each new question must still supply its own date/topic, and its source permissions use the current plan.

The retrieval call currently receives **only the new question**, not previous approved answers, drafts, or source excerpts. That prevents old Pro content from silently becoming Plus retrieval evidence after downgrade. Old approved answers remain accessible to the original owner within retention, including their plain source citations.

This is storage/ownership support for follow-ups, not automatic conversational understanding. A vague "what about that?" is not rewritten by an LLM yet. Gemini-based clarification/question rewriting is a later step, and it must preserve this downgrade boundary.

## Thirty-day retention

- Queued, pending, and draft records expire 30 days after submission unless a review decision renews their retention.
- An approved answer's 30-day window starts at approval. Refusal/clarification outcomes get 30 days from that decision.
- Expired queries are excluded from lists; their owning user receives `410` for direct access, with no content.
- Purge maintenance removes expired query rows, private packets, drafts, answers, and attached review events. It does not remove accounts or source PDFs.
- If an expired parent is purged while a newer child still exists, the child's parent ID is set to null; its conversation ID remains.

Inspect first:

```powershell
uv run python -m gst_rag.manage purge-expired
```

Only when you intend to delete those expired query records:

```powershell
uv run python -m gst_rag.manage purge-expired --apply
```

The second operation is permanent SQLite deletion, not a trash action. It was tested only against temporary test data here; it was not run against a persistent user database. The API enforces expiry on reads even if this maintenance command has not been run. No recurring purge automation has been created.

This purge covers SQLite query data, not local provider embedding caches. In optional Jina mode, hashed query-vector cache entries can remain until separately removed. The default BM25 HTTP smoke makes no provider calls or new query-vector cache. A public deployment would need a defined cache-retention policy as well.

## What was actually verified

The 37 new API tests cover login, invalid/unsigned/expired tokens, password-error redaction, admin boundaries, extra-field rejection, query ownership, hidden drafts, approval/refusal/clarification, citation checks, duplicate/stale decisions, plan changes before/during/after retrieval, historical visibility, follow-ups without answer replay, expiry/purge, restart recovery, PDF path/checksum restrictions, and request bounds.

The existing 77 ingestion/retrieval tests still pass: **114 tests total**.

`scripts/smoke_api.py` additionally starts an actual Uvicorn server on an ephemeral localhost port and uses HTTP—not only an in-process mock client. It creates temporary accounts and a temporary SQLite database, then:

1. Logs in and submits a Pro query against the real corpus.
2. Confirms real firm-book and notification evidence reaches admin review.
3. Confirms PDF downloads are admin-only and public pending responses hide evidence.
4. Saves a private draft and explicitly approves it with a real source citation.
5. Downgrades the account while retaining its original token.
6. Confirms the old approved answer remains readable, but the new Plus follow-up has no firm evidence or firm candidate links.

All 13 recorded HTTP checks pass. The approved text in this smoke test is explicitly **synthetic workflow text, not a GST conclusion**. The server stops afterward and temporary accounts/database are removed. No permanent demo account or plaintext password is written to the report.

Measured poll-to-review time was 25.687 seconds for the first cold retrieval and 0.141 seconds for the warmed follow-up. The first includes tokenizer/import initialization. These are one local observation, not latency benchmarks, not HTTP acceptance latency, and not human-review completion time. The smoke used BM25 with **zero provider calls**; Jina-backed HTTP retrieval was not exercised in that run.

The saved report is `data/app/api_smoke.json`. The app corpus contains 149 records: Plus can retrieve 19 ICAI/notification records; Pro can retrieve all 149. Its five PDFs are source-whitelisted, not publicly mounted static files.

## Reproduce the checks

```powershell
uv run python -m unittest discover -s tests -v
uv run python scripts/smoke_api.py
uv run python scripts/verify_structure_repair.py --require-retrieval
uv run python scripts/verify_notification_experiment.py --require-dense
```

The smoke requires the prepared local corpus and tokenizer cache, but makes no embedding/generation calls. The earlier benchmark source snapshots, questions, scores, and originals are not modified. Runtime dependencies and the development HTTP test client are recorded in `pyproject.toml`/`uv.lock`.

## Files added

- `src/gst_rag/api.py`: routes, auth dependencies, public/admin projection, validation-error redaction, protected PDF downloads.
- `src/gst_rag/auth.py`: Argon2 helper, local settings/signing key, signed-token encoding/validation.
- `src/gst_rag/models.py`: strict request schemas and separate response models.
- `src/gst_rag/store.py`: SQLite schema, queue/review state transitions, ownership and expiry checks, maintenance.
- `src/gst_rag/service.py`: audited-corpus loader, real retrieval/update-check adapter, local worker.
- `src/gst_rag/manage.py`: first-admin setup and explicit retention maintenance.
- `scripts/prepare_api_corpus.py`: application snapshot and app-owned source registration.
- `scripts/smoke_api.py`, `tests/test_api.py`: real HTTP smoke and deterministic temporary-DB tests.

## Interview answer

"I moved the RAG experiment behind a small authenticated FastAPI service with SQLite-backed queries and review states. A user only sees status until an admin explicitly approves an answer. I separated public and private response models, enforced ownership on object reads, served PDFs only through an admin endpoint, and checked the current database plan instead of trusting a stale Pro token. I also tested downgrade races: pending evidence must be reprocessed, while already approved historical answers remain readable. I used a single local worker rather than adding a broker before the demo needed one."

If asked whether it is production-ready, answer **no**: no TLS/public deployment setup, rate limiting, reset/refresh/logout lifecycle, distributed queue, comprehensive legal corpus, or security certification. If asked whether AI drafts are implemented, also answer **no**: current manual drafting is the foundation for that next feature.

## Next step

Add Gemini behind the existing private-draft boundary. It should receive only permitted evidence, return structured source IDs, and never publish directly. Keep risk/citation failures pending review; validate citation existence separately from actual claim support. Add the required Gemini key locally rather than pasting it into chat. React screens, NeMo integration, Pinecone, and admin PDF replacement remain separate later steps.
