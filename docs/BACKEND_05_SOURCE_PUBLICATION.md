# Notification source review and controlled publication

Implemented 25 October 2026. This is a **backend/API milestone** following the notification downloader/staging work. A new React ingestion-review screen and the hosted/GitHub scheduling trigger are not included.

Later follow-up: [hosted sync jobs and the opt-in GitHub workflow](BACKEND_06_HOSTED_SYNC.md) are now implemented and offline-tested. Deployment/enablement and the new React source-review screen remain pending. Counts below describe this publication milestone, not the newer suite.

The real downloaded notification has **not** been approved, indexed or activated by the assistant. Source approval remains an authenticated admin action. Verification described below uses synthetic local fixtures and fake provider transports, not a new live cloud publication.

## Explain it to a beginner

The importer puts PDFs into an incoming tray. This step adds a way for an admin to check a document and move selected, supported content onto the chatbot's bookshelf.

There are three separate permissions/decisions:

1. **Source review:** an admin checks what the notification is, its dates, relevant topics and complete clauses.
2. **Publication:** a prepared collection is verified, then explicitly activated for retrieval.
3. **Answer review:** an admin still checks a drafted answer before a customer sees it.

Approving a source does not approve any answer or establish that it overrides a book. `chain_complete` stays false, supersession is not automatically established, and the existing mandatory notification/date lane still requires review.

## Before and after

| Before | After |
|---|---|
| Parsed drafts could only wait in staging | An authenticated admin can inspect source items/PDF, approve anchored metadata or reject it |
| Generic chunks had unknown dates | Approved records carry source-anchored issue/effective dates and reviewed topics |
| No controlled route into the answer corpus | Prepare a candidate, verify it, then explicitly activate it |
| A naïve vector append would miss the app's corpus fingerprint | Verification covers the whole new snapshot, including existing book vectors |
| A running worker cached its original corpus | The real worker detects an activated corpus between queued jobs and rebuilds retrieval |

The importer still does not publish automatically. Existing source PDFs, approved answers and frozen experimental files are not deleted or rewritten.

## Admin API workflow

Use the existing username/password login and bearer JWT. These endpoints recheck the current database user's admin role. Pro membership alone is insufficient. The reviewer identity comes from authentication, never a request field.

The existing FastAPI `/docs` screen can operate this workflow while the React source-review screen remains unbuilt. See the main README for starting the API and creating a local administrator. No new default account or password was created for this milestone.

| Operation | Endpoint |
|---|---|
| List staged versions, statuses and review revisions | `GET /admin/ingestion/notifications?limit=50&offset=0` |
| Inspect source items, page references, draft chunks and saved review | `GET /admin/ingestion/notifications/{version_id}` |
| View the exact staged PDF, authenticated and `no-store` | `GET /admin/ingestion/notifications/{version_id}/pdf` |
| Approve source metadata and selected complete clauses | `PUT /admin/ingestion/notifications/{version_id}/review` |
| Reject the staged source with a reason | `POST /admin/ingestion/notifications/{version_id}/reject` |
| Get the active corpus digest/fingerprint/counts | `GET /admin/ingestion/corpus` |
| Prepare a candidate without changing the active corpus | `POST /admin/ingestion/publications` |
| List publication/verification/activation state | `GET /admin/ingestion/publications` |
| Explicitly activate a verified publication | `POST /admin/ingestion/publications/{publication_id}/activate` |

### 1. Inspect and review

Read the original PDF, not just its draft chunk. The detail endpoint provides the current `revision`, `stage_sha256` and original Docling `items`. Use those source references, page positions and actual quotes in a `NotificationReview` request.

The request contains:

- The expected review revision (initially zero) and staging SHA-256.
- An explicit issue date and a single effective date.
- An optional canonical amendment target such as `central_tax_rate:1/2017` or `central_tax:1/2017`.
- Anchors for identity, issue date, effective date and amendment target when present. Each anchor has `source_ref`, `pages` and an exact source-contained `quote`.
- Selected clauses: a stable ID, subject, one of the three currently supported topic IDs, complete source-item references, provisions, an operative-change description and an explicit completeness confirmation.
- `source_checked: true`; each clause requires `complete_clause_confirmed: true`.

These confirmations are human attestations, not machine proof of legal correctness. Quote checks demonstrate source containment/page attribution, not that a conclusion logically follows. Dates are checked against explicit date quotes; we do not infer a missing effective date from the issue date.

The server rebuilds approved records from the **complete selected source items plus identity/date/target anchors**, not arbitrary submitted answer text or unchecked staged chunks. Each resulting record is limited to 512 tokenizer tokens. An oversized complete clause is rejected, never silently truncated. Review a safe clause breakdown rather than cut off its conditions.

Approval is bound to the exact PDF, staging checksum, Docling checksum and authenticated reviewer. Optimistic revisions prevent one reviewer from overwriting another's newer decision. Changed/stale/corrupt artifacts must be reviewed again. A rejected source cannot be prepared for publication.

### 2. Prepare a candidate

Read `GET /admin/ingestion/corpus`, then submit its `base_sha256` and the approved version IDs:

```json
{
  "version_ids": ["<approved-version-id>"],
  "base_sha256": "<digest-returned-by-the-active-corpus-endpoint>"
}
```

Placeholders above are not valid identifiers. The endpoint returns a publication ID and `state: prepared`.

Preparation verifies registered PDFs and source policies, copies the approved PDF into app source storage, adds the reviewed records and recomputes **candidate** explicit-number book links. It saves the exact previous active bytes as a backup and a separate candidate bundle. The active `data/app/corpus.json` is unchanged.

Book links distinguish Central Tax from Central Tax (Rate). They remain `candidate_pending_admin_review`; an explicit number match is not a legal-precedence determination.

### 3. Verify/index, dry run first

Indexing is a trusted local-operator command, not a publicly callable provider-writing API. Source review still requires an authenticated admin; there is no source-approval CLI shortcut.

```powershell
# Dry run: validate the prepared snapshot without provider calls or activation.
.\.venv\Scripts\python.exe -m gst_rag.notification_publication index <publication-id> --mode pinecone

# Explicit provider work: uses the existing owned index, never creates/deletes one.
# Requires backend Jina/Pinecone configuration and may consume provider quota.
.\.venv\Scripts\python.exe -m gst_rag.notification_publication index <publication-id> --mode pinecone --apply
```

For a deliberately BM25-configured local demo, `--mode bm25 --apply` verifies locally without embedding/vector APIs. `--mode jina` verifies local dense embeddings. **Do not use BM25 verification to activate a Pinecone-configured backend:** activation enforces the backend's actual retriever mode and index name.

Changing the corpus changes its snapshot fingerprint and vector IDs. Pinecone verification therefore upserts the **whole candidate snapshot**, using cached Jina embeddings where available, and fetches every expected vector to check metadata and values. It does not create a new index, change billing settings, delete old vectors or mutate experimental caches. For dense modes a checksummed local embedding copy is retained for activation verification. Provider errors are reduced to safe error codes, not raw key-bearing error bodies.

A failed verification leaves the prior corpus active. Review changes after preparation invalidate that candidate. Publication also rejects a changed active base before provider writes.

### 4. Activate explicitly

After verification, post to the activation endpoint:

```json
{
  "base_sha256": "<the-original-base-digest-used-for-preparation>",
  "confirm": true
}
```

Activation rechecks reviewer/source checksums, the candidate and backup, current retriever/index configuration and the active base. Pinecone mode performs a fresh fetch-back verification against the retained embeddings. A missing/corrupt remote vector blocks the switch. Activation itself performs verification reads, not embedding creation or vector upserts.

Only after these checks does the backend atomically replace `corpus.json` with the verified in-memory candidate. It marks the publication active with the activator's authenticated identity; previously active publication rows become historical/superseded. Repeating an activation can reconcile an interruption after the file switch but before the registry acknowledgement. This is not a distributed transaction or a promise against arbitrary concurrent manual file editing.

The single query worker checks the corpus file digest between jobs. It recreates retrieval when the file changes and reads local evidence/Pinecone fingerprint from the same pinned bundle. An already-running query may finish with its earlier coherent snapshot. Later jobs use the new one. Old source PDFs remain registered/available, and existing stored answers are not regenerated.

The previous manifest is retained for recovery; an automatic rollback/retraction UI or CLI is not implemented. Do not manually restore a different retriever snapshot without verifying its index compatibility and source files.

## Persistent state

- Import/version states remain in `data/app/notification_sync/registry.sqlite3`; review and publication states use separate tables there. A version still being “staged” in the importer status is not a claim that its separate source review is pending.
- `source_reviews` stores the latest revision, authenticated actor, bound artifact checksums and derived approved records.
- `source_review_events` retains the decision history hashes/actors.
- `publications` tracks prepared, verified, verification-failed, active and superseded states.
- `data/app/publications/<publication-id>/base.json` retains the exact previous corpus.
- `corpus.json` in that directory is the candidate, and dense verification additionally saves `embeddings.json`.
- All these data directories are ignored by Git. Candidate bundles contain book text; never publish them as public CI artifacts. They are backend storage, not GitHub runner persistence.

The sync and review/publication operations share a local exclusive lock. This is a single-process/single-instance demo design, not a distributed deployment architecture.

## Current boundaries

- First-version review supports **Central Tax and Central Tax (Rate), ordinary notifications and one prospective effective date**. Retrospective effect, corrigenda and same-instrument PDF replacement/retraction need separate reviewed policies and are refused by this publisher for now. The downloader may retain them in staging.
- Existing published source metadata is frozen against silent edits/rejections. Changing an active source requires the future revision/retraction workflow; it must not pretend that editing a review instantly rewrites the active corpus.
- Only the existing three topic IDs are accepted. Automatic question/topic classification and comprehensive amendment-chain coverage are not added here.
- Source availability and quoted dates do not prove applicability, completeness, legal precedence or current law.
- Every generated answer still needs its existing explicit admin decision. Plus/Pro retrieval restrictions, downgrade history visibility and 30-day answer retention are unchanged.
- No real source approval, real Pinecone write, deployment, scheduled trigger or new React review screen was performed by this implementation turn.

## Verification and interview notes

Final result: **283/283 Python tests pass** (248 existing plus **35 new**), using `python -m unittest discover -s tests`. The pre-existing FastAPI/Starlette test-client deprecation warning remains. No new frontend files were changed; its last verification remains 33 tests and a successful production build.

The new tests exercise authenticated role boundaries, actor spoofing, stale revisions/checksums, false dates/targets, quote/page mismatches, missing clause provenance, unsupported retrospective effects, completeness attestations, token-budget refusal, source rejection and immutable active reviews.

Publication tests cover unchanged active data during preparation, exact backup preservation, idempotent preparation, stale bases, changed reviews/candidate/backup, mode mismatches, provider failure, a full fake-Pinecone snapshot upload/fetch verification, missing-vector rejection at activation, explicit BM25 activation, both-plan notification availability, Pro-only firm evidence, service snapshot coherence and worker refresh. A synthetic real-HTTP `TestClient` workflow logs in by JWT, reviews, prepares, verifies and activates; it creates no public answer.

An initial fixture used identical book text for ICAI and the firm. A test incorrectly expected both texts in Pro's context, but the existing context builder correctly deduplicated them. The fixture now uses distinct synthetic book texts; the real retrieval policy and frozen benchmarks were not changed to satisfy the assertion.

**Explain the design in an interview:** “I separated document ingestion, source approval, corpus deployment and answer approval. I bound metadata to original source checksums and page-level evidence, then treated corpus updates as verified snapshots. A failed index update cannot replace the active collection, and a worker detects a completed activation before its next job.”

**Do not claim:** that checkbox/quote validation proves legal truth, that the government feed is complete/current, or that this is production-grade distributed publication. Cloud verification of a newly approved real source still requires an actual admin decision and an explicit provider run.

## Next step

Add the authenticated hosted notification-sync job trigger/status path and GitHub Actions workflow once the deployment target is known. The CLI importer and source-publication backend now provide the underlying local operations. A small React source-review panel can follow without changing their authorization rules.
