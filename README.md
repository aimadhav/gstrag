# GST RAG Assistant

An interview-ready reference implementation of a role-aware GST document assistant.

## Architecture

`Admin upload -> parse/clean -> section-aware chunks -> embeddings -> pgvector`

`User question -> backend role policy -> filtered retrieval -> grounded answer -> citations/risk review`

The repository keeps provider integrations behind small adapters so the core policy and RAG logic can be tested locally.

## Quick start

```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
pytest
```

Copy `.env.example` to `.env` and add provider credentials for live integrations. Without credentials, the API still exposes health, policy, chunking, citation validation, and a deterministic demo chat path.

## Important security decision

The frontend never supplies permitted sources. `backend/policy.py` derives them from the authenticated profile, and `backend/retrieval.py` applies the source filter before vector search. A Plus user can never retrieve `private_book` chunks by changing a request payload.

## Layout

- `backend/`: FastAPI API and RAG domain logic
- `ingestion/`: parsing, cleaning, chunking, and ingestion orchestration
- `worker/`: official CBIC notification discovery
- `sql/`: Supabase/Postgres schema and filtered vector search function
- `frontend/`: minimal Next.js TypeScript UI
- `tests/`: provider-independent regression tests

This is an informational assistant, not legal advice. High-risk answers are routed to admin review.
