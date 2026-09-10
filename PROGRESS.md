# GST RAG implementation record

Last updated: 2026-09-09

## Completed

- [x] Repository structure and README
- [x] Local `uv` virtual environment
- [x] FastAPI health and demo chat endpoints
- [x] Backend-controlled Admin/Plus/Pro source policy
- [x] Citation validation and risk/review decisions
- [x] Supabase/pgvector schema draft
- [x] CBIC notification discovery stub
- [x] Minimal Next.js chat page
- [x] Provider-independent tests: 4 passing

## In progress

- [x] Authentication and provider configuration scaffolding (development adapter)
- [ ] Persistent document/chat/review repository interfaces
- [x] Supabase setup documentation and initial RLS policies

## Deliberately paused for user review

- [ ] PDF ingestion pipeline
- [ ] Docling parsing choices
- [ ] Cleaning rules
- [ ] Chunk size, overlap, and section strategy
- [ ] Embedding model and vector dimensions
- [ ] Retrieval ranking/filtering refinements

## Next checkpoint

Before implementing ingestion or changing retrieval behavior, confirm:

1. Preferred Supabase project setup and authentication approach.
2. PDF types you expect (text PDFs, scanned PDFs, tables/OCR).
3. Your preferred chunking and retrieval rules.
