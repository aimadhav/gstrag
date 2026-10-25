import type { Query } from './types';

export const TOPICS = [
  ['other_gst', 'General GST'], ['renewable_energy', 'Renewable energy'], ['pencil_sharpeners', 'Pencil sharpeners'],
] as const;
export const SOURCE_LABELS = { icai_book: 'ICAI book', firm_book: 'Firm book', notification: 'Notification' };
export function dateLabel(value: string | null) {
  if (!value) return 'Not provided';
  return new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}
export function clockLabel(value: string) { return new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }); }
export function initials(username: string) { return username.split(/[._ -]+/).slice(0, 2).map((s) => s[0]).join('').toUpperCase(); }
export function conversations(rows: Query[]) {
  const grouped = new Map<string, Query[]>();
  rows.forEach((q) => grouped.set(q.conversation_id, [...(grouped.get(q.conversation_id) || []), q]));
  return [...grouped].map(([id, list]) => {
    const sorted = [...list].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
    return { id, title: sorted[0].question, latest: sorted[sorted.length - 1], rows: sorted };
  }).sort((a, b) => b.latest.created_at.localeCompare(a.latest.created_at));
}
export function statusLabel(status: string) {
  return ({ approved: 'Approved by admin', pending_review: 'Awaiting admin review', queued: 'Queued', processing: 'Checking sources',
    safe_refusal: 'Unable to answer safely', clarification_required: 'Clarification requested' } as Record<string, string>)[status] || status.replaceAll('_', ' ');
}
export function readableFlag(flag: string) {
  return ({ explicit_admin_approval_required: 'Explicit admin approval required', incomplete_amendment_chain_and_unverified_applicability: 'Amendment chain and applicability are not verified',
    no_effective_notification_evidence_in_loaded_corpus: 'No effective notification evidence in this sample',
    firm_content_requires_privacy_opt_in: 'Firm excerpts were not sent to Gemini: privacy opt-in required',
    not_configured: 'Gemini key not configured · manual drafting available', sample_only: 'Illustrative sample · not a model-generated answer',
    validated_private_draft: 'Draft passed structural and quoted-span checks only', configured_not_live_verified: 'Configured · live connectivity not verified',
  } as Record<string, string>)[flag] || flag.replaceAll('_', ' ');
}
