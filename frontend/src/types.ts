export type Plan = 'plus' | 'pro';
export type Role = 'user' | 'admin';
export interface User { id: string; username: string; role: Role; plan: Plan }
export type SourceType = 'icai_book' | 'firm_book' | 'notification';
export interface Citation { citation_id: string; source_name: string; source_type: SourceType; pages: number[] }
export interface Query {
  id: string; conversation_id: string; parent_query_id: string | null;
  question: string; as_of: string | null; topic_ids: string[]; status: string;
  message: string; answer: string | null; citations: Citation[];
  approval_kind: string | null; created_at: string; expires_at: string;
}
export interface Evidence extends Citation {
  document_id: string; source_refs: string[]; excerpt: string;
  truncated_for_budget?: boolean;
}
export interface Packet {
  citations?: Evidence[]; review_reasons?: string[]; generation?: string;
  current_law_verified?: boolean;
  generation_details?: { citation_ids?: string[] };
  generated_answer?: { clarification_question?: string; status?: string };
}
export interface AdminQuery {
  id: string; user_id: string; question: string; conversation_id: string;
  parent_query_id: string | null; as_of: string | null; topic_ids: string[];
  status: string; revision: number; plan_at_retrieval: Plan | null;
  draft_text: string | null; packet: Packet | null; expires_at: string;
}
export interface Source { document_id: string; name: string; source_type: SourceType; page_count: number; pdf_url: string; archived?: boolean; replaced_by?: string | null }
export interface Question { question: string; as_of: string; topic_ids: string[]; parent_query_id?: string }
export interface Decision {
  revision: number; action: 'approve' | 'edit_and_approve' | 'refuse' | 'request_clarification';
  text?: string; citation_ids: string[];
}
export interface Health { status: string; retriever: string; generation: string; notification_sync?: string }
export interface IncomingSource {
  id: string; identity: string; status: string; sha256: string; stage_sha256: string | null;
  error: string | null; revision: number; review_status: 'approved' | 'rejected' | null;
}
export interface SourceItem { source_ref: string; text: string; pages: number[]; label: string }
export interface SourceAnchor { source_ref: string; pages: number[]; quote: string }
export interface ReviewedClause {
  id: string; subject: string; topic_id: string; source_refs: string[]; provisions: string[];
  operative_change: string; complete_clause_confirmed: true;
}
export interface SourceReview {
  revision: number; stage_sha256: string; issued_on: string; effective_from: string; amends: string | null;
  source_checked: true;
  anchors: { identity: SourceAnchor; issued_on: SourceAnchor; effective_from: SourceAnchor; amends: SourceAnchor | null };
  clauses: ReviewedClause[];
}
export interface SourceDetail {
  version_id: string; candidate: { label: string; subject?: string; series: string; kind: string; number: number | null; year: number };
  source_sha256: string; stage_sha256: string; revision: number; review_status: string;
  review: { decision: string; payload?: SourceReview; reason?: string } | null;
  page_count: number; document_id: string; items: SourceItem[];
  draft_chunks: { text: string; token_count?: number; pages?: number[]; eligible_for_retrieval: boolean }[];
}
export interface SourceDecision { version_id: string; revision: number; status: string; answer_approval_performed: false }
export interface CorpusStatus { base_sha256: string; corpus_id: string; records: number; sources: number }
export interface Publication {
  id: string; state: string; mode: string | null; index_name: string | null; base_sha256: string;
  actor_id: string; created_at: string; activated_at: string | null; activated_by: string | null; error: string | null;
}
export interface SyncJob {
  id: string; status: string; created_at: string; started_at: string | null; finished_at: string | null;
  attempts: number; error: string | null;
  result: { downloaded_new_versions: number; unchanged_versions: number; staged_versions: number;
    deferred_documents: number; error_count: number; bounded_scan: boolean; coverage: string;
    active_corpus_changed: false; published: 0 } | null;
}
export interface SyncStatus { enabled: boolean; worker_ready: boolean; max_pages: number; max_documents: number; since_year: number; jobs: SyncJob[] }
export interface UploadSpec {
  title: string; source_type: SourceType; replaces_document_id: string | null;
  series?: 'central_tax' | 'central_tax_rate'; number?: number; year?: number;
}
export interface UploadedSource {
  id: string; title: string; source_type: SourceType; sha256: string; stage_sha256: string | null;
  status: string; error: string | null; byte_count: number; page_count: number | null;
  replaces_document_id: string | null; created_at: string; revision: number; review_status: string | null;
}
export interface UploadDetail extends UploadedSource {
  document_id: string; items: SourceItem[];
  draft_chunks: { chunk_id: string; text: string; embedding_text: string; headings: string[]; token_count: number;
    pages: number[]; source_refs: string[]; plan_required: Plan; eligible_for_retrieval: boolean }[];
  warnings: string[]; excluded_items: { ref: string; reason: string; pages: number[]; preview: string }[]; over_token_budget: number;
}
export interface BookDecision { revision: number; stage_sha256: string; action: 'approve' | 'reject'; reason: string; source_checked: boolean; structure_checked: boolean }
export interface Client {
  sample: boolean;
  login(username: string, password: string): Promise<User>;
  logout(): void;
  me(): Promise<User>;
  health(): Promise<Health>;
  queries(): Promise<Query[]>;
  submit(data: Question): Promise<Query>;
  reviews(): Promise<AdminQuery[]>;
  review(id: string): Promise<AdminQuery>;
  saveDraft(id: string, revision: number, text: string): Promise<AdminQuery>;
  decide(id: string, data: Decision): Promise<Query>;
  reprocess(id: string, revision: number): Promise<AdminQuery>;
  users(): Promise<User[]>;
  createUser(username: string, password: string, plan: Plan): Promise<User>;
  setPlan(id: string, plan: Plan): Promise<User>;
  sources(): Promise<Source[]>;
  pdf(id: string): Promise<Blob>;
  incomingSources(): Promise<IncomingSource[]>;
  sourceDetail(id: string): Promise<SourceDetail>;
  stagedPdf(id: string): Promise<Blob>;
  approveSource(id: string, data: SourceReview): Promise<SourceDecision>;
  rejectSource(id: string, revision: number, stage_sha256: string, reason: string): Promise<SourceDecision>;
  corpusStatus(): Promise<CorpusStatus>;
  publications(): Promise<Publication[]>;
  preparePublication(version_ids: string[], base_sha256: string): Promise<Publication>;
  activatePublication(id: string, base_sha256: string): Promise<{ state: string }>;
  syncStatus(): Promise<SyncStatus>;
  triggerSync(key: string): Promise<SyncJob>;
  uploads(): Promise<UploadedSource[]>;
  uploadFile(file: File, spec: UploadSpec): Promise<UploadedSource>;
  uploadDetail(id: string): Promise<UploadDetail>;
  uploadedPdf(id: string): Promise<Blob>;
  retryUpload(id: string): Promise<UploadedSource>;
  reviewBook(id: string, decision: BookDecision): Promise<SourceDecision>;
}
