import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowUp, ArrowUpRight, BookOpen, Check, ChevronRight, CircleCheck, CircleHelp, Clock3, Crown,
  Code2, FileText, History, House, Inbox, LibraryBig, LoaderCircle, LockKeyhole, LogOut, Menu, Plus,
  RefreshCw, Search, ShieldCheck, ShieldAlert, Users, X, LayoutDashboard, FileCheck2, GitBranch, Download, UploadCloud } from 'lucide-react';
import { ApiClient, ApiError, errorMessage } from './api';
import { SampleClient } from './sample';
import { clockLabel, conversations, dateLabel, initials, readableFlag, SOURCE_LABELS, statusLabel, TOPICS } from './helpers';
import type { AdminQuery, Citation, Client, Decision, Health, Plan, Query, Role, Source, User } from './types';
import { Busy, Empty, ErrorNotice, Modal, PageHeading, useUnsavedChanges } from './ui';
import { AdminOverview, ImportDesk, PublicationsDesk, SourceInbox } from './AdminIngestion';
import { UploadDesk } from './UploadDesk';

type View = 'workspace' | 'history' | 'reviews' | 'users' | 'sources' | 'admin' | 'incoming' | 'publications' | 'imports' | 'uploads';
const ADMIN_VIEWS: View[] = ['reviews', 'users', 'sources', 'admin', 'incoming', 'publications', 'imports', 'uploads'];
const VIEW_NAMES = { workspace: 'Workspace', history: 'Conversation history', reviews: 'Review inbox', users: 'People & access', sources: 'Source library', admin: 'Admin overview', incoming: 'Incoming notifications', publications: 'Corpus publications', imports: 'Import history', uploads: 'PDF uploads' };

function Brand() { return <span className="brand"><BookOpen size={29} strokeWidth={1.55} /><span>GST Research<span className="brand-sub">DOCUMENT WORKSPACE</span></span></span>; }
function PlanBadge({ plan }: { plan: Plan }) { return <span className={`plan-badge ${plan}`}>{plan === 'pro' ? 'Pro' : 'Plus'}</span>; }
function StateBadge({ status }: { status: string }) {
  const Icon = status === 'approved' ? CircleCheck : ['queued', 'processing'].includes(status) ? LoaderCircle : Clock3;
  return <span className={`state-badge ${status}`}><Icon size={14} className={status === 'processing' ? 'spin' : ''} />{statusLabel(status)}</span>;
}

function RecruiterDialog({ onClose }: { onClose: () => void }) {
  return <Modal title="For recruiters" className="recruiter-modal" onClose={onClose}>
    <div className="recruiter-hero"><span className="recruiter-stage"><span aria-hidden="true" />PROJECT IN PROGRESS</span>
      <h3>A closer look<br />at the build.</h3>
      <p>The technical walkthrough will be added after the project is complete.</p><Code2 className="recruiter-watermark" size={130} strokeWidth={0.8} aria-hidden="true" />
    </div>
    <div className="recruiter-outline"><div className="recruiter-outline-heading"><span className="eyebrow">WHAT’S PLANNED</span><span>Not published yet</span></div>
      <ol><li><span className="outline-number" aria-hidden="true">01</span><div><strong>System architecture</strong><span>How the pieces fit together</span></div><Clock3 size={16} aria-hidden="true" /></li>
        <li><span className="outline-number" aria-hidden="true">02</span><div><strong>Retrieval decisions</strong><span>Chunking choices and the trade-offs</span></div><Clock3 size={16} aria-hidden="true" /></li>
        <li><span className="outline-number" aria-hidden="true">03</span><div><strong>Evaluation & lessons</strong><span>Measured results, including limitations</span></div><Clock3 size={16} aria-hidden="true" /></li></ol>
    </div>
    <div className="recruiter-footer"><span>Still building.<br /><strong>Verified results, when it’s ready.</strong></span><button className="button primary" onClick={onClose}>Back to project <ArrowUpRight size={16} /></button></div>
  </Modal>;
}

function Login({ client, notice, onLogin, onPreview, onRecruiter }: { client: Client; notice: string; onLogin: (user: User) => void; onPreview: (role: Role, plan?: Plan) => void; onRecruiter: () => void }) {
  const [username, setUsername] = useState(''); const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try { const user = await client.login(username, password); setPassword(''); onLogin(user); }
    catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  return <main className="login-page">
    <section className="login-story"><Brand /><div className="login-story-body"><span className="eyebrow">EVIDENCE FIRST. HUMAN REVIEWED.</span>
      <h1>Clarity for your<br />GST questions.</h1><p>A considered workspace for your books, notifications and the answers that connect them.</p>
      <div className="login-proof"><span><BookOpen size={19} />Evidence-backed research</span><span><ShieldCheck size={19} />Human-reviewed answers</span><span><LockKeyhole size={19} />A private workspace</span></div>
    </div><p className="login-footnote">A research assistant, not a substitute for professional tax advice.</p></section>
    <section className="login-panel"><div className="login-form-wrap"><span className="eyebrow">YOUR RESEARCH WORKSPACE</span><h2>Welcome back.</h2><p className="muted">Sign in with the account your admin created.</p>
      <form onSubmit={submit} className="stack"><label>Username<input name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} maxLength={64} placeholder="Your username" /></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={12} maxLength={256} placeholder="Your password" /></label>
        <ErrorNotice error={error || notice} /><button className="button primary full" disabled={busy}>{busy ? <LoaderCircle size={17} className="spin" /> : <ArrowUpRight size={18} />}Sign in to workspace</button>
      </form>
      <p className="small muted login-admin-note">No public sign-up. An admin assigns your Plus or Pro plan.</p>
      <div className="preview-invite"><span className="eyebrow">JUST EXPLORING?</span><h3>Take a look around.</h3><p>Open an isolated sample interface. No account, API key or real tax answers.</p>
        <div className="button-row"><button className="button secondary" onClick={() => onPreview('user')}>Preview workspace <ArrowUpRight size={15} /></button><button className="text-button" onClick={() => onPreview('admin')}>Admin preview</button></div>
      </div>
      <p className="small muted">Refreshing this page signs you out.</p>
      <button className="recruiter-entry" aria-label="Recruiter?" onClick={onRecruiter}><span className="recruiter-entry-icon"><Code2 size={19} /></span><span><strong>Recruiter?</strong><small>A look behind the build · coming later</small></span><ArrowUpRight size={17} /></button>
    </div></section>
  </main>;
}

export function AnswerText({ text }: { text: string }) {
  return <div className="answer-text">{text.split(/\n\s*\n/).map((block, index) => {
    const lines = block.trim().split('\n');
    const heading = /^(Book explanation|Latest notification.*|Practical effect|Limitations)$/.test(lines[0]);
    return <section key={index}>{heading && <h3>{lines.shift()}</h3>}{lines.map((line, i) => <p key={i}>{line}</p>)}</section>;
  })}</div>;
}

function CitationChips({ citations }: { citations: Citation[] }) {
  return <div className="citation-chips">{citations.map((c) => <span className="citation-chip" key={c.citation_id} title={c.source_name}>
    <FileText size={14} /><span><strong>{c.citation_id}</strong> {SOURCE_LABELS[c.source_type]} · p. {c.pages.join(', ')}</span>
  </span>)}</div>;
}

export function QueryCard({ query, username }: { query: Query; username: string }) {
  // A pending response must never be rendered as an answer, even if it has extra fields.
  const approved = query.status === 'approved' && Boolean(query.answer);
  return <article className="query-pair">
    <div className="question-line"><span className="avatar small-avatar">{initials(username)}</span><div className="question-bubble"><p>{query.question}</p><time dateTime={query.created_at}>{clockLabel(query.created_at)}</time></div></div>
    <div className={`answer-card ${approved ? '' : 'pending-card'}`}>
      <div className="answer-top"><div className="answer-identity"><span className="answer-symbol"><BookOpen size={17} strokeWidth={1.6} /></span><span>{approved ? 'Research response' : 'Research request'}</span></div><StateBadge status={query.status} /></div>
      {approved ? <><AnswerText text={query.answer!} /><div className="answer-bottom"><CitationChips citations={query.citations} /><span className="small muted">PDF access is admin-only</span></div></>
        : <div className="pending-body"><span className="pending-icon"><ShieldCheck size={25} /></span><div><h3>{query.status === 'clarification_required' ? 'A little more context is needed.' : query.status === 'safe_refusal' ? 'No supported answer to share.' : 'Your question is in good hands.'}</h3>
          <p>{query.message}</p>{['pending_review', 'processing', 'queued'].includes(query.status) && <p className="small muted">Source excerpts and drafts stay private. An answer appears here only after admin approval.</p>}</div></div>}
    </div>
  </article>;
}

function ResearchContext({ user, health }: { user: User; health: Health | null }) {
  return <aside className="research-context" aria-label="Your workspace"><h2>Your workspace</h2><div className="access-card"><Crown size={21} /><div><strong>{user.plan === 'pro' ? 'Pro' : 'Plus'} access</strong><p>Your plan is managed by your administrator.</p></div></div>
    <div className="review-note"><ShieldAlert size={22} /><div><strong>Review-first workflow</strong><p>Every answer is checked by an admin before it appears in your workspace.</p></div></div>
    <div className="context-fineprint"><span className="eyebrow">A FEW THINGS TO KNOW</span><p>The loaded sample is not a complete or current GST law corpus.</p><p>Approved answers remain available for 30 days, including after a plan downgrade.</p></div>
    {user.role === 'admin' && health && <div className="runtime-status"><span className="status-dot" /><div><strong>{health.retriever === 'sample only' ? 'Interface preview' : `${health.retriever === 'pinecone' ? 'Pinecone' : health.retriever.toUpperCase()} retrieval`}</strong><p>{health.generation === 'not_configured' ? 'Manual drafting · no Gemini key' : readableFlag(health.generation)}</p></div></div>}
  </aside>;
}

function Composer({ client, parent, sample, onSent }: { client: Client; parent: Query | null; sample: boolean; onSent: (query: Query) => void }) {
  const [question, setQuestion] = useState(''); const [date, setDate] = useState(parent?.as_of || (sample ? '2023-03-01' : ''));
  const [topic, setTopic] = useState(parent?.topic_ids[0] || 'other_gst'); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e: FormEvent) {
    e.preventDefault(); if (!question.trim() || busy) return;
    setBusy(true); setError('');
    try { const row = await client.submit({ question: question.trim(), as_of: date, topic_ids: [topic], ...(parent ? { parent_query_id: parent.id } : {}) }); setQuestion(''); onSent(row); }
    catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  return <div className="composer-wrap"><form className="composer" onSubmit={submit}><label className="sr-only" htmlFor="question">GST question</label>
    <textarea id="question" name="question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={parent ? 'Ask a follow-up — include the relevant facts…' : 'Ask a question about GST…'} required maxLength={4000} rows={2} />
    <div className="composer-controls"><label><span>Transaction date</span><input aria-label="Transaction date" type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
      <label><span>Topic</span><select aria-label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)}>{TOPICS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <button className="send-button" type="submit" aria-label="Send question" disabled={busy || !question.trim()}>{busy ? <LoaderCircle size={23} className="spin" /> : <ArrowUp size={23} />}</button></div>
  </form><ErrorNotice error={error} /><p className="composer-caption"><ShieldCheck size={14} />Answers appear only after admin approval.<span>{question.length}/4,000</span></p></div>;
}

function HistoryView({ rows, onSelect }: { rows: Query[]; onSelect: (id: string) => void }) {
  const [search, setSearch] = useState(''); const grouped = conversations(rows).filter((g) => g.rows.some((r) => r.question.toLowerCase().includes(search.toLowerCase())));
  return <section className="content-page"><PageHeading eyebrow="YOUR RESEARCH" title="A record of your questions." subtitle="Revisit approved answers, follow up, and keep track of pending reviews." />
    <label className="search-input"><Search size={18} /><input aria-label="Search conversations" placeholder="Search your questions…" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
    <div className="history-list">{grouped.map((g) => <button key={g.id} className="history-item" onClick={() => onSelect(g.id)}><span className="file-icon"><FileText size={22} /></span><span className="history-copy"><strong>{g.title}</strong><span>{dateLabel(g.latest.created_at)} · {g.rows.length} {g.rows.length === 1 ? 'question' : 'questions'}</span></span><StateBadge status={g.latest.status} /><ChevronRight size={18} /></button>)}</div>
    {!grouped.length && <Empty title="No conversations found." text={search ? 'Try a different search.' : 'Your first question starts a new conversation.'} />}
  </section>;
}

function ReviewDesk({ client, onPdf, onDirtyChange }: { client: Client; onPdf: (id: string, page: number) => void; onDirtyChange: (dirty: boolean) => void }) {
  const [rows, setRows] = useState<AdminQuery[]>([]); const [current, setCurrent] = useState<AdminQuery | null>(null);
  const [draft, setDraft] = useState(''); const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true); const [confirmation, setConfirmation] = useState<Decision['action'] | null>(null); const [publicMessage, setPublicMessage] = useState('');
  const dirty = current && draft !== (current.draft_text || '');
  useUnsavedChanges(Boolean(dirty), onDirtyChange);
  const [search, setSearch] = useState(''); const [riskFilter, setRiskFilter] = useState('all');
  const visible = rows.filter((row) => row.question.toLowerCase().includes(search.toLowerCase()) && (riskFilter === 'all'
    || (riskFilter === 'no_evidence' ? !row.packet?.citations?.length : row.packet?.citations?.some((c) => c.source_type === 'firm_book'))));
  const receive = (row: AdminQuery) => { setCurrent(row); setDraft(row.draft_text || ''); setSelected(row.packet?.generation_details?.citation_ids || []); };
  useEffect(() => { let active = true; client.reviews().then((list) => { if (active) { setRows(list); if (list[0]) receive(list[0]); } }).catch((e) => { if (active) setError(errorMessage(e)); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [client]);
  async function open(id: string) {
    if (dirty) { setError('Save or reset the current draft before opening another review.'); return; }
    setBusy(true); setError(''); setNotice('');
    try { receive(await client.review(id)); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function refresh() {
    if (dirty) { setError('Save or reset the current draft before refreshing.'); return; }
    setBusy(true); setError('');
    try { const list = await client.reviews(); setRows(list); if (current && list.some((r) => r.id === current.id)) receive(await client.review(current.id)); else if (list[0]) receive(list[0]); else setCurrent(null); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function save() {
    if (!current) return; setBusy(true); setError(''); setNotice('');
    try { const row = await client.saveDraft(current.id, current.revision, draft); setCurrent(row); setDraft(row.draft_text || ''); setNotice('Draft saved privately. Nothing has been published.'); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function decide(e: FormEvent) {
    e.preventDefault(); if (!current || !confirmation) return; setBusy(true); setError('');
    try {
      const approval = confirmation === 'approve';
      await client.decide(current.id, { revision: current.revision, action: approval && dirty ? 'edit_and_approve' : confirmation,
        ...(approval && dirty ? { text: draft } : !approval ? { text: publicMessage } : {}), citation_ids: approval ? selected : [] });
      setConfirmation(null); setNotice(approval ? 'Answer approved and released to the requester.' : 'Decision sent to the requester.');
      setCurrent(null); setDraft(''); setRows(await client.reviews());
    } catch (err) { setError(errorMessage(err)); setConfirmation(null); } finally { setBusy(false); }
  }
  async function reprocess() {
    if (!current || dirty) { setError('Save or reset draft changes before reprocessing.'); return; }
    setBusy(true); setError('');
    try { const result = await client.reprocess(current.id, current.revision); setNotice('Question requeued using the user’s current plan. Refresh the inbox shortly.'); setRows(rows.filter((r) => r.id !== result.id)); setCurrent(null); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <section className="admin-page"><div className="page-heading-row"><PageHeading eyebrow="ADMIN WORKSPACE" title="Considered answers start here." subtitle="Inspect the evidence. Check the meaning. Publish only what you can support." />
    <button className="button secondary" onClick={refresh} disabled={busy}><RefreshCw size={15} />Refresh inbox</button></div>
    <ErrorNotice error={error} />{notice && <div className="success-notice" role="status"><CircleCheck size={17} />{notice}</div>}
    <div className="ops-toolbar"><label className="ops-search">Search pending questions<input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a question to review" /></label><label>Evidence filter<select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}><option value="all">All pending reviews</option><option value="no_evidence">No retrieved evidence</option><option value="firm">Includes firm-book evidence</option></select></label><span className="small muted">{visible.length} of {rows.length} pending reviews</span></div>
    {loading ? <Busy text="Loading private reviews…" /> : <div className="review-grid"><aside className="review-list"><h2>Pending reviews <span>{rows.length}</span></h2>
      {visible.map((row) => <button key={row.id} className={`review-list-item ${current?.id === row.id ? 'active' : ''}`} onClick={() => open(row.id)} disabled={busy}><span className="small muted">{row.plan_at_retrieval?.toUpperCase()} · {dateLabel(row.as_of)}</span><strong>{row.question}</strong><span className="small">Review required <ChevronRight size={14} /></span></button>)}
      {!visible.length && <p className="muted small">{rows.length ? 'No questions match these filters.' : 'Your inbox is clear.'}</p>}</aside>
      {current ? <div className="review-detail"><div className="review-question"><StateBadge status={current.status} /><h2>{current.question}</h2><p className="small muted">Transaction: {dateLabel(current.as_of)} · Retrieval plan: {current.plan_at_retrieval} · Revision {current.revision}</p></div>
        <div className="review-risk"><ShieldAlert size={18} /><div><strong>Human judgment is still required.</strong><p>Quoted-span checks do not prove that a legal conclusion follows from the source.</p></div></div>
        <div className="flag-list">{(current.packet?.review_reasons || []).map((reason) => <span className="flag" key={reason}>{readableFlag(reason)}</span>)}</div>
        <div className="evidence-header"><h3>Retrieved evidence</h3><span className="small muted">Admin-only excerpts & PDFs</span></div>
        <div className="evidence-list">{(current.packet?.citations || []).map((c) => <details key={c.citation_id} className="evidence-card"><summary><span className="source-id">{c.citation_id}</span><span><strong>{c.source_name}</strong><span className="small muted">{SOURCE_LABELS[c.source_type]} · PDF p. {c.pages.join(', ')}</span></span><ChevronRight size={16} /></summary>
          <div className="evidence-content"><p>{c.excerpt}</p>{c.truncated_for_budget && <p className="small warning-text">Excerpt truncated for context budget. Inspect the PDF.</p>}<button className="text-button" onClick={() => onPdf(c.document_id, c.pages[0])}><FileText size={15} />View PDF source <ArrowUpRight size={14} /></button></div>
        </details>)}</div>
        {!current.packet?.citations?.length && <div className="info-notice">No evidence was retrieved. Reprocess, request clarification, or refuse; do not invent an answer.</div>}
        <div className="draft-header"><label htmlFor="admin-draft">Answer draft <span>PRIVATE UNTIL APPROVED</span></label>{dirty && <span className="small warning-text">Unsaved changes</span>}</div>
        <p className="small muted generation-note">{readableFlag(current.packet?.generation || 'not_configured')}</p>
        <textarea id="admin-draft" className="draft-editor" rows={13} maxLength={16000} value={draft} onChange={(e) => { setDraft(e.target.value); setNotice(''); }} placeholder="Write a source-supported answer. Separate the book explanation, loaded notification and practical effect. Use [S1] references. No PDF URLs." />
        <fieldset className="citation-selection"><legend>Sources to include in the approved answer</legend><p className="small muted">Select every source cited in the text. User citations include names and pages, never PDF links.</p>
          {(current.packet?.citations || []).map((c) => <label className="check-label" key={c.citation_id}><input type="checkbox" checked={selected.includes(c.citation_id)} onChange={(e) => setSelected(e.target.checked ? [...selected, c.citation_id] : selected.filter((id) => id !== c.citation_id))} /><span><strong>{c.citation_id}</strong> {c.source_name} · p. {c.pages.join(', ')}</span></label>)}
        </fieldset>
        <div className="review-actions"><button className="button secondary" onClick={save} disabled={busy || !draft.trim()}>Save private draft</button><button className="button primary" disabled={busy || !draft.trim() || !selected.length} onClick={() => { setPublicMessage(''); setConfirmation('approve'); }}><Check size={17} />Approve answer</button>
          <button className="text-button" disabled={busy} onClick={() => { setPublicMessage(current.packet?.generated_answer?.clarification_question || ''); setConfirmation('request_clarification'); }}>Ask for clarification</button><button className="text-button danger-text" disabled={busy} onClick={() => { setPublicMessage(''); setConfirmation('refuse'); }}>Refuse safely</button></div>
        <div className="review-utility"><button className="text-button" disabled={busy} onClick={reprocess}><RefreshCw size={14} />Reprocess with current access</button>{dirty && <button className="text-button" onClick={() => setDraft(current.draft_text || '')}>Reset draft changes</button>}</div>
      </div> : <Empty title="A little care goes a long way." text="Choose a pending question to inspect its sources and prepare an answer." />}</div>}
    {confirmation && <Modal title={confirmation === 'approve' ? 'Confirm approval' : confirmation === 'refuse' ? 'Confirm safe refusal' : 'Request clarification'} onClose={() => setConfirmation(null)}><form onSubmit={decide} className="stack modal-body"><p>{confirmation === 'approve' ? `This publishes the ${dirty ? 'edited ' : ''}answer with ${selected.length} selected source(s) to the requester. Have you checked its meaning, dates and exceptions?` : 'Only the public message below will be sent. The draft and evidence remain private.'}</p>
      {confirmation !== 'approve' && <label>Public message<textarea rows={4} value={publicMessage} onChange={(e) => setPublicMessage(e.target.value)} required maxLength={16000} /></label>}
      <div className="button-row"><button type="button" className="button secondary" onClick={() => setConfirmation(null)}>Keep reviewing</button><button className="button primary" disabled={busy}>{confirmation === 'approve' ? 'Confirm approval' : 'Send decision'}</button></div></form></Modal>}
  </section>;
}

function People({ client, onSelfChange }: { client: Client; onSelfChange: () => void }) {
  const [rows, setRows] = useState<User[]>([]); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false); const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [plan, setPlan] = useState<Plan>('plus');
  useEffect(() => { let active = true; client.users().then((r) => { if (active) setRows(r); }).catch((e) => { if (active) setError(errorMessage(e)); }); return () => { active = false; }; }, [client]);
  async function create(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try { const user = await client.createUser(username, password, plan); setRows([...rows, user]); setPassword(''); setUsername(''); setNotice(`Account created for ${user.username}. Share credentials outside this application.`); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function change(id: string, next: Plan) {
    setBusy(true); setError(''); setNotice('');
    try { const user = await client.setPlan(id, next); setRows(rows.map((u) => u.id === id ? user : u)); onSelfChange(); setNotice(`Plan updated for ${user.username}. New questions use ${next === 'pro' ? 'Pro' : 'Plus'} access; approved history is retained.`); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <section className="content-page"><PageHeading eyebrow="ADMIN · MANUAL PLANS" title="The right access, deliberately." subtitle="Create researcher accounts and assign Plus or Pro. Plans and admin roles are separate." /><ErrorNotice error={error} />{notice && <div className="success-notice" role="status">{notice}</div>}
    <div className="people-grid"><div className="panel"><h2>Researcher accounts</h2><p className="small muted">Showing up to 100 accounts from the API.</p><div className="people-list">{rows.map((user) => <div className="person-row" key={user.id}><span className="avatar">{initials(user.username)}</span><div><strong>{user.username}</strong><p className="small muted">{user.role === 'admin' ? 'Administrator' : 'Researcher'}</p></div><label className="sr-only" htmlFor={`plan-${user.id}`}>Plan for {user.username}</label><select id={`plan-${user.id}`} value={user.plan} disabled={busy} onChange={(e) => change(user.id, e.target.value as Plan)}><option value="plus">Plus</option><option value="pro">Pro</option></select></div>)}</div></div>
    <form className="panel stack create-account" onSubmit={create}><h2>Create an account</h2><label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={64} pattern="[a-zA-Z0-9_.-]+" required autoComplete="off" placeholder="e.g. research.user" /></label><label>Initial password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={12} maxLength={256} required autoComplete="new-password" placeholder="At least 12 characters" /></label><label>Access plan<select value={plan} onChange={(e) => setPlan(e.target.value as Plan)}><option value="plus">Plus · ICAI + notifications</option><option value="pro">Pro · adds firm books</option></select></label><p className="small muted">This creates a researcher, never an admin. Passwords are not displayed after creation.</p><button className="button primary" disabled={busy}>Create researcher</button></form></div>
  </section>;
}

function Library({ client, onPdf, onUpload }: { client: Client; onPdf: (id: string, page: number) => void; onUpload: (target?: string) => void }) {
  const [rows, setRows] = useState<Source[]>([]); const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  useEffect(() => { let active = true; client.sources().then((r) => { if (active) setRows(r); }).catch((e) => { if (active) setError(errorMessage(e)); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [client]);
  return <section className="content-page"><PageHeading eyebrow="ADMIN · REGISTERED DOCUMENTS" title="Know what’s behind the answer." subtitle="Inspect registered source PDFs and their access labels. Source viewing is admin-only." /><ErrorNotice error={error} />
    <div className="info-notice"><LibraryBig size={19} /><span>Uploads are staged privately. Replacements retain previous PDFs for historical citations.</span><button className="text-button" onClick={() => onUpload()}>Upload or replace a PDF <ArrowUpRight size={15} /></button></div>
    {loading ? <Busy text="Loading source library…" /> : <div className="library-list">{rows.map((source) => <div key={source.document_id} className="library-item"><span className="file-icon"><BookOpen size={23} /></span><div className="library-copy"><h3>{source.name}</h3><p className="small muted">{SOURCE_LABELS[source.source_type]} · Original PDF: {source.page_count} pages · {source.archived ? 'Archived · historical citations only' : source.source_type === 'firm_book' ? 'Pro-only retrieval' : 'Plus & Pro retrieval'}</p></div><div className="button-row"><button className="button secondary" onClick={() => onPdf(source.document_id, 1)}>View PDF <ArrowUpRight size={15} /></button>{!source.archived && <button className="text-button" aria-label={`Replace ${source.name}`} onClick={() => onUpload(source.document_id)}>Replace PDF</button>}</div></div>)}</div>}
  </section>;
}

function WorkspaceApp({ client, user, onUser, onLogout, onPreview, onRecruiter }: { client: Client; user: User; onUser: (u: User) => void; onLogout: () => void; onPreview: (role: Role, plan?: Plan) => void; onRecruiter: () => void }) {
  const [view, setView] = useState<View>(user.role === 'admin' ? 'reviews' : 'workspace'); const [menu, setMenu] = useState(false);
  const [rows, setRows] = useState<Query[]>([]); const [selected, setSelected] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null); const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [help, setHelp] = useState(false); const [pdf, setPdf] = useState<{ url: string; page: number } | null>(null); const [pdfLoading, setPdfLoading] = useState(false);
  const [adminDirty, setAdminDirty] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<{ view: View; conversation?: string | null } | null>(null);
  const [uploadTarget, setUploadTarget] = useState<string | null>(null); const [incomingId, setIncomingId] = useState<string | null>(null);
  const loaded = useRef(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const refreshUser = useCallback(() => { client.me().then((u) => { if (alive.current) onUser(u); }).catch(() => {}); }, [client, onUser]);
  useEffect(() => {
    let active = true; let running = false;
    const load = async () => {
      if (running) return; running = true;
      try { const list = await client.queries(); if (!active) return; setRows(list); setError('');
        if (!loaded.current) { loaded.current = true; if (client.sample) setSelected(conversations(list)[0]?.id || null); }
      } catch (e) { if (active) setError(errorMessage(e)); } finally { running = false; if (active) setLoading(false); }
    };
    load(); const timer = window.setInterval(load, 5000);
    client.health().then((h) => { if (active) setHealth(h); }).catch(() => {});
    return () => { active = false; window.clearInterval(timer); };
  }, [client]);
  useEffect(() => { const timer = window.setInterval(refreshUser, 15000); return () => clearInterval(timer); }, [refreshUser]);
  useEffect(() => { if (user.role !== 'admin') { if (ADMIN_VIEWS.includes(view)) setView('workspace'); setPdf(null); setAdminDirty(false); setPendingNavigation(null); } }, [user.role, view]);
  useEffect(() => { window.scrollTo(0, 0); }, [view, selected]);
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf.url); }, [pdf]);
  const grouped = conversations(rows); const thread = grouped.find((g) => g.id === selected); const parent = thread?.rows[thread.rows.length - 1] || null;
  function applyNavigation(next: { view: View; conversation?: string | null }) { setView(next.view); if ('conversation' in next) setSelected(next.conversation ?? null); setMenu(false); setError(''); }
  function navigate(next: View, conversation?: string | null) {
    if (ADMIN_VIEWS.includes(next) && user.role !== 'admin') return;
    const destination = { view: next, ...(conversation !== undefined ? { conversation } : {}) };
    if (adminDirty && next !== view) { setPendingNavigation(destination); return; } applyNavigation(destination);
  }
  function choose(id: string) { navigate('workspace', id); }
  function newQuestion() { navigate('workspace', null); }
  async function openPdf(id: string, page: number, staged: boolean | 'upload' = false) {
    if (user.role !== 'admin') return; setPdfLoading(true); setError('');
    try { const blob = await (staged === 'upload' ? client.uploadedPdf(id) : staged ? client.stagedPdf(id) : client.pdf(id)); if (!alive.current) return; setPdf({ url: URL.createObjectURL(blob), page: Math.max(1, page || 1) }); }
    catch (e) { if (alive.current) setError(errorMessage(e)); } finally { if (alive.current) setPdfLoading(false); }
  }
  return <div className={`application ${menu ? 'menu-open' : ''}`}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    {client.sample && <div className="sample-banner"><span><strong>Interface preview</strong> · Sample data only. No API calls or tax advice.</span><label>Preview as<select aria-label="Preview as" value={user.role === 'admin' ? 'admin' : user.plan} onChange={(e) => onPreview(e.target.value === 'admin' ? 'admin' : 'user', e.target.value === 'plus' ? 'plus' : 'pro')}><option value="pro">Pro researcher</option><option value="plus">Plus researcher</option><option value="admin">Administrator</option></select></label><button onClick={onLogout}>Exit preview <X size={14} /></button></div>}
    {!client.sample && health?.generation === 'fixture_only' && <div className="sample-banner"><span><strong>API integration fixture</strong> · Real auth/review endpoints, synthetic evidence only. Temporary accounts; no provider calls.</span></div>}
    {menu && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMenu(false)} />}
    <aside className="sidebar"><Brand /><button className="button primary new-question" onClick={newQuestion}><Plus size={19} />New question</button>
      <nav aria-label="Main navigation"><button className={`nav-item ${view === 'workspace' ? 'active' : ''}`} onClick={() => navigate('workspace')}><House size={19} />Workspace</button><button className={`nav-item ${view === 'history' ? 'active' : ''}`} onClick={() => navigate('history')}><History size={19} />Conversation history</button>
        {user.role === 'admin' && <><span className="nav-label">ADMINISTRATION</span><button className={`nav-item ${view === 'admin' ? 'active' : ''}`} onClick={() => navigate('admin')}><LayoutDashboard size={19} />Admin overview</button><button className={`nav-item ${view === 'reviews' ? 'active' : ''}`} onClick={() => navigate('reviews')}><Inbox size={19} />Review inbox</button><button className={`nav-item ${view === 'uploads' ? 'active' : ''}`} onClick={() => navigate('uploads')}><UploadCloud size={19} />PDF uploads</button><button className={`nav-item ${view === 'incoming' ? 'active' : ''}`} onClick={() => navigate('incoming')}><FileCheck2 size={19} />Incoming notifications</button><button className={`nav-item ${view === 'publications' ? 'active' : ''}`} onClick={() => navigate('publications')}><GitBranch size={19} />Corpus publications</button><button className={`nav-item ${view === 'imports' ? 'active' : ''}`} onClick={() => navigate('imports')}><Download size={19} />Import history</button><button className={`nav-item ${view === 'users' ? 'active' : ''}`} onClick={() => navigate('users')}><Users size={19} />People & access</button><button className={`nav-item ${view === 'sources' ? 'active' : ''}`} onClick={() => navigate('sources')}><LibraryBig size={19} />Source library</button></>}
      </nav><div className="recent-heading"><span>RECENT CONVERSATIONS</span></div><div className="recent-list">{grouped.slice(0, 4).map((g) => <button key={g.id} className={`recent-item ${selected === g.id && view === 'workspace' ? 'selected' : ''}`} onClick={() => choose(g.id)}><FileText size={17} /><span><strong>{g.title}</strong><small>{dateLabel(g.latest.created_at)}</small></span></button>)}{!grouped.length && <p className="small muted">Your research history starts here.</p>}</div>
      <div className="sidebar-bottom"><div className="sidebar-links"><button className="text-button help-button" onClick={() => setHelp(true)}><CircleHelp size={17} />How this works</button><button className="recruiter-entry" aria-label="Recruiter?" onClick={() => { setMenu(false); onRecruiter(); }}><span className="recruiter-entry-icon"><Code2 size={18} /></span><span><strong>Recruiter?</strong><small>Behind the build · coming later</small></span><ArrowUpRight size={15} /></button></div><div className="profile"><span className="avatar">{initials(user.username)}</span><div><strong>{user.username}</strong><small>{user.role === 'admin' ? 'Administrator' : 'Researcher'}</small></div><PlanBadge plan={user.plan} /></div><button className="text-button logout-button" onClick={onLogout}><LogOut size={15} />{client.sample ? 'Exit sample preview' : 'Sign out'}</button></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div><button className="icon-button menu-toggle" aria-label="Open navigation" onClick={() => setMenu(true)}><Menu size={22} /></button><span className="breadcrumb">Research <span>/</span><strong>{VIEW_NAMES[view]}</strong></span></div><span className="topbar-assurance"><ShieldCheck size={17} />Human-reviewed answers</span></header>
      <main id="main-content" className={view === 'workspace' ? 'workspace-grid' : 'full-content'}><div className={view === 'workspace' ? 'workspace-main' : 'full-content-inner'}>
        {pdfLoading && <Busy text="Opening protected PDF…" />}<ErrorNotice error={error} />
        {view === 'workspace' && <><PageHeading eyebrow={thread ? 'YOUR RESEARCH CONVERSATION' : 'A LITTLE CONTEXT. A CLEARER ANSWER.'} title="Clarity for your GST questions." subtitle="Research your documents. Review the evidence." />
          <div className="thread" aria-label="Conversation">{loading ? <Busy text="Loading your workspace…" /> : thread ? thread.rows.map((q) => <QueryCard key={q.id} query={q} username={user.username} />) : <div className="welcome-card"><span className="welcome-symbol"><BookOpen size={36} strokeWidth={1.3} /></span><h2>Start with a good question.</h2><p>Describe the transaction, add the relevant date, and we’ll gather the permitted evidence for review.</p><div className="welcome-steps"><span><i>1</i>Ask with context</span><span><i>2</i>Admin checks evidence</span><span><i>3</i>Read the approved answer</span></div></div>}</div>
          <Composer key={selected || 'new-question'} client={client} parent={parent} sample={client.sample} onSent={(q) => { setRows((list) => [q, ...list.filter((item) => item.id !== q.id)]); setSelected(q.conversation_id); }} />
        </>}
        {view === 'history' && <HistoryView rows={rows} onSelect={choose} />}
        {user.role === 'admin' && view === 'admin' && <AdminOverview client={client} navigate={navigate} />}
        {user.role === 'admin' && view === 'reviews' && <ReviewDesk client={client} onPdf={openPdf} onDirtyChange={setAdminDirty} />}
        {user.role === 'admin' && view === 'incoming' && <SourceInbox key={incomingId || 'all'} client={client} onPdf={openPdf} onDirtyChange={setAdminDirty} initialSelection={incomingId} />}
        {user.role === 'admin' && view === 'uploads' && <UploadDesk client={client} initialTarget={uploadTarget} onDirtyChange={setAdminDirty} onPdf={(id, page) => openPdf(id, page, 'upload')} onNotification={(id) => { setIncomingId(id); navigate('incoming'); }} onPublications={() => navigate('publications')} />}
        {user.role === 'admin' && view === 'publications' && <PublicationsDesk client={client} />}
        {user.role === 'admin' && view === 'imports' && <ImportDesk client={client} />}
        {user.role === 'admin' && view === 'users' && <People client={client} onSelfChange={refreshUser} />}
        {user.role === 'admin' && view === 'sources' && <Library client={client} onPdf={openPdf} onUpload={(target) => { setUploadTarget(target || null); navigate('uploads'); }} />}
      </div>{view === 'workspace' && <ResearchContext user={user} health={health} />}</main>
    </div>
    {help && <Modal title="A review-first research flow" onClose={() => setHelp(false)}><div className="modal-body stack"><p>Your administrator manages your plan. Ask a question, and an admin checks the answer before it is shared with you.</p><p>Include transaction facts and dates in follow-ups. You may receive a request for clarification when more context is needed.</p><p>The available material is incomplete. This is a research assistant, not a substitute for professional tax advice.</p><p>Approved answers remain readable for their 30-day retention window, including after a downgrade. Refreshing the app signs you out.</p></div></Modal>}
    {pdf && <Modal title="Protected PDF source" onClose={() => setPdf(null)}><div className="pdf-toolbar"><p className="small muted">Admin-only · authenticated fetch · PDF p. {pdf.page}<br />If your browser cannot display PDFs, download the original.</p><a className="button secondary" href={pdf.url} download="gst-source.pdf"><Download size={15} />Download PDF</a></div><iframe className="pdf-frame" title="Source PDF" src={`${pdf.url}#page=${pdf.page}`} /></Modal>}
    {pendingNavigation && <Modal title="Leave with unsaved review changes?" onClose={() => setPendingNavigation(null)}><div className="modal-body stack"><p>Your private edits have not been saved. Stay here to finish or discard them before leaving.</p><div className="button-row"><button className="button secondary" onClick={() => setPendingNavigation(null)}>Keep editing</button><button className="button primary" onClick={() => { setAdminDirty(false); applyNavigation(pendingNavigation); setPendingNavigation(null); }}>Discard and leave</button></div></div></Modal>}
  </div>;
}

export function App({ initialClient }: { initialClient?: Client }) {
  const [session, setSession] = useState<{ client: Client; user: User } | null>(null); const [notice, setNotice] = useState('');
  const [recruiter, setRecruiter] = useState(false);
  const [client] = useState(() => initialClient || new ApiClient(undefined, () => { setSession(null); setNotice('Your session has ended. Please sign in again.'); }));
  const updateUser = useCallback((user: User) => setSession((current) => current ? { ...current, user } : null), []);
  function logout() { session?.client.logout(); setSession(null); setNotice(''); }
  async function preview(role: Role, plan: Plan = 'pro') { const sample = new SampleClient(role, plan); setSession({ client: sample, user: await sample.me() }); setNotice(''); }
  return <>{!session ? <Login client={client} notice={notice} onLogin={(user) => setSession({ client, user })} onPreview={preview} onRecruiter={() => setRecruiter(true)} />
    : <WorkspaceApp key={`${session.client.sample ? 'sample' : 'live'}-${session.user.id}-${session.user.role}-${session.client.sample ? session.user.plan : ''}`} client={session.client} user={session.user} onUser={updateUser} onLogout={logout} onPreview={preview} onRecruiter={() => setRecruiter(true)} />}
    {recruiter && <RecruiterDialog onClose={() => setRecruiter(false)} />}
  </>;
}
