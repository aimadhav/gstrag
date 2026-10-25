import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, ArrowUpRight, FileCheck2, FileText, RefreshCw, ShieldCheck, UploadCloud } from 'lucide-react';
import { errorMessage } from './api';
import { OpsStatus } from './AdminIngestion';
import { SOURCE_LABELS, dateLabel } from './helpers';
import { Busy, Empty, ErrorNotice, Modal, PageHeading, useUnsavedChanges } from './ui';
import type { Client, Source, SourceType, UploadDetail, UploadedSource, UploadSpec } from './types';

export function UploadDesk({ client, initialTarget, onPdf, onNotification, onPublications, onDirtyChange }: {
  client: Client; initialTarget?: string | null; onPdf: (id: string, page: number) => void;
  onNotification: (id: string) => void; onPublications: () => void; onDirtyChange: (dirty: boolean) => void;
}) {
  const [sources, setSources] = useState<Source[]>([]); const [rows, setRows] = useState<UploadedSource[]>([]);
  const [target, setTarget] = useState(initialTarget || ''); const [kind, setKind] = useState<SourceType>('icai_book');
  const [title, setTitle] = useState(''); const [file, setFile] = useState<File | null>(null);
  const [series, setSeries] = useState(''); const [number, setNumber] = useState(''); const [year, setYear] = useState('');
  const [selected, setSelected] = useState<string | null>(null); const [detail, setDetail] = useState<UploadDetail | null>(null);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false); const [refreshKey, setRefreshKey] = useState(0); const [reason, setReason] = useState('');
  const [sourceChecked, setSourceChecked] = useState(false); const [structureChecked, setStructureChecked] = useState(false);
  const [decision, setDecision] = useState<'approve' | 'reject' | null>(null); const [pendingSource, setPendingSource] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null); const alive = useRef(true); const reviewDirty = Boolean(reason || sourceChecked || structureChecked);
  useUnsavedChanges(Boolean(file) || reviewDirty || busy, onDirtyChange);
  const refresh = useCallback(async () => { const list = await client.uploads(); if (alive.current) setRows(list); }, [client]);
  useEffect(() => {
    let live = true; let running = false; alive.current = true;
    client.sources().then((list) => { if (live) { setSources(list); const previous = list.find((s) => s.document_id === initialTarget); if (previous) { setKind(previous.source_type); setTitle(previous.name + ' (updated)'); } } }).catch((e) => { if (live) setError(errorMessage(e)); });
    const poll = async () => { if (running) return; running = true; try { const list = await client.uploads(); if (live) { setRows(list); setSelected((old) => old || list[0]?.id || null); } } catch (e) { if (live) setError(errorMessage(e)); } finally { running = false; if (live) setLoading(false); } };
    poll(); const timer = window.setInterval(poll, 3000); return () => { live = false; alive.current = false; clearInterval(timer); };
  }, [client, initialTarget]);
  const row = rows.find((r) => r.id === selected);
  useEffect(() => {
    let live = true; setDetail(null); setReason(''); setSourceChecked(false); setStructureChecked(false);
    if (!selected || row?.status !== 'pending_source_metadata_review') return;
    client.uploadDetail(selected).then((result) => { if (live) setDetail(result); }).catch((e) => { if (live) setError(errorMessage(e)); });
    return () => { live = false; };
  }, [client, selected, row?.status, refreshKey]);
  function choose(id: string) { if (id === selected) return; if (reviewDirty) setPendingSource(id); else { setSelected(id); setError(''); } }
  function chooseTarget(id: string) { setTarget(id); const previous = sources.find((s) => s.document_id === id); if (previous) { setKind(previous.source_type); setTitle(previous.name + ' (updated)'); } }
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file || busy) return; setBusy(true); setError(''); setNotice('');
    try {
      const spec: UploadSpec = { title, source_type: kind, replaces_document_id: target || null,
        ...(kind === 'notification' ? { series: series as UploadSpec['series'], number: Number(number), year: Number(year) } : {}) };
      const result = await client.uploadFile(file, spec); if (!alive.current) return;
      setFile(null); if (input.current) input.current.value = ''; setSelected(result.id); await refresh();
      setNotice(client.sample ? 'Sample upload recorded in this tab only. No file was sent or parsed.' : 'PDF received for private parsing. It is not in retrieval and no answer was approved.');
    } catch (e) { if (alive.current) setError(errorMessage(e)); } finally { if (alive.current) setBusy(false); }
  }
  async function retry(id: string) { setBusy(true); setError(''); try { await client.retryUpload(id); await refresh(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  async function review(event: FormEvent) {
    event.preventDefault(); if (!detail || !decision || busy) return; setBusy(true); setError('');
    try {
      await client.reviewBook(detail.id, { revision: detail.revision, stage_sha256: detail.stage_sha256!, action: decision, reason,
        source_checked: sourceChecked, structure_checked: structureChecked });
      if (!alive.current) return; setReason(''); setSourceChecked(false); setStructureChecked(false); setDecision(null); setRefreshKey((n) => n + 1);
      setNotice('Source decision recorded privately. Prepare, verify and activate a snapshot separately.'); await refresh();
    } catch (e) { if (alive.current) { setError(errorMessage(e)); setDecision(null); } } finally { if (alive.current) setBusy(false); }
  }
  return <section className="ops-page"><div className="page-heading-row"><PageHeading eyebrow="ADMIN · PDF INGESTION" title="New evidence, never a silent overwrite." subtitle="Upload a book or notification, inspect the parse, then deliberately publish. Previous editions stay available for historical citations." />
    <button className="button secondary" disabled={busy || reviewDirty} onClick={async () => { setError(''); try { await refresh(); setRefreshKey((n) => n + 1); setSources(await client.sources()); } catch (e) { setError(errorMessage(e)); } }}><RefreshCw size={15} />Refresh uploads</button></div>
    <ErrorNotice error={error} />{notice && <div className="success-notice" role="status">{notice}</div>}
    <div className="upload-layout"><form className="panel upload-form stack" onSubmit={upload}><div className="ops-section-title"><UploadCloud size={22} /><h2>Upload a PDF</h2></div>
      <fieldset disabled={busy} className="ops-form-fields"><label>Document operation<select value={target} onChange={(e) => chooseTarget(e.target.value)}><option value="">Add a new document</option>{sources.filter((s) => !s.archived).map((s) => <option key={s.document_id} value={s.document_id}>Replace: {s.name}</option>)}</select></label>
        {target && <div className="info-notice"><ShieldCheck size={18} /><span>The current PDF stays active until a verified replacement is activated. Its old PDF and citation identity are retained.</span></div>}
        <label>PDF source type<select value={kind} disabled={Boolean(target)} onChange={(e) => setKind(e.target.value as SourceType)}><option value="icai_book">ICAI book · Plus & Pro</option><option value="firm_book">Firm book · Pro only</option><option value="notification">GST notification · Plus & Pro</option></select></label>
        <label className="upload-file-field"><FileText size={28} strokeWidth={1.4} /><strong>Choose the original PDF</strong><span>25 MB maximum · 1–500 pages</span><input ref={input} type="file" accept="application/pdf,.pdf" aria-label="PDF file" required onChange={(e) => {
          const next = e.target.files?.[0] || null; setError('');
          if (next && (next.size > 25 * 1024 * 1024 || !next.size || !next.name.toLowerCase().endsWith('.pdf'))) { setFile(null); e.target.value = ''; setError('Choose a non-empty .pdf file no larger than 25 MB.'); return; }
          setFile(next); if (next && !title) setTitle(next.name.replace(/\.pdf$/i, '').slice(0, 160));
        }} />{file && <span>{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB</span>}</label>
        <label>Display title<input value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} maxLength={160} placeholder="Name and edition for the source library" /></label>
        {kind === 'notification' && <fieldset className="anchor-fields"><legend>Notification identity · checked against quotes later</legend><label>Notification series<select required value={series} onChange={(e) => setSeries(e.target.value)}><option value="">Choose series</option><option value="central_tax">Central Tax</option><option value="central_tax_rate">Central Tax (Rate)</option></select></label><div className="ops-date-grid"><label>Notification number<input type="number" min={1} max={999} required value={number} onChange={(e) => setNumber(e.target.value)} /></label><label>Notification year<input type="number" min={2000} max={2099} required value={year} onChange={(e) => setYear(e.target.value)} /></label></div><p className="small muted">Do not infer identity or effective dates from the filename. Corrigenda/complex effects need separate policy.</p></fieldset>}
        <p className="small muted">Text PDFs only for this version. Encrypted, active-content and oversized PDFs are rejected. No OCR, provider calls or automatic approval during upload.</p>
      </fieldset><button className="button primary" disabled={!file || busy}><UploadCloud size={17} />{busy ? 'Working privately…' : target ? 'Upload replacement privately' : 'Upload to private staging'}</button>
      <p className="small muted">SHA-256 binds the reservation to these exact bytes. Retrying the same file/settings reuses its reservation.</p>
    </form><div className="upload-review-area"><div className="ops-section-title"><h2>Upload history</h2><span className="small muted">Refreshes every 3 seconds</span></div>
      {loading ? <Busy text="Loading private uploads…" /> : <div className="upload-history">{rows.map((entry) => <button key={entry.id} className={`upload-history-row ${selected === entry.id ? 'selected' : ''}`} onClick={() => choose(entry.id)}><FileText size={18} /><span><strong>{entry.title}</strong><small>{SOURCE_LABELS[entry.source_type]} · {entry.replaces_document_id ? 'Replacement' : 'New document'} · {dateLabel(entry.created_at)}</small></span><OpsStatus status={entry.review_status || entry.status} /></button>)}{!rows.length && <Empty title="Your upload tray is clear." text="Choose a PDF on the left. Parsing will not change the active corpus." />}</div>}
      {row && !detail && <div className="panel upload-processing"><OpsStatus status={row.status} /><h3>{row.title}</h3><p>{row.status === 'awaiting_upload' ? 'Reserved, but PDF bytes have not been received. Select the same file and settings to retry the transfer.' : row.status === 'upload_parse_failed' ? 'Parsing failed. The source remains private. Inspect the PDF or retry the local parse; raw exception content is hidden.' : 'The PDF is queued or being parsed. This page will show the staged result when it is ready.'}</p>{row.status === 'upload_parse_failed' && <button className="button secondary" disabled={busy} onClick={() => retry(row.id)}>Retry private parse</button>}</div>}
      {detail && <div className="panel upload-detail"><div className="ops-source-heading"><div><OpsStatus status={detail.review_status || 'pending'} /><h2>{detail.title}</h2><p>{SOURCE_LABELS[detail.source_type]} · {detail.page_count} PDF page(s) · {detail.draft_chunks.length} draft chunks · Review r{detail.revision}</p></div><button className="button secondary" onClick={() => onPdf(detail.id, 1)}>Inspect uploaded PDF <ArrowUpRight size={15} /></button></div>
        {detail.warnings.map((warning, index) => <p key={index} className="upload-warning">{warning}</p>)}
        {detail.source_type === 'notification' ? <div className="info-notice"><FileCheck2 size={20} /><div><p>Notifications require exact identity/date anchors and complete operative clauses in the notification review screen.</p><button className="text-button" disabled={Boolean(file)} onClick={() => onNotification(detail.id)}>Review notification evidence <ArrowRight size={15} /></button></div></div> : <form className="stack book-review" onSubmit={(e) => { e.preventDefault(); setDecision('approve'); }}>
          <h3>Review the book parse</h3><p className="small muted">Check the original against these chunks, including headings, order, tables, diagrams, definitions, examples and exceptions. No case fields are forced.</p>
          <div className="upload-chunks">{detail.draft_chunks.map((chunk, i) => <details key={chunk.chunk_id} open={i === 0}><summary>Chunk {i + 1} · PDF p. {chunk.pages?.join(', ')} · {chunk.token_count} tokens</summary><div><p className="small muted">{chunk.headings?.join(' › ') || 'No heading detected'} · {chunk.plan_required === 'pro' ? 'Pro only' : 'Plus & Pro'}</p><p className="upload-chunk-text">{chunk.text}</p><p className="ops-digest">{chunk.source_refs?.join(', ')}</p></div></details>)}</div>
          <details className="ops-parse-details"><summary>Excluded furniture / cleanup candidates ({detail.excluded_items.length})</summary>{detail.excluded_items.map((item) => <p key={item.ref}>{item.ref} · p. {item.pages.join(', ')} · {item.reason}<br />{item.preview}</p>)}</details>
          <label>Book review note<textarea value={reason} onChange={(e) => setReason(e.target.value)} required minLength={5} maxLength={1000} rows={3} placeholder="What did you check? Record any limitations." /></label>
          <label className="check-label ops-attestation"><input type="checkbox" checked={sourceChecked} onChange={(e) => setSourceChecked(e.target.checked)} /><span>I inspected the original PDF and verified its source type/access label.</span></label>
          <label className="check-label ops-attestation"><input type="checkbox" checked={structureChecked} onChange={(e) => setStructureChecked(e.target.checked)} /><span>I checked structure, page provenance and completeness against the PDF, including cleanup exclusions.</span></label>
          {detail.over_token_budget > 0 && <div className="error-notice">{detail.over_token_budget} chunk(s) exceed the token budget. Approval is blocked; do not silently discard content.</div>}
          <div className="button-row"><button className="button primary" disabled={busy || !sourceChecked || !structureChecked || detail.over_token_budget > 0}>Approve book source</button><button type="button" className="button secondary" disabled={busy} onClick={() => setDecision('reject')}>Reject book source</button><button type="button" className="text-button" disabled={Boolean(file) || reviewDirty} onClick={onPublications}>Open publications <ArrowRight size={15} /></button></div>
        </form>}
      </div>}
    </div></div>
    {decision && detail && <Modal title={decision === 'approve' ? 'Confirm book source approval' : 'Reject book source'} onClose={() => { if (!busy) setDecision(null); }}><form className="modal-body stack" onSubmit={review}><p>{decision === 'approve' ? 'Approve the complete staged book parse, bound to this PDF and stage hash. It will remain private until separately prepared, verified and activated.' : 'Record a rejection. The source bytes remain stored; nothing is deleted or published.'}</p>{decision === 'reject' && <label>Rejection note<textarea required minLength={5} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} /></label>}<div className="button-row"><button type="button" className="button secondary" disabled={busy} onClick={() => setDecision(null)}>Keep reviewing</button><button className="button primary" disabled={busy}>{decision === 'approve' ? 'Confirm book approval' : 'Confirm book rejection'}</button></div></form></Modal>}
    {pendingSource && <Modal title="Discard book-review changes?" onClose={() => setPendingSource(null)}><div className="modal-body stack"><p>The review note and checkboxes have not been saved.</p><div className="button-row"><button className="button secondary" onClick={() => setPendingSource(null)}>Keep reviewing</button><button className="button primary" onClick={() => { setSelected(pendingSource); setPendingSource(null); }}>Discard changes</button></div></div></Modal>}
  </section>;
}
