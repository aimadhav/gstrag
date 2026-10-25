import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, ArrowUpRight, Check, CheckCheck, CircleCheck, Clock3, Download, FileCheck2, FileText,
  GitBranch, Inbox, Layers3, Plus, RefreshCw, ShieldAlert, ShieldCheck, Trash2, Users } from 'lucide-react';
import { errorMessage } from './api';
import { dateLabel, readableFlag, TOPICS } from './helpers';
import { Busy, Empty, ErrorNotice, Modal, PageHeading, useUnsavedChanges } from './ui';
import type { Client, CorpusStatus, IncomingSource, Publication, ReviewedClause, SourceAnchor, SourceDetail,
  SourceItem, SourceReview, SyncStatus } from './types';

export type AdminDestination = 'reviews' | 'incoming' | 'publications' | 'imports' | 'users' | 'sources' | 'uploads';
const SOURCE_STAGED = 'pending_source_metadata_review';
export function OpsStatus({ status }: { status: string }) {
  const labels: Record<string, string> = { pending: 'Needs review', approved: 'Source approved', rejected: 'Rejected',
    pending_source_metadata_review: 'Needs review', prepared: 'Awaiting verification', verified: 'Verified',
    verification_failed: 'Verification failed', active: 'Active', superseded: 'Superseded',
    completed: 'Completed · staging only', completed_with_errors: 'Completed with errors', failed: 'Failed', queued: 'Queued', running: 'Running',
    awaiting_upload: 'Awaiting PDF', uploaded_queued: 'Parse queued', upload_parsing: 'Parsing', parsing: 'Parsing', upload_parse_failed: 'Parse failed' };
  return <span className={`ops-status ${status}`}><span aria-hidden="true" />{labels[status] || readableFlag(status)}</span>;
}

export function AdminOverview({ client, navigate }: { client: Client; navigate: (view: AdminDestination) => void }) {
  const [stats, setStats] = useState<{ answers: number; incoming: IncomingSource[]; corpus: CorpusStatus; sync: SyncStatus } | null>(null);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true; setLoading(true);
    Promise.all([client.reviews(), client.incomingSources(), client.corpusStatus(), client.syncStatus()]).then(([answers, incoming, corpus, sync]) => {
      if (live) { setStats({ answers: answers.length, incoming, corpus, sync }); setError(''); }
    }).catch((e) => { if (live) setError(errorMessage(e)); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [client, reload]);
  return <section className="ops-page"><div className="page-heading-row"><PageHeading eyebrow="ADMIN · CONTROL CENTRE" title="Good research needs good judgment." subtitle="One workspace for incoming evidence, controlled publication and human-reviewed answers." />
    <button className="button secondary" disabled={loading} onClick={() => setReload(reload + 1)}><RefreshCw size={15} />Refresh overview</button></div>
    <ErrorNotice error={error} />{loading ? <Busy text="Loading admin overview…" /> : <>
      <div className="ops-metrics">
        <button onClick={() => navigate('reviews')}><span><Inbox size={18} />ANSWER REVIEWS</span><strong>{stats?.answers ?? '—'}</strong><small>Private drafts awaiting a decision <ArrowUpRight size={14} /></small></button>
        <button onClick={() => navigate('incoming')}><span><FileCheck2 size={18} />SOURCE REVIEWS</span><strong>{stats?.incoming.filter((r) => r.status === SOURCE_STAGED && !r.review_status).length ?? '—'}</strong><small>Parsed notifications to inspect <ArrowUpRight size={14} /></small></button>
        <button onClick={() => navigate('sources')}><span><Layers3 size={18} />ACTIVE CORPUS</span><strong>{stats?.corpus.records ?? '—'}</strong><small>{stats ? `${stats.corpus.sources} registered PDFs` : 'Corpus unavailable'} <ArrowUpRight size={14} /></small></button>
      </div>
      <div className="ops-workflow"><div><span className="eyebrow">THREE CHECKPOINTS. THREE SEPARATE DECISIONS.</span><h2>From incoming PDF to a considered answer.</h2><p>Nothing moves straight from a government download to a customer response.</p></div>
        <div className="ops-steps">{[
          ['01', 'Review the source', 'Check identity, exact source quotes, dates and complete clauses.', 'incoming', FileCheck2],
          ['02', 'Publish the evidence', 'Prepare a snapshot, verify its index, then explicitly activate it.', 'publications', GitBranch],
          ['03', 'Review the answer', 'Check the reasoning, edit the draft and approve what the user sees.', 'reviews', ShieldCheck],
        ].map(([number, title, text, destination, Icon]) => { const Graphic = Icon as typeof FileCheck2; return <button key={String(number)} onClick={() => navigate(destination as AdminDestination)}><span className="ops-step-number">{String(number)}</span><Graphic size={23} strokeWidth={1.5} /><h3>{String(title)}</h3><p>{String(text)}</p><span className="text-button">Open workspace <ArrowRight size={14} /></span></button>; })}</div>
      </div>
      <div className="ops-bottom-grid"><div className="panel ops-feed"><div className="ops-section-title"><Download size={19} /><h2>Notification collection</h2></div><p>Central Tax + Central Tax (Rate), from partial official GST Council mirrors. Not a complete or verified-current feed.</p>
        <div className="ops-inline-stat"><span>Backend worker</span><strong>{stats?.sync.enabled ? stats.sync.worker_ready ? 'Ready' : 'Unavailable' : 'Disabled'}</strong></div>
        <button className="text-button" onClick={() => navigate('imports')}>Import history & controls <ArrowUpRight size={15} /></button></div>
        <div className="panel ops-feed"><div className="ops-section-title"><Users size={19} /><h2>Access is deliberate, too.</h2></div><p>Assign Plus or Pro manually. Approved history remains visible after a downgrade within its 30-day retention window.</p><button className="text-button" onClick={() => navigate('users')}>Manage researcher accounts <ArrowUpRight size={15} /></button>
          <button className="text-button" onClick={() => navigate('uploads')}>Upload or replace a PDF <ArrowUpRight size={15} /></button></div></div>
    </>}</section>;
}

type AnchorKey = keyof SourceReview['anchors'];
const ANCHOR_NAMES: Record<AnchorKey, string> = { identity: 'Identity', issued_on: 'Issue date', effective_from: 'Effective date', amends: 'Amendment' };
const blankAnchor = (): SourceAnchor => ({ source_ref: '', pages: [], quote: '' });
type ClauseDraft = Omit<ReviewedClause, 'complete_clause_confirmed'> & { complete_clause_confirmed: boolean };
const newClause = (number: number): ClauseDraft => ({ id: `clause_${number}`, subject: '', topic_id: 'other_gst', source_refs: [], provisions: [], operative_change: '', complete_clause_confirmed: false });

function AnchorFields({ name, value, items, onChange }: { name: AnchorKey; value: SourceAnchor; items: SourceItem[]; onChange: (anchor: SourceAnchor) => void }) {
  const label = ANCHOR_NAMES[name];
  return <fieldset className="anchor-fields"><legend>{label} evidence</legend><label>{label} source item<select required value={value.source_ref} onChange={(e) => {
    const item = items.find((r) => r.source_ref === e.target.value);
    onChange(item ? { source_ref: item.source_ref, pages: item.pages, quote: item.text.length <= 4000 ? item.text : '' } : blankAnchor());
  }}><option value="">Choose an original source item</option>{items.map((item) => <option key={item.source_ref} value={item.source_ref}>{item.source_ref} · p. {item.pages.join(', ')} · {item.text.slice(0, 85)}</option>)}</select></label>
    <label>{label} evidence quote<textarea rows={2} value={value.quote} required minLength={5} maxLength={4000} placeholder="Exact excerpt, not a paraphrase" onChange={(e) => onChange({ ...value, quote: e.target.value })} /></label><p className="small muted">PDF p. {value.pages.join(', ') || '—'} · Page numbers come from the selected Docling item.</p></fieldset>;
}

function SourceReviewForm({ client, source, onDone, onDirtyChange }: { client: Client; source: SourceDetail; onDone: () => Promise<void>; onDirtyChange: (dirty: boolean) => void }) {
  const saved = source.review?.payload;
  const [issued, setIssued] = useState(saved?.issued_on || ''); const [effective, setEffective] = useState(saved?.effective_from || '');
  const [amending, setAmending] = useState(Boolean(saved?.amends)); const [amends, setAmends] = useState(saved?.amends || '');
  const [anchors, setAnchors] = useState<SourceReview['anchors']>(saved?.anchors || { identity: blankAnchor(), issued_on: blankAnchor(), effective_from: blankAnchor(), amends: null });
  const [clauses, setClauses] = useState<ClauseDraft[]>(saved?.clauses.map((c) => ({ ...c, complete_clause_confirmed: false })) || [newClause(1)]);
  const [checked, setChecked] = useState(false); const [dirty, setDirty] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [confirmation, setConfirmation] = useState<'approve' | 'reject' | null>(null); const [reason, setReason] = useState('');
  useUnsavedChanges(dirty || busy, onDirtyChange);
  function edit(change: () => void, resetCheck = true) { change(); setDirty(true); if (resetCheck) setChecked(false); }
  function clauseChange(index: number, patch: Partial<ClauseDraft>) { edit(() => setClauses(clauses.map((c, i) => i === index ? { ...c, ...patch } : c))); }
  async function decide(event: FormEvent) {
    event.preventDefault(); if (!confirmation || busy) return; setBusy(true); setError('');
    try {
      if (confirmation === 'reject') await client.rejectSource(source.version_id, source.revision, source.stage_sha256, reason);
      else await client.approveSource(source.version_id, { revision: source.revision, stage_sha256: source.stage_sha256,
        issued_on: issued, effective_from: effective, amends: amending ? amends : null, source_checked: true,
        anchors: { ...anchors, amends: amending ? anchors.amends : null },
        clauses: clauses.map((c) => ({ ...c, provisions: c.provisions.map((p) => p.trim()).filter(Boolean), complete_clause_confirmed: true })) });
      setDirty(false); onDirtyChange(false); setConfirmation(null); await onDone();
    } catch (e) { setError(errorMessage(e)); setConfirmation(null); } finally { setBusy(false); }
  }
  const attestations = checked && clauses.every((c) => c.complete_clause_confirmed && c.source_refs.length && c.provisions.some((p) => p.trim()));
  return <div className="source-review-form"><div className="ops-section-title"><FileCheck2 size={20} /><h3>Source decision</h3><span className="ops-private">ADMIN ONLY</span></div>
    <p className="small muted">No dates, amendment target or clause completeness are inferred. Recheck all evidence before approving.</p>
    {source.review && <div className="info-notice">Previous decision: {source.review.decision} · Revision {source.revision}{source.review.reason && <span> · {source.review.reason}</span>}</div>}
    <ErrorNotice error={error} />
    <form className="stack" onSubmit={(e) => { e.preventDefault(); if (attestations) setConfirmation('approve'); }}>
      <fieldset disabled={busy} className="ops-form-fields"><div className="ops-date-grid"><label>Issue date<input type="date" required value={issued} onInput={(e) => edit(() => setIssued(e.currentTarget.value))} onChange={(e) => edit(() => setIssued(e.target.value))} /></label>
        <label>Effective date<input type="date" required min={issued || undefined} value={effective} onInput={(e) => edit(() => setEffective(e.currentTarget.value))} onChange={(e) => edit(() => setEffective(e.target.value))} /></label></div>
        <p className="small muted">This form supports a single prospective effective date. Retrospective or complex provisions need a separate policy.</p>
        {(['identity', 'issued_on', 'effective_from'] as AnchorKey[]).map((key) => <AnchorFields key={key} name={key} value={anchors[key]!} items={source.items} onChange={(value) => edit(() => setAnchors({ ...anchors, [key]: value }))} />)}
        <label className="check-label"><input type="checkbox" checked={amending} onChange={(e) => edit(() => setAmending(e.target.checked))} />This notification amends an earlier notification</label>
        {amending && <><label>Amendment target<input required value={amends} pattern="central_tax(_rate)?:[1-9][0-9]{0,2}/[0-9]{4}" placeholder="central_tax_rate:1/2017" onChange={(e) => edit(() => setAmends(e.target.value))} /></label><AnchorFields name="amends" value={anchors.amends || blankAnchor()} items={source.items} onChange={(value) => edit(() => setAnchors({ ...anchors, amends: value }))} /></>}
        <div className="ops-section-title"><h3>Complete operative clauses</h3><span className="small muted">{clauses.length}/20</span></div>
        <p className="small muted">Select full source items, including conditions and exceptions. The backend checks provenance and the 512-token limit; it does not prove legal completeness.</p>
        {clauses.map((clause, index) => <fieldset className="clause-fields" key={index}><legend>Clause {index + 1}</legend>
          <div className="ops-date-grid"><label>Clause {index + 1} ID<input value={clause.id} required pattern="[a-z][a-z0-9_]{0,63}" maxLength={64} onChange={(e) => clauseChange(index, { id: e.target.value })} /></label><label>Clause {index + 1} topic<select value={clause.topic_id} onChange={(e) => clauseChange(index, { topic_id: e.target.value })}>{TOPICS.map(([id, title]) => <option key={id} value={id}>{title}</option>)}</select></label></div>
          <label>Clause {index + 1} subject<input value={clause.subject} required minLength={5} maxLength={300} onChange={(e) => clauseChange(index, { subject: e.target.value })} /></label>
          <label>Clause {index + 1} provisions<input value={clause.provisions.join(';')} required maxLength={2000} placeholder="e.g. Section 8; Schedule entry (separate with semicolons)" onChange={(e) => clauseChange(index, { provisions: e.target.value.split(';') })} /></label>
          <label>Clause {index + 1} operative change<textarea rows={2} value={clause.operative_change} required minLength={5} maxLength={2000} onChange={(e) => clauseChange(index, { operative_change: e.target.value })} /></label>
          <fieldset className="clause-source-selection"><legend>Clause {index + 1} complete source items</legend>{source.items.map((item) => <label className="check-label" key={item.source_ref}><input type="checkbox" checked={clause.source_refs.includes(item.source_ref)} onChange={(e) => clauseChange(index, { source_refs: e.target.checked ? [...clause.source_refs, item.source_ref] : clause.source_refs.filter((ref) => ref !== item.source_ref), complete_clause_confirmed: false })} /><span>{item.source_ref} · p. {item.pages.join(', ')} · {item.text.slice(0, 90)}</span></label>)}</fieldset>
          <label className="check-label ops-attestation"><input type="checkbox" checked={clause.complete_clause_confirmed} onChange={(e) => clauseChange(index, { complete_clause_confirmed: e.target.checked })} /><span>I checked clause {index + 1}: its conditions and exceptions are complete in these selected items.</span></label>
          {clauses.length > 1 && <button type="button" className="text-button danger-text" onClick={() => edit(() => setClauses(clauses.filter((_, i) => i !== index)))}><Trash2 size={14} />Remove clause {index + 1}</button>}
        </fieldset>)}
        <button type="button" className="button secondary" disabled={clauses.length >= 20} onClick={() => edit(() => { let number = 1; while (clauses.some((c) => c.id === `clause_${number}`)) number++; setClauses([...clauses, newClause(number)]); })}><Plus size={15} />Add complete clause</button>
        <label className="check-label ops-attestation"><input type="checkbox" checked={checked} onChange={(e) => edit(() => setChecked(e.target.checked), false)} /><span>I inspected the original PDF, identity, dates and selected clauses. Source approval is not answer approval.</span></label>
      </fieldset>
      <div className="button-row ops-sticky-actions"><button className="button primary" disabled={busy || !attestations}><Check size={16} />Approve source metadata</button><button type="button" className="button secondary" disabled={busy} onClick={() => { setReason(''); setConfirmation('reject'); }}>Reject source</button>{dirty && <span className="small warning-text">Unsaved review</span>}</div>
    </form>
    {confirmation && <Modal title={confirmation === 'approve' ? 'Confirm source approval' : 'Reject incoming source'} onClose={() => { if (!busy) setConfirmation(null); }}><form className="modal-body stack" onSubmit={decide}>
      <p>{confirmation === 'approve' ? 'This records your source review against this exact PDF and parse. It does not index, activate or approve an answer.' : 'The PDF and audit record are retained. Rejecting it does not delete a source or publish a response.'}</p>
      {confirmation === 'reject' && <label>Rejection reason<textarea required minLength={5} maxLength={1000} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} /></label>}
      <div className="button-row"><button className="button secondary" type="button" disabled={busy} onClick={() => setConfirmation(null)}>Keep reviewing</button><button className="button primary" disabled={busy}>{confirmation === 'approve' ? 'Confirm source approval' : 'Confirm rejection'}</button></div></form></Modal>}
  </div>;
}

export function SourceInbox({ client, onPdf, onDirtyChange, initialSelection }: { client: Client; onPdf: (id: string, page: number, staged?: boolean) => void; onDirtyChange: (dirty: boolean) => void; initialSelection?: string | null }) {
  const [rows, setRows] = useState<IncomingSource[]>([]); const [selected, setSelected] = useState<string | null>(initialSelection || null);
  const [detail, setDetail] = useState<SourceDetail | null>(null); const [filter, setFilter] = useState('all'); const [search, setSearch] = useState('');
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false); const [dirty, setDirty] = useState(false); const [pending, setPending] = useState<string | null>(null);
  const [revision, setRevision] = useState(0); const [reload, setReload] = useState(0);
  const dirtyChanged = useCallback((value: boolean) => { setDirty(value); onDirtyChange(value); }, [onDirtyChange]);
  useEffect(() => { let live = true; setLoading(true);
    client.incomingSources().then((list) => { if (live) { setRows(list); setSelected((old) => old || list.find((r) => !r.review_status)?.id || list[0]?.id || null); setError(''); } })
      .catch((e) => { if (live) setError(errorMessage(e)); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [client, reload]);
  const selectedRow = rows.find((r) => r.id === selected);
  useEffect(() => {
    let live = true; setDetail(null); setError(''); setLoadingDetail(false);
    if (!selected || selectedRow?.status !== SOURCE_STAGED) return;
    setLoadingDetail(true);
    client.sourceDetail(selected).then((result) => { if (live) setDetail(result); }).catch((e) => { if (live) setError(errorMessage(e)); }).finally(() => { if (live) setLoadingDetail(false); });
    return () => { live = false; };
  }, [client, selected, selectedRow?.status, revision]);
  async function done() { setNotice('Source decision recorded. Nothing was indexed, activated or released to a customer.'); setRows(await client.incomingSources()); setRevision((r) => r + 1); }
  function choose(id: string) { if (id === selected) return; if (dirty) setPending(id); else { setSelected(id); setNotice(''); } }
  function refresh() { if (dirty) setPending('refresh'); else { setReload((r) => r + 1); setRevision((r) => r + 1); } }
  const visible = rows.filter((r) => (filter === 'all' || (filter === 'pending' ? !r.review_status : r.review_status === filter)) && r.identity.toLowerCase().includes(search.toLowerCase()));
  return <section className="ops-page"><div className="page-heading-row"><PageHeading eyebrow="ADMIN · INCOMING EVIDENCE" title="Check the source before it joins the shelf." subtitle="Review the original PDF and its page-bound content. Downloaded does not mean trusted or published." /><button className="button secondary" onClick={refresh}><RefreshCw size={15} />Refresh sources</button></div>
    <div className="ops-coverage"><ShieldAlert size={17} /><span>Partial official-mirror coverage · No automatic legal precedence · Plus and Pro can retrieve only after publication</span></div>
    <ErrorNotice error={error} />{notice && <div className="success-notice" role="status"><CircleCheck size={17} />{notice}</div>}
    <div className="ops-toolbar"><label className="ops-search">Find a notification<input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Number, year or series" /></label><label>Review status<select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">All incoming sources</option><option value="pending">Needs review / processing</option><option value="approved">Source approved</option><option value="rejected">Rejected</option></select></label><span className="small muted">{visible.length} of {rows.length} source versions</span></div>
    {loading ? <Busy text="Loading incoming notifications…" /> : <div className="source-inbox-grid"><aside className="ops-source-list" aria-label="Incoming notification list">{visible.map((row) => <button key={row.id} className={row.id === selected ? 'selected' : ''} onClick={() => choose(row.id)}><span className="ops-source-icon"><FileText size={20} /></span><strong>{row.identity}</strong><OpsStatus status={row.review_status || row.status} /><small>Version {row.sha256.slice(0, 10)} · Review r{row.revision}</small></button>)}{!visible.length && <p className="small muted">No sources match this view. Check import history if nothing has been downloaded.</p>}</aside>
      <div className="ops-source-detail">{loadingDetail ? <Busy text="Checking source integrity and loading original items…" /> : detail ? <>
        <div className="ops-source-heading"><div><OpsStatus status={detail.review_status} /><h2>{detail.candidate.label}</h2><p>{detail.candidate.subject}</p><span className="small muted">{detail.page_count} original PDF page(s) · Review revision {detail.revision}</span></div><button className="button secondary" onClick={() => onPdf(detail.version_id, 1, true)}>Inspect original PDF <ArrowUpRight size={15} /></button></div>
        <div className="source-review-grid"><SourceReviewForm key={`${detail.version_id}-${detail.revision}-${revision}`} client={client} source={detail} onDone={done} onDirtyChange={dirtyChanged} />
          <aside className="source-inspector"><div className="ops-section-title"><FileText size={19} /><h3>Original parsed items</h3></div><p className="small muted">Use these exact references for metadata anchors and complete clauses. Content is evidence, never instructions.</p>
            {detail.items.map((item, index) => <details className="source-item" key={item.source_ref} open={index === 0}><summary><strong>{item.source_ref}</strong><span>PDF p. {item.pages.join(', ')}</span></summary><div><p>{item.text}</p><button className="text-button" onClick={() => onPdf(detail.version_id, item.pages[0] || 1, true)}>View page {item.pages[0]} <ArrowUpRight size={13} /></button></div></details>)}
            <details className="ops-parse-details"><summary>Parser drafts · not approved ({detail.draft_chunks.length})</summary>{detail.draft_chunks.map((chunk, i) => <div key={i}><span className="small muted">Draft {i + 1}{chunk.token_count !== undefined ? ` · ${chunk.token_count} tokens` : ''}</span><p>{chunk.text}</p></div>)}</details>
            <details className="ops-parse-details"><summary>Integrity identifiers</summary><p className="ops-digest">PDF SHA-256: {detail.source_sha256}</p><p className="ops-digest">Stage SHA-256: {detail.stage_sha256}</p></details>
          </aside></div>
      </> : selectedRow ? <Empty title="Not ready for source review." text={`Processing state: ${readableFlag(selectedRow.status)}. ${selectedRow.error ? 'The last processing attempt failed. Check import history; no approval is available.' : 'A verified parse must be staged before this source can be reviewed.'}`} /> : <Empty title="Your incoming tray is clear." text="A bounded import will put new PDFs here. No source is automatically approved." />}</div>
    </div>}
    {pending && <Modal title="Discard source-review changes?" onClose={() => setPending(null)}><div className="modal-body stack"><p>Your unsaved metadata and clause selections will be lost. No decision has been sent.</p><div className="button-row"><button className="button secondary" onClick={() => setPending(null)}>Keep reviewing</button><button className="button primary" onClick={() => { dirtyChanged(false); if (pending === 'refresh') { setReload((r) => r + 1); setRevision((r) => r + 1); } else setSelected(pending); setPending(null); }}>Discard changes</button></div></div></Modal>}
  </section>;
}

export function PublicationsDesk({ client }: { client: Client }) {
  const [corpus, setCorpus] = useState<CorpusStatus | null>(null); const [rows, setRows] = useState<Publication[]>([]); const [sources, setSources] = useState<IncomingSource[]>([]);
  const [selected, setSelected] = useState<string[]>([]); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [confirm, setConfirm] = useState<Publication | 'prepare' | null>(null);
  const [ack, setAck] = useState(false); const [command, setCommand] = useState<Publication | null>(null);
  const read = useCallback(async () => { const [active, releases, incoming, uploads] = await Promise.all([client.corpusStatus(), client.publications(), client.incomingSources(), client.uploads()]);
    return { active, releases, incoming: [...incoming, ...uploads.filter((r) => r.source_type !== 'notification').map((r) => ({ ...r, identity: r.title, review_status: r.review_status as IncomingSource['review_status'] }))] }; }, [client]);
  const load = useCallback(async () => { const data = await read(); setCorpus(data.active); setRows(data.releases); setSources(data.incoming); }, [read]);
  useEffect(() => { let live = true; read().then((data) => { if (live) { setCorpus(data.active); setRows(data.releases); setSources(data.incoming); } }).catch((e) => { if (live) setError(errorMessage(e)); }).finally(() => { if (live) setLoading(false); }); return () => { live = false; }; }, [read]);
  async function refresh() { setBusy(true); setError(''); try { await load(); setSelected([]); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  async function execute(e: FormEvent) {
    e.preventDefault(); if (!corpus || !confirm || busy || !ack) return; setBusy(true); setError('');
    try {
      if (confirm === 'prepare') { const publication = await client.preparePublication(selected, corpus.base_sha256); setNotice('Snapshot prepared privately. Verification and activation are still required.'); setCommand(publication); setSelected([]); }
      else { await client.activatePublication(confirm.id, corpus.base_sha256); setNotice('Verified snapshot activated for new queries. No answer was automatically approved.'); }
      setConfirm(null); await load();
    } catch (err) { setError(errorMessage(err)); setConfirm(null); } finally { setBusy(false); }
  }
  const approved = sources.filter((r) => r.review_status === 'approved');
  return <section className="ops-page"><div className="page-heading-row"><PageHeading eyebrow="ADMIN · CORPUS PUBLICATION" title="A deliberate release, not a silent update." subtitle="Source approval, index verification and activation are separate. The current corpus stays live until you switch it." /><button className="button secondary" disabled={busy} onClick={refresh}><RefreshCw size={15} />Refresh publications</button></div>
    <ErrorNotice error={error} />{notice && <div className="success-notice" role="status">{notice}</div>}
    {loading ? <Busy text="Loading corpus snapshots…" /> : <>
      <div className="ops-active-corpus"><span className="ops-live-dot" /><div><span className="eyebrow">CURRENT ACTIVE CORPUS</span><h2>{corpus ? `${corpus.records} records · ${corpus.sources} PDFs` : 'Unavailable'}</h2><p className="ops-digest">{corpus?.corpus_id}</p></div><span className="ops-status active">Serving new queries</span></div>
      <div className="publication-layout"><section className="panel publication-prepare"><div className="ops-section-title"><Plus size={19} /><h2>Prepare a snapshot</h2></div><p className="small muted">Choose up to 10 reviewed versions. Preparation keeps the current corpus active; already-published identities are rejected by the backend.</p>
        <fieldset disabled={busy} className="publication-selection"><legend>Approved source versions</legend>{approved.map((source) => <label className="check-label" key={source.id}><input type="checkbox" checked={selected.includes(source.id)} disabled={!selected.includes(source.id) && selected.length >= 10} onChange={(e) => setSelected(e.target.checked ? [...selected, source.id] : selected.filter((id) => id !== source.id))} /><span><strong>{source.identity}</strong><small>Version {source.sha256.slice(0, 10)} · Review r{source.revision}</small></span></label>)}{!approved.length && <p className="small muted">No approved sources yet. Start in Incoming notifications.</p>}</fieldset>
        <button className="button primary" disabled={busy || !corpus || !selected.length} onClick={() => { setAck(false); setConfirm('prepare'); }}><Layers3 size={16} />Prepare selected sources ({selected.length})</button>
      </section><div className="publication-guide"><span className="eyebrow">THE RELEASE PATH</span><ol><li><strong>Prepare</strong><p>Bind approved sources to the current corpus digest.</p></li><li><strong>Verify on the backend</strong><p>Run the explicit operator command. This can call Jina/Pinecone; it never runs in this browser.</p></li><li><strong>Activate</strong><p>Switch only a verified snapshot with a matching base. Existing approved answers are retained.</p></li></ol><div className="ops-coverage"><ShieldAlert size={17} /><span>Verification checks the snapshot and vectors, not legal correctness or complete GST coverage.</span></div></div></div>
      <div className="ops-section-title publication-list-title"><h2>Publication history</h2><span className="small muted">Most recent 50 snapshots</span></div><div className="publication-list">{rows.map((row) => <article className="publication-card" key={row.id}><div className="publication-card-heading"><span className="ops-publication-symbol"><GitBranch size={21} /></span><div><OpsStatus status={row.state} /><h3 title={row.id}>Snapshot {row.id.slice(0, 12)}</h3><p className="small muted">{dateLabel(row.created_at)} · {row.mode || 'Not verified'}{row.index_name ? ` · ${row.index_name}` : ''}</p></div></div>
        {row.error && <p className="small warning-text">Verification did not complete. Inspect the backend before retrying.</p>}
        {corpus && row.base_sha256 !== corpus.base_sha256 && !['active', 'superseded'].includes(row.state) && <p className="small warning-text">Stale base · prepare a fresh snapshot against the active corpus.</p>}
        <div className="button-row"><button className="button secondary" onClick={() => setCommand(row)}>Verification instructions</button><button className="button primary" disabled={busy || row.state !== 'verified' || !corpus || row.base_sha256 !== corpus.base_sha256} onClick={() => { setAck(false); setConfirm(row); }}><CheckCheck size={16} />Activate snapshot</button></div><p className="small muted">{row.state === 'verified' ? 'Activation rechecks the current backend and source integrity.' : row.state === 'active' ? 'This snapshot has been activated.' : 'Activation is unavailable until backend verification succeeds.'}</p>
      </article>)}{!rows.length && <Empty title="No snapshots prepared yet." text="Approve a source, then prepare a candidate here. Nothing is switched automatically." />}</div>
    </>}
    {confirm && <Modal title={confirm === 'prepare' ? 'Confirm snapshot preparation' : 'Confirm corpus activation'} onClose={() => { if (!busy) setConfirm(null); }}><form className="modal-body stack" onSubmit={execute}><p>{confirm === 'prepare' ? `Prepare ${selected.length} source version(s) against the displayed active corpus. This creates a private candidate; it does not index or activate it.` : `Activate verified snapshot ${confirm.id.slice(0, 12)} for new questions. The backend rechecks its base and verification. Previous approved answers remain unchanged.`}</p><label className="check-label"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /><span>I understand this is a corpus operation, not approval of any answer or legal precedence.</span></label><div className="button-row"><button type="button" disabled={busy} className="button secondary" onClick={() => setConfirm(null)}>Cancel</button><button disabled={busy || !ack} className="button primary">{confirm === 'prepare' ? 'Confirm preparation' : 'Confirm activation'}</button></div></form></Modal>}
    {command && <Modal title="Backend verification instructions" onClose={() => setCommand(null)}><div className="modal-body stack"><p>Run on the trusted backend with its configured retrieval mode. Dry run first; only add <code>--apply</code> after checking it. This UI does not execute shell commands or collect provider keys.</p><code className="ops-command">python -m gst_rag.notification_publication index {command.id} --mode {'<bm25|jina|pinecone>'}</code><p className="small muted">Use the same mode as GST_RETRIEVER. For Pinecone, use the configured index name. The --apply run may incur provider usage. Return here and refresh after verification; activation stays explicit.</p>{client.sample && <div className="info-notice">Sample IDs are illustrative. Do not run this sample command against your real backend.</div>}<button className="button secondary" onClick={() => setCommand(null)}>Back to publications</button></div></Modal>}
  </section>;
}

export function ImportDesk({ client }: { client: Client }) {
  const [status, setStatus] = useState<SyncStatus | null>(null); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false); const [confirm, setConfirm] = useState(false); const [loading, setLoading] = useState(true);
  const key = useRef<string | null>(null); const alive = useRef(true);
  useEffect(() => { let live = true; let running = false; alive.current = true;
    const poll = async () => { if (running) return; running = true; try { const next = await client.syncStatus(); if (live) setStatus(next); } catch (e) { if (live) setError(errorMessage(e)); } finally { running = false; if (live) setLoading(false); } };
    poll(); const timer = window.setInterval(poll, 5000); return () => { live = false; alive.current = false; clearInterval(timer); };
  }, [client]);
  async function refresh() { setError(''); try { const next = await client.syncStatus(); if (alive.current) setStatus(next); } catch (e) { if (alive.current) setError(errorMessage(e)); } }
  async function trigger(e: FormEvent) {
    e.preventDefault(); if (busy) return; setBusy(true); setError(''); key.current ||= `admin:${crypto.randomUUID()}`;
    try { const job = await client.triggerSync(key.current); if (!alive.current) return; key.current = null; setConfirm(false);
      setNotice(client.sample ? 'Sample import recorded in this tab only. No PDF was downloaded or parsed.' : `Import ${job.id.slice(0, 8)} accepted. Completion means private staging, not publication.`); await refresh();
    } catch (err) { if (alive.current) { setError(errorMessage(err)); setConfirm(false); } } finally { if (alive.current) setBusy(false); }
  }
  const active = status?.jobs.some((j) => ['queued', 'running'].includes(j.status));
  return <section className="ops-page"><div className="page-heading-row"><PageHeading eyebrow="ADMIN · NOTIFICATION IMPORTS" title="Keep the incoming tray moving." subtitle="Request a bounded import or inspect its outcome. Parsing happens on the backend, never in this browser." /><button className="button secondary" onClick={refresh}><RefreshCw size={15} />Refresh imports</button></div>
    <ErrorNotice error={error} />{notice && <div className="success-notice" role="status">{notice}</div>}
    {loading ? <Busy text="Checking the import worker…" /> : <>
      <div className="import-control"><span className="ops-import-symbol"><Download size={30} strokeWidth={1.4} /></span><div><span className="eyebrow">HOSTED BACKGROUND WORKER</span><h2>{status?.enabled ? status.worker_ready ? 'Ready for a deliberate check.' : 'The import worker is unavailable.' : 'Automatic collection is not enabled.'}</h2><p>{status ? `Up to ${status.max_documents} PDFs per job · ${status.max_pages} page(s) per listing · notification identity year ${status.since_year} onward` : 'Backend status unavailable.'}</p><p className="small muted">No sync secret or provider keys are entered here. Your current admin login authorizes this action.</p></div>
        <button className="button primary" disabled={busy || !status?.enabled || !status.worker_ready || active} onClick={() => setConfirm(true)}><Download size={16} />{active ? 'Import in progress' : key.current ? 'Retry import request' : 'Run bounded import'}</button></div>
      <div className="ops-coverage"><ShieldAlert size={18} /><span>Only two partial official-mirror feeds: Central Tax and Central Tax (Rate). A completed job does not prove current law or comprehensive coverage. The GitHub schedule is configured separately; worker readiness does not prove it is enabled.</span></div>
      <div className="ops-section-title publication-list-title"><h2>Import history</h2><span className="small muted">Latest 30 hosted jobs · refreshes every 5 seconds</span></div><div className="import-history">{status?.jobs.map((job) => <article className="import-job" key={job.id}><div className="import-job-heading"><div><OpsStatus status={job.status} /><h3>Import {job.id.slice(0, 8)}</h3><span className="small muted">{dateLabel(job.created_at)} · {job.attempts} attempt(s){job.finished_at ? ` · Finished ${dateLabel(job.finished_at)}` : ''}</span></div><Clock3 size={20} /></div>
        {job.result && <><dl className="import-counts"><div><dt>New PDFs</dt><dd>{job.result.downloaded_new_versions}</dd></div><div><dt>Staged</dt><dd>{job.result.staged_versions}</dd></div><div><dt>Unchanged</dt><dd>{job.result.unchanged_versions}</dd></div><div><dt>Deferred PDFs</dt><dd>{job.result.deferred_documents}</dd></div><div><dt>Errors</dt><dd>{job.result.error_count}</dd></div></dl><p className="small muted">{job.result.bounded_scan ? 'Bounded / incomplete listing scan' : 'Configured listing scan finished; overall coverage still partial'} · No corpus change · 0 published</p></>}
        {job.error && <p className="small warning-text">{job.error === 'importer_busy' ? 'The importer or publication storage was busy. Retry with a new import after it finishes.' : 'The import did not complete. Inspect the backend registry; no raw error content is shown here.'}</p>}
      </article>)}{!status?.jobs.length && <Empty title="No hosted imports recorded." text="Run a bounded import when the worker is configured. Older one-shot CLI runs are separate from this hosted-job history." />}</div>
    </>}
    {confirm && <Modal title="Run a bounded notification import?" onClose={() => { if (!busy) setConfirm(false); }}><form className="modal-body stack" onSubmit={trigger}><p>Check the configured official listings, download up to {status?.max_documents} PDFs and parse them into private staging. No source, vector snapshot or answer is automatically approved.</p><p className="small muted">Duplicate retries reuse this request key. A GitHub or browser timeout does not cancel a backend job.</p><div className="button-row"><button type="button" className="button secondary" disabled={busy} onClick={() => setConfirm(false)}>Cancel</button><button className="button primary" disabled={busy}>Confirm bounded import</button></div></form></Modal>}
  </section>;
}
