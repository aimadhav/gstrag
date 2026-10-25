/** Illustrative admin data only; no government documents, parser or providers. */
import { ApiError } from './api';
import type { CorpusStatus, IncomingSource, Publication, SourceDetail, SourceReview, SyncJob, SyncStatus } from './types';

export class SampleIngestion {
  private base = '1'.repeat(64);
  private rows: IncomingSource[] = ['a', 'b'].map((letter, i) => ({ id: letter.repeat(64),
    identity: `central_tax_rate:${8 + i}/2025:en`, status: 'pending_source_metadata_review', sha256: letter.repeat(64),
    stage_sha256: 'e'.repeat(64), error: null, revision: i, review_status: i ? 'approved' : null }));
  private decisions = new Map<string, SourceDetail['review']>();
  private releases: Publication[] = ['prepared', 'verified'].map((state, i) => ({ id: (i ? 'd' : 'c').repeat(64), state,
    mode: i ? 'bm25' : null, index_name: null, base_sha256: this.base, actor_id: 'sample.admin',
    created_at: new Date().toISOString(), activated_at: null, activated_by: null, error: null }));
  private jobs: SyncJob[] = [];
  private approvedUploads = new Set<string>();
  registerUpload(id: string, approved: boolean) { if (approved) this.approvedUploads.add(id); else this.approvedUploads.delete(id); }
  constructor(private guard: () => void) {}
  private clone<T>(value: T): T { return structuredClone(value); }
  async sources() { this.guard(); return this.clone(this.rows); }
  async detail(id: string): Promise<SourceDetail> {
    this.guard(); const row = this.rows.find((r) => r.id === id);
    if (!row) throw new ApiError(404, 'ingestion_version_not_found');
    const number = row.id[0] === 'a' ? 8 : 9;
    const texts = [`Notification No. ${number}/2025-Central Tax (Rate)`, '1st January, 2025', '2nd January, 2025',
      'Synthetic complete clause for interface testing only. All illustrative conditions remain together. No tax advice.'];
    return { version_id: id, candidate: { label: `Notification ${number}/2025 · illustrative sample`, subject: 'Sample source review, not a GST claim',
      kind: 'notification', series: 'central_tax_rate', number, year: 2025 }, source_sha256: row.sha256,
      stage_sha256: row.stage_sha256!, revision: row.revision, review_status: row.review_status || 'pending',
      review: this.clone(this.decisions.get(id) || null), page_count: 1, document_id: `sample-${number}`,
      items: texts.map((text, i) => ({ source_ref: `#/texts/${i}`, text, pages: [1], label: 'text' })),
      draft_chunks: [{ text: texts[3], pages: [1], token_count: 28, eligible_for_retrieval: false }] };
  }
  async approve(id: string, data: SourceReview) {
    this.guard(); const row = this.rows.find((r) => r.id === id);
    if (!row) throw new ApiError(404, 'ingestion_version_not_found');
    if (row.revision !== data.revision || row.stage_sha256 !== data.stage_sha256) throw new ApiError(409, 'stale_source_review_revision');
    row.revision++; row.review_status = 'approved'; this.decisions.set(id, { decision: 'approved', payload: this.clone(data) });
    return { version_id: id, revision: row.revision, status: 'approved', answer_approval_performed: false as const };
  }
  async reject(id: string, revision: number, sha: string, reason: string) {
    this.guard(); const row = this.rows.find((r) => r.id === id);
    if (!row) throw new ApiError(404, 'ingestion_version_not_found');
    if (row.revision !== revision || row.stage_sha256 !== sha) throw new ApiError(409, 'stale_source_review_revision_or_stage');
    row.revision++; row.review_status = 'rejected'; this.decisions.set(id, { decision: 'rejected', reason });
    return { version_id: id, revision: row.revision, status: 'rejected', answer_approval_performed: false as const };
  }
  async corpus(): Promise<CorpusStatus> { this.guard(); return { base_sha256: this.base, corpus_id: 'sample-corpus', records: 149, sources: 5 }; }
  async publications() { this.guard(); return this.clone(this.releases); }
  async prepare(ids: string[], base: string) {
    this.guard(); if (base !== this.base) throw new ApiError(409, 'active_corpus_changed');
    if (!ids.length || ids.some((id) => !this.approvedUploads.has(id) && !this.rows.some((r) => r.id === id && r.review_status === 'approved'))) throw new ApiError(409, 'source_review_missing_or_changed');
    const row: Publication = { id: crypto.randomUUID().replaceAll('-', '').repeat(2), state: 'prepared', mode: null,
      index_name: null, base_sha256: base, actor_id: 'sample.admin', created_at: new Date().toISOString(),
      activated_at: null, activated_by: null, error: null };
    this.releases.unshift(row); return this.clone(row);
  }
  async activate(id: string, base: string) {
    this.guard(); const row = this.releases.find((r) => r.id === id);
    if (base !== this.base || base !== row?.base_sha256) throw new ApiError(409, 'active_corpus_changed');
    if (row.state !== 'verified') throw new ApiError(409, 'publication_not_verified_for_current_retriever');
    this.releases.filter((r) => r.state === 'active').forEach((r) => { r.state = 'superseded'; });
    row.state = 'active'; row.activated_at = new Date().toISOString(); row.activated_by = 'sample.admin'; this.base = '2'.repeat(64);
    return { state: 'active' };
  }
  async sync(): Promise<SyncStatus> { this.guard(); return { enabled: true, worker_ready: true, max_pages: 1, max_documents: 2, since_year: 2025, jobs: this.clone(this.jobs) }; }
  async trigger(_key: string) {
    this.guard(); const row: SyncJob = { id: crypto.randomUUID(), status: 'completed', created_at: new Date().toISOString(),
      started_at: new Date().toISOString(), finished_at: new Date().toISOString(), attempts: 1, error: null,
      result: { downloaded_new_versions: 0, unchanged_versions: 0, staged_versions: 0, deferred_documents: 0,
        error_count: 0, bounded_scan: true, coverage: 'sample_only', active_corpus_changed: false, published: 0 } };
    this.jobs.unshift(row); return this.clone(row);
  }
}
