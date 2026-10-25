import type { AdminQuery, Client, Decision, Health, Plan, Query, Question, Source, User,
  IncomingSource, SourceDetail, SourceReview, SourceDecision, CorpusStatus, Publication, SyncJob, SyncStatus,
  UploadedSource, UploadDetail, UploadSpec, BookDecision } from './types';

export class ApiError extends Error {
  constructor(public status: number, public code: string) { super(code); }
}

const messages: Record<string, string> = {
  invalid_credentials: 'That username or password was not recognised.',
  invalid_or_expired_credentials: 'Your session has ended. Please sign in again.',
  query_expired: 'This answer has passed its 30-day retention window.',
  admin_required: 'This action requires an administrator account.',
  username_already_exists: 'That username is already in use.',
  review_state_or_revision_changed: 'This review changed in another session. Refresh before continuing.',
  access_changed_reprocess_required: 'The user’s plan changed. Reprocess this question before approval.',
  approval_requires_answer_and_citations: 'Add an answer and select its supporting sources.',
  citation_not_in_permitted_query_evidence: 'A selected citation is not available to this user. Reprocess the question.',
  inline_citations_must_be_in_approval_selection: 'Select every source referenced by an inline [S…] citation.',
  public_answer_must_not_contain_links: 'Remove URLs and PDF links from the public answer. They are admin-only.',
  registered_corpus_unavailable: 'Prepare the corpus before using the source library.',
  stale_source_review_revision: 'Another admin changed this source review. Reload it before continuing.',
  stale_stage_digest: 'The parsed source changed. Reload and check the original again.',
  stale_source_review_revision_or_stage: 'This source changed. Reload it before sending a decision.',
  active_corpus_changed: 'The active corpus changed. Refresh before preparing or activating a publication.',
  active_source_review_frozen_requires_revision_policy: 'This source is already active. Its review is frozen; replacement requires a separate revision workflow.',
  complete_reviewed_clause_exceeds_512_tokens: 'This complete clause exceeds 512 tokens with its anchors. Review the clause boundaries; do not silently drop conditions or exceptions.',
  review_anchor_not_on_claimed_source_page: 'An evidence quote does not match its selected source item and page.',
  review_date_not_supported: 'A date does not match its selected source quote.',
  review_date_evidence_ambiguous: 'The date quote is ambiguous. Select a short, exact date excerpt.',
  notification_identity_not_supported: 'The identity quote does not support this notification number and series.',
  amendment_target_not_supported: 'The amendment target does not match its source quote.',
  retrospective_effect_requires_separate_policy: 'Retrospective notifications need a separate review policy. Do not approve through this form.',
  corrigendum_or_series_requires_separate_policy: 'This document type or series needs a separate review policy.',
  notification_already_present_requires_revision_policy: 'This notification is already in the corpus. A replacement workflow is needed.',
  source_review_missing_or_changed: 'A selected source review is missing or changed. Refresh the selection.',
  publication_not_verified_for_current_retriever: 'Verify this snapshot for the currently configured retrieval backend before activation.',
  publication_base_digest_mismatch: 'The selected snapshot belongs to a different base. Refresh publications before continuing.',
  activation_verification_failed: 'Activation verification failed. The previous corpus remains active; check the backend.',
  sync_job_in_progress: 'An import is already queued or running. Refresh import history instead of starting another.',
  notification_sync_disabled: 'The hosted import worker is disabled. Configure it on the backend first.',
  notification_sync_worker_unavailable: 'The import worker is unavailable. Check the backend and refresh.',
  ingestion_operation_conflict: 'Ingestion storage is busy. Wait for the current import or publication, then refresh.',
  ingestion_registry_unavailable: 'The ingestion registry is unavailable. Check persistent backend storage before retrying.',
  upload_worker_unavailable: 'The PDF parsing worker is unavailable. Enable it on the backend before uploading.',
  invalid_uploaded_pdf: 'This file is not a structurally valid PDF. Export a valid PDF and try again.',
  uploaded_pdf_size_limit: 'Choose a PDF no larger than 25 MB.',
  uploaded_pdf_page_limit: 'Choose a PDF with 1–500 pages. Split larger books into chapter PDFs.',
  encrypted_pdf_not_supported: 'Password-protected PDFs are not supported. Supply an authorised, unencrypted copy.',
  active_pdf_content_not_supported: 'This PDF contains active or embedded content. Supply a plain document-only PDF.',
  upload_size_or_digest_mismatch: 'The transferred file does not match the reservation. Select the same original file and retry.',
  pdf_already_registered: 'This exact PDF is already registered. No duplicate publication was created.',
  source_hash_conflicting_classification: 'This PDF is already assigned another source type. It cannot be relabelled to change access.',
  replacement_source_type_mismatch: 'A replacement must keep the original source type and plan restriction.',
  replacement_target_not_active: 'That replacement target is no longer active. Refresh the library.',
  replacement_target_changed: 'The target changed after this upload was reserved. Refresh and reserve a replacement against the current version.',
  replacement_notification_identity_changed: 'A replacement notification must retain the original notification identity.',
  uploaded_chunk_review_failed: 'A chunk failed provenance or size checks. Inspect the parse; do not approve an incomplete source.',
  notification_identity_required: 'Enter the notification series, number and year. They will be checked against source quotes during review.',
};
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return messages[error.code] || (error.status === 422
    ? 'Check the form fields and try again.' : error.status === 404 ? 'This item is no longer available.' : 'The request could not be completed. Please refresh and try again.');
  return error instanceof Error && error.message === 'sample_pdf_unavailable'
    ? 'PDF viewing uses the real backend. The sample preview contains no PDF files.'
    : 'Could not reach the local API. Check that the backend is running.';
}

export class ApiClient implements Client {
  sample = false;
  private token = '';
  constructor(private base = import.meta.env.DEV ? '/api' : '', private expired: () => void = () => {}) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    const tokenUsed = this.token;
    if (tokenUsed) headers.set('Authorization', `Bearer ${tokenUsed}`);
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(this.base + path, { ...init, headers, cache: 'no-store', credentials: 'omit' });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (response.status === 401 && path !== '/auth/token' && tokenUsed === this.token) { this.logout(); this.expired(); }
      throw new ApiError(response.status, data.error || data.detail || 'request_failed');
    }
    return response.json() as Promise<T>;
  }

  async login(username: string, password: string) {
    // Memory only: no token, credential or source content in web storage.
    this.token = '';
    const result = await this.request<{ access_token: string }>('/auth/token', { method: 'POST', body: JSON.stringify({ username, password }) });
    this.token = result.access_token;
    try { return await this.me(); } catch (error) { this.logout(); throw error; }
  }
  logout() { this.token = ''; }
  me() { return this.request<User>('/me'); }
  health() { return this.request<Health>('/health'); }
  async queries() {
    // Page through the API's 100-row maximum, instead of silently dropping older chats.
    const rows: Query[] = [];
    for (let offset = 0; ; offset += 100) {
      const page = await this.request<Query[]>(`/queries?limit=100&offset=${offset}`);
      rows.push(...page);
      if (page.length < 100) return rows;
    }
  }
  submit(data: Question) { return this.request<Query>('/queries', { method: 'POST', body: JSON.stringify(data) }); }
  async reviews() {
    const rows: AdminQuery[] = [];
    for (let offset = 0; ; offset += 100) {
      const page = await this.request<AdminQuery[]>(`/admin/reviews?limit=100&offset=${offset}`);
      rows.push(...page);
      if (page.length < 100) return rows;
    }
  }
  review(id: string) { return this.request<AdminQuery>(`/admin/queries/${encodeURIComponent(id)}`); }
  saveDraft(id: string, revision: number, text: string) {
    return this.request<AdminQuery>(`/admin/queries/${encodeURIComponent(id)}/draft`, { method: 'PUT', body: JSON.stringify({ revision, draft_text: text }) });
  }
  decide(id: string, data: Decision) { return this.request<Query>(`/admin/queries/${encodeURIComponent(id)}/decision`, { method: 'POST', body: JSON.stringify(data) }); }
  reprocess(id: string, revision: number) {
    return this.request<AdminQuery>(`/admin/queries/${encodeURIComponent(id)}/reprocess`, { method: 'POST', body: JSON.stringify({ revision }) });
  }
  users() { return this.request<User[]>('/admin/users'); }
  createUser(username: string, password: string, plan: Plan) { return this.request<User>('/admin/users', { method: 'POST', body: JSON.stringify({ username, password, plan }) }); }
  setPlan(id: string, plan: Plan) { return this.request<User>(`/admin/users/${encodeURIComponent(id)}/plan`, { method: 'PATCH', body: JSON.stringify({ plan }) }); }
  sources() { return this.request<Source[]>('/admin/sources'); }
  pdf(id: string) { return this.pdfRequest(`/admin/sources/${encodeURIComponent(id)}/pdf`); }
  stagedPdf(id: string) { return this.pdfRequest(`/admin/ingestion/notifications/${encodeURIComponent(id)}/pdf`); }
  async incomingSources() {
    const rows: IncomingSource[] = [];
    for (let offset = 0; ; offset += 100) {
      const page = await this.request<IncomingSource[]>(`/admin/ingestion/notifications?limit=100&offset=${offset}`);
      rows.push(...page); if (page.length < 100) return rows;
    }
  }
  sourceDetail(id: string) { return this.request<SourceDetail>(`/admin/ingestion/notifications/${encodeURIComponent(id)}`); }
  approveSource(id: string, data: SourceReview) { return this.request<SourceDecision>(`/admin/ingestion/notifications/${encodeURIComponent(id)}/review`, { method: 'PUT', body: JSON.stringify(data) }); }
  rejectSource(id: string, revision: number, stage_sha256: string, reason: string) {
    return this.request<SourceDecision>(`/admin/ingestion/notifications/${encodeURIComponent(id)}/reject`, { method: 'POST', body: JSON.stringify({ revision, stage_sha256, reason }) });
  }
  corpusStatus() { return this.request<CorpusStatus>('/admin/ingestion/corpus'); }
  publications() { return this.request<Publication[]>('/admin/ingestion/publications'); }
  preparePublication(version_ids: string[], base_sha256: string) {
    return this.request<Publication>('/admin/ingestion/publications', { method: 'POST', body: JSON.stringify({ version_ids, base_sha256 }) });
  }
  activatePublication(id: string, base_sha256: string) {
    return this.request<{ state: string }>(`/admin/ingestion/publications/${encodeURIComponent(id)}/activate`, { method: 'POST', body: JSON.stringify({ base_sha256, confirm: true }) });
  }
  syncStatus() { return this.request<SyncStatus>('/admin/ingestion/sync'); }
  triggerSync(key: string) { return this.request<SyncJob>('/admin/ingestion/sync', { method: 'POST', body: '{}', headers: { 'Idempotency-Key': key } }); }
  async uploads() {
    const rows: UploadedSource[] = [];
    for (let offset = 0; ; offset += 100) {
      const page = await this.request<UploadedSource[]>(`/admin/uploads?limit=100&offset=${offset}`);
      rows.push(...page); if (page.length < 100) return rows;
    }
  }
  async uploadFile(file: File, spec: UploadSpec) {
    if (file.size > 25 * 1024 * 1024 || !file.size) throw new ApiError(413, 'uploaded_pdf_size_limit');
    const bytes = await file.arrayBuffer();
    const sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map((n) => n.toString(16).padStart(2, '0')).join('');
    const reserved = await this.request<UploadedSource>('/admin/uploads', { method: 'POST', body: JSON.stringify({ ...spec, sha256, byte_count: file.size }) });
    return this.request<UploadedSource>(`/admin/uploads/${encodeURIComponent(reserved.id)}/pdf`, { method: 'PUT', body: file, headers: { 'Content-Type': 'application/pdf' } });
  }
  uploadDetail(id: string) { return this.request<UploadDetail>(`/admin/uploads/${encodeURIComponent(id)}/detail`); }
  uploadedPdf(id: string) { return this.pdfRequest(`/admin/uploads/${encodeURIComponent(id)}/pdf`); }
  retryUpload(id: string) { return this.request<UploadedSource>(`/admin/uploads/${encodeURIComponent(id)}/retry`, { method: 'POST' }); }
  reviewBook(id: string, decision: BookDecision) { return this.request<SourceDecision>(`/admin/uploads/${encodeURIComponent(id)}/review`, { method: 'PUT', body: JSON.stringify(decision) }); }
  private async pdfRequest(path: string) {
    // Never navigate to a URL from model text; use this fixed authenticated route.
    const tokenUsed = this.token;
    const response = await fetch(this.base + path, {
      headers: { Authorization: `Bearer ${tokenUsed}` }, cache: 'no-store', credentials: 'omit',
    });
    if (!response.ok) {
      if (response.status === 401 && tokenUsed === this.token) { this.logout(); this.expired(); }
      throw new ApiError(response.status, 'pdf_unavailable');
    }
    if (!(response.headers.get('Content-Type') || '').startsWith('application/pdf')) throw new ApiError(502, 'invalid_pdf');
    return response.blob();
  }
}
