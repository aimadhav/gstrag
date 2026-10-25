/** Isolated upload UI states. No file bytes, parsing, authenticity or provider verification. */
import { ApiError } from './api';
import type { BookDecision, SourceDecision, SourceDetail, SourceReview, UploadDetail, UploadedSource, UploadSpec } from './types';

export class SampleUploads {
  private rows: UploadedSource[] = [];
  private specs = new Map<string, UploadSpec>();
  constructor(private guard: () => void, private approve: (id: string, approved: boolean) => void) {}
  private clone<T>(value: T): T { return structuredClone(value); }
  async list() { this.guard(); return this.clone(this.rows); }
  async upload(file: File, spec: UploadSpec) {
    this.guard(); const id = crypto.randomUUID().replaceAll('-', '').repeat(2);
    const row: UploadedSource = { id, title: spec.title, source_type: spec.source_type, sha256: id, stage_sha256: 'e'.repeat(64),
      status: 'pending_source_metadata_review', error: null, byte_count: file.size, page_count: 1,
      replaces_document_id: spec.replaces_document_id, created_at: new Date().toISOString(), revision: 0, review_status: null };
    this.rows.unshift(row); this.specs.set(id, this.clone(spec)); return this.clone(row);
  }
  has(id: string) { return this.rows.some((r) => r.id === id); }
  async detail(id: string): Promise<UploadDetail> {
    this.guard(); const row = this.rows.find((r) => r.id === id); if (!row) throw new ApiError(404, 'upload_not_found');
    const spec = this.specs.get(id)!;
    const texts = [`Notification No. ${spec.number || 8}/${spec.year || 2025}-Central Tax${spec.series === 'central_tax' ? '' : ' (Rate)'}`,
      '1st January, 2025', '2nd January, 2025', 'Synthetic complete source text. This is an interface sample, not uploaded file content or tax advice.'];
    return { ...this.clone(row), document_id: 'sample-upload-' + id.slice(0, 12),
      items: texts.map((text, i) => ({ source_ref: `#/texts/${i}`, text, pages: [1], label: 'text' })),
      draft_chunks: [{ chunk_id: id + ':1', text: texts[3], embedding_text: texts[3], headings: ['Illustrative sample'],
        token_count: 25, pages: [1], source_refs: ['#/texts/3'], plan_required: row.source_type === 'firm_book' ? 'pro' : 'plus', eligible_for_retrieval: false }],
      warnings: ['Sample data only. The selected file was not transmitted, parsed or stored.'], excluded_items: [], over_token_budget: 0 };
  }
  async notification(id: string): Promise<SourceDetail> {
    const detail = await this.detail(id); const spec = this.specs.get(id)!;
    return { version_id: id, candidate: { label: spec.title, kind: 'notification', series: spec.series!, number: spec.number!, year: spec.year! },
      source_sha256: detail.sha256, stage_sha256: detail.stage_sha256!, revision: detail.revision, review_status: detail.review_status || 'pending',
      review: null, page_count: 1, document_id: detail.document_id, items: detail.items, draft_chunks: detail.draft_chunks };
  }
  async decide(id: string, decision: BookDecision | SourceReview, action = 'approve'): Promise<SourceDecision> {
    this.guard(); const row = this.rows.find((r) => r.id === id); if (!row) throw new ApiError(404, 'upload_not_found');
    if (decision.revision !== row.revision || decision.stage_sha256 !== row.stage_sha256) throw new ApiError(409, 'stale_source_review_revision_or_stage');
    row.revision++; row.review_status = action === 'reject' ? 'rejected' : 'approved';
    this.approve(id, row.review_status === 'approved');
    return { version_id: id, revision: row.revision, status: row.review_status, answer_approval_performed: false };
  }
  async retry(id: string) { this.guard(); const row = this.rows.find((r) => r.id === id); if (!row) throw new ApiError(404, 'upload_not_found'); return this.clone(row); }
}
