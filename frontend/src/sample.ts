/** Explicit, isolated in-memory visual preview. Never authenticates to the API. */
import { ApiError } from './api';
import { SampleIngestion } from './sampleIngestion';
import { SampleUploads } from './sampleUploads';
import type { AdminQuery, BookDecision, Client, Decision, Plan, Query, Question, Role, Source, SourceReview, UploadSpec, User } from './types';

const SAMPLE_ANSWER = `Book explanation
The selected book passages are available for comparison. This is sample interface copy, not a GST conclusion. [S1]

Latest notification (loaded evidence only)
Review the loaded notification and its effective date before applying a book explanation. This sample does not establish an amendment or current law. [S2]

Practical effect
An administrator would check the transaction facts, exceptions and source support before releasing an answer.

Limitations
Illustrative sample only. No live model answer or tax advice is shown.`;

export class SampleClient implements Client {
  sample = true;
  private current: User;
  private people: User[];
  private rows: Query[];
  private inbox: AdminQuery[];
  private ingestion = new SampleIngestion(() => this.admin());
  private uploadState = new SampleUploads(() => this.admin(), (id, approved) => this.ingestion.registerUpload(id, approved));
  constructor(role: Role = 'user', plan: Plan = 'pro') {
    this.current = { id: 'sample-researcher', username: role === 'admin' ? 'sample.admin' : 'sample.researcher', role, plan };
    this.people = [this.current, { id: 'sample-plus', username: 'sample.plus', role: 'user', plan: 'plus' }];
    const now = new Date();
    this.rows = [{
      id: 'sample-approved', conversation_id: 'sample-conversation', parent_query_id: null,
      question: 'How should I distinguish composite and mixed supplies?', as_of: '2023-03-01', topic_ids: ['other_gst'],
      status: 'approved', message: 'Sample approved answer.', answer: SAMPLE_ANSWER,
      citations: [
        { citation_id: 'S1', source_name: plan === 'pro' ? 'Firm GST book · sample reference' : 'ICAI GST book · sample reference', source_type: plan === 'pro' ? 'firm_book' : 'icai_book', pages: [12] },
        { citation_id: 'S2', source_name: 'Notification · sample reference', source_type: 'notification', pages: [1] },
      ], approval_kind: 'edit_and_approve', created_at: new Date(now.getTime() - 3600000).toISOString(),
      expires_at: new Date(now.getTime() + 29 * 86400000).toISOString(),
    }];
    this.inbox = [this.makeReview({ ...this.rows[0], id: 'sample-pending', question: 'Which conditions should be checked for a bundled supply?' })];
  }
  private clone<T>(value: T): T { return structuredClone(value); }
  private admin() { if (this.current.role !== 'admin') throw new ApiError(403, 'admin_required'); }
  private makeReview(row: Query): AdminQuery {
    return {
      id: row.id, user_id: this.current.id, question: row.question, conversation_id: row.conversation_id,
      parent_query_id: row.parent_query_id, as_of: row.as_of, topic_ids: row.topic_ids, status: 'pending_review', revision: 2,
      plan_at_retrieval: this.current.plan, draft_text: SAMPLE_ANSWER,
      packet: { generation: 'sample_only', current_law_verified: false,
        review_reasons: ['sample_data_only', 'explicit_admin_approval_required', 'incomplete_amendment_chain'],
        citations: (this.rows.find((r) => r.citations.length)?.citations || []).map((c, i) => ({ ...c, document_id: `sample-source-${i}`,
          source_refs: ['sample-reference'], excerpt: 'Illustrative source excerpt for the interface preview. No actual PDF or legal claim is supplied.' })),
      }, expires_at: row.expires_at,
    };
  }
  async login() { return this.me(); }
  logout() {}
  async me() { return this.clone(this.current); }
  async health() { return { status: 'ok', retriever: 'sample only', generation: 'sample_only' }; }
  async queries() { return this.clone(this.rows); }
  async submit(data: Question) {
    const id = `sample-${crypto.randomUUID()}`;
    const parent = this.rows.find((row) => row.id === data.parent_query_id);
    const row: Query = { ...data, id, conversation_id: parent?.conversation_id || id, parent_query_id: parent?.id || null,
      status: 'pending_review', message: 'Sample question saved in this tab only. Real answers need admin approval.',
      answer: null, citations: [], approval_kind: null, created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 30 * 86400000).toISOString() };
    this.rows.unshift(row); this.inbox.unshift(this.makeReview(row)); return this.clone(row);
  }
  async reviews() { this.admin(); return this.clone(this.inbox.filter((r) => r.status === 'pending_review')); }
  async review(id: string) {
    this.admin(); const row = this.inbox.find((r) => r.id === id);
    if (!row) throw new ApiError(404, 'query_not_found'); return this.clone(row);
  }
  async saveDraft(id: string, revision: number, text: string) {
    const row = await this.review(id);
    if (row.revision !== revision || row.status !== 'pending_review') throw new ApiError(409, 'review_state_or_revision_changed');
    row.draft_text = text; row.revision += 1; this.inbox[this.inbox.findIndex((r) => r.id === id)] = row; return this.clone(row);
  }
  async decide(id: string, data: Decision) {
    const row = await this.review(id);
    if (row.revision !== data.revision || row.status !== 'pending_review') throw new ApiError(409, 'review_state_or_revision_changed');
    if (data.action === 'approve' || data.action === 'edit_and_approve') {
      const text = data.action === 'approve' ? row.draft_text : data.text;
      if (!text || !data.citation_ids.length) throw new ApiError(422, 'approval_requires_answer_and_citations');
      if (Array.from(text.matchAll(/\[(S[1-9][0-9]*)\]/g)).some((m) => !data.citation_ids.includes(m[1]))) throw new ApiError(422, 'inline_citations_must_be_in_approval_selection');
    }
    row.status = data.action === 'refuse' ? 'refused' : data.action === 'request_clarification' ? 'clarification_required' : 'approved';
    row.revision += 1; this.inbox[this.inbox.findIndex((r) => r.id === id)] = row;
    const query: Query = {
      ...row, created_at: new Date().toISOString(), status: row.status === 'refused' ? 'safe_refusal' : row.status,
      message: data.text || 'Sample decision recorded.', approval_kind: data.action,
      answer: row.status === 'approved' ? (data.action === 'approve' ? row.draft_text : data.text || null) : null,
      citations: row.status === 'approved' ? (row.packet?.citations || []).filter((c) => data.citation_ids.includes(c.citation_id))
        .map(({ citation_id, source_name, source_type, pages }) => ({ citation_id, source_name, source_type, pages })) : [],
    };
    const index = this.rows.findIndex((r) => r.id === id);
    if (index >= 0) this.rows[index] = query; else this.rows.unshift(query);
    return this.clone(query);
  }
  async reprocess(id: string, revision: number) {
    const row = await this.review(id);
    if (row.revision !== revision) throw new ApiError(409, 'review_state_or_revision_changed');
    row.revision += 1; row.status = 'pending_review'; row.plan_at_retrieval = this.current.plan;
    this.inbox[this.inbox.findIndex((r) => r.id === id)] = row; return this.clone(row);
  }
  async users() { this.admin(); return this.clone(this.people); }
  async createUser(username: string, _password: string, plan: Plan) {
    this.admin(); if (this.people.some((u) => u.username === username)) throw new ApiError(409, 'username_already_exists');
    const user: User = { id: `sample-${crypto.randomUUID()}`, username, plan, role: 'user' };
    this.people.push(user); return this.clone(user);
  }
  async setPlan(id: string, plan: Plan) {
    this.admin(); const user = this.people.find((u) => u.id === id);
    if (!user) throw new ApiError(404, 'user_not_found'); user.plan = plan;
    if (id === this.current.id) this.current.plan = plan; return this.clone(user);
  }
  async sources(): Promise<Source[]> {
    this.admin(); return [
      { document_id: 'sample-source-0', name: 'ICAI GST book · sample reference', source_type: 'icai_book', page_count: 104, pdf_url: '' },
      { document_id: 'sample-source-1', name: 'Firm GST book · sample reference', source_type: 'firm_book', page_count: 45, pdf_url: '' },
      { document_id: 'sample-source-2', name: 'Notification · sample reference', source_type: 'notification', page_count: 1, pdf_url: '' },
    ];
  }
  async pdf(): Promise<Blob> { this.admin(); throw new Error('sample_pdf_unavailable'); }
  async stagedPdf(): Promise<Blob> { this.admin(); throw new Error('sample_pdf_unavailable'); }
  async incomingSources() { return [...await this.ingestion.sources(), ...(await this.uploadState.list()).filter((r) => r.source_type === 'notification').map((r) => ({ ...r, identity: r.title, review_status: r.review_status as 'approved' | 'rejected' | null }))]; }
  sourceDetail(id: string) { return this.uploadState.has(id) ? this.uploadState.notification(id) : this.ingestion.detail(id); }
  approveSource(id: string, data: SourceReview) { return this.uploadState.has(id) ? this.uploadState.decide(id, data) : this.ingestion.approve(id, data); }
  rejectSource(id: string, revision: number, sha: string, reason: string) { return this.uploadState.has(id) ? this.uploadState.decide(id, { revision, stage_sha256: sha, action: 'reject', reason, source_checked: false, structure_checked: false }, 'reject') : this.ingestion.reject(id, revision, sha, reason); }
  corpusStatus() { return this.ingestion.corpus(); }
  publications() { return this.ingestion.publications(); }
  preparePublication(ids: string[], base: string) { return this.ingestion.prepare(ids, base); }
  activatePublication(id: string, base: string) { return this.ingestion.activate(id, base); }
  syncStatus() { return this.ingestion.sync(); }
  triggerSync(key: string) { return this.ingestion.trigger(key); }
  uploads() { return this.uploadState.list(); }
  uploadFile(file: File, spec: UploadSpec) { return this.uploadState.upload(file, spec); }
  uploadDetail(id: string) { return this.uploadState.detail(id); }
  async uploadedPdf(): Promise<Blob> { this.admin(); throw new Error('sample_pdf_unavailable'); }
  retryUpload(id: string) { return this.uploadState.retry(id); }
  reviewBook(id: string, decision: BookDecision) { return this.uploadState.decide(id, decision, decision.action); }
}
