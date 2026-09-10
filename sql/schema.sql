create extension if not exists vector;

create type document_source as enum ('icai_book', 'private_book', 'notification');
create type document_status as enum ('processing', 'active', 'failed');

create table if not exists profiles (id uuid primary key references auth.users(id) on delete cascade, role text not null check (role in ('admin','plus','pro')) default 'plus');
create table if not exists documents (id uuid primary key default gen_random_uuid(), title text not null, source_type document_source not null, storage_path text not null, checksum text not null, publication_date date, effective_date date, document_number text, status document_status not null default 'processing', error_message text, created_at timestamptz not null default now());
create table if not exists chunks (id uuid primary key default gen_random_uuid(), document_id uuid not null references documents(id) on delete cascade, content text not null, embedding vector(1024), page_number int, section_path text[] not null default '{}', metadata jsonb not null default '{}');

create or replace function match_chunks(query_embedding vector(1024), permitted_sources document_source[], result_limit int default 5)
returns table (id uuid, document_id uuid, content text, page_number int, section_path text[], similarity float)
language sql stable as $$
  select c.id, c.document_id, c.content, c.page_number, c.section_path, 1 - (c.embedding <=> query_embedding) as similarity
  from chunks c join documents d on d.id = c.document_id
  where d.status = 'active' and d.source_type = any(permitted_sources)
  order by c.embedding <=> query_embedding limit result_limit;
$$;
