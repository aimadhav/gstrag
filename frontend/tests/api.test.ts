import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, errorMessage } from '../src/api';

const user = { id: 'fixture-user', username: 'fixture', role: 'user', plan: 'plus' };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock); });
async function loggedIn(expired = () => {}) {
  fetchMock.mockResolvedValueOnce(response({ access_token: 'SYNTHETIC_SESSION_TOKEN' })).mockResolvedValueOnce(response(user));
  const client = new ApiClient('/api', expired); await client.login('fixture', 'synthetic-password-fixture'); return client;
}

describe('API boundary', () => {
  it('reserves by hash then transfers raw PDF bytes without a filename or token in its URL', async () => {
    const { webcrypto } = await import('node:crypto'); vi.stubGlobal('crypto', webcrypto);
    const client = await loggedIn(); const file = new File(['synthetic'], '../../book.pdf', { type: 'application/pdf' });
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode('synthetic').buffer });
    fetchMock.mockResolvedValueOnce(response({ id: 'a'.repeat(64) })).mockResolvedValueOnce(response({ id: 'a'.repeat(64), status: 'uploaded_queued' }));
    await client.uploadFile(file, { title: 'Synthetic book', source_type: 'firm_book', replaces_document_id: null });
    const [reserveUrl, reserve] = fetchMock.mock.calls.at(-2)!; const payload = JSON.parse(reserve.body);
    expect(reserveUrl).toBe('/api/admin/uploads'); expect(payload.sha256).toMatch(/^[a-f0-9]{64}$/); expect(payload.byte_count).toBe(9); expect(payload.pdf_path).toBeUndefined();
    const [uploadUrl, upload] = fetchMock.mock.calls.at(-1)!; expect(uploadUrl).toBe(`/api/admin/uploads/${'a'.repeat(64)}/pdf`);
    expect(upload.body).toBe(file); expect(upload.headers.get('Content-Type')).toBe('application/pdf'); expect(uploadUrl).not.toContain('TOKEN'); expect(uploadUrl).not.toContain('book.pdf');
  });
  it('paginates incoming notification versions', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(response(Array(100).fill({ id: 'a' }))).mockResolvedValueOnce(response([{ id: 'b' }]));
    expect(await client.incomingSources()).toHaveLength(101);
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/admin/ingestion/notifications?limit=100&offset=100');
  });
  it('fetches staged PDFs from a fixed protected route', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(new Response('synthetic', { headers: { 'Content-Type': 'application/pdf' } }));
    await client.stagedPdf('version/one'); expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/admin/ingestion/notifications/version%2Fone/pdf');
  });
  it('uses the admin JWT, empty body and stable key for imports; never a service secret', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(response({ id: 'job' })); await client.triggerSync('admin:stable');
    const [url, init] = fetchMock.mock.calls.at(-1)!;
    expect(url).toBe('/api/admin/ingestion/sync'); expect(init.body).toBe('{}');
    expect(init.headers.get('Authorization')).toBe('Bearer SYNTHETIC_SESSION_TOKEN'); expect(init.headers.get('Idempotency-Key')).toBe('admin:stable');
  });
  it('binds preparation and activation to the displayed base digest', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(response({ id: 'publication' })); await client.preparePublication(['a'.repeat(64)], 'b'.repeat(64));
    expect(JSON.parse(fetchMock.mock.calls.at(-1)?.[1].body)).toEqual({ version_ids: ['a'.repeat(64)], base_sha256: 'b'.repeat(64) });
    fetchMock.mockResolvedValueOnce(response({ state: 'active' })); await client.activatePublication('c'.repeat(64), 'b'.repeat(64));
    expect(JSON.parse(fetchMock.mock.calls.at(-1)?.[1].body)).toEqual({ base_sha256: 'b'.repeat(64), confirm: true });
  });
  it('sends source rejection with revision, stage hash and reason', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(response({})); await client.rejectSource('a', 2, 'b'.repeat(64), 'Synthetic reason');
    expect(JSON.parse(fetchMock.mock.calls.at(-1)?.[1].body)).toEqual({ revision: 2, stage_sha256: 'b'.repeat(64), reason: 'Synthetic reason' });
  });
  it('logs in using JSON and resolves current identity from /me', async () => {
    const client = await loggedIn();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/auth/token'); expect(JSON.parse(init.body)).toEqual({ username: 'fixture', password: 'synthetic-password-fixture' });
    expect(fetchMock.mock.calls[1][0]).toBe('/api/me');
    expect(fetchMock.mock.calls[1][1].headers.get('Authorization')).toBe('Bearer SYNTHETIC_SESSION_TOKEN');
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0); client.logout();
  });
  it('does not put role, plan or namespaces in question payloads', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(response({ id: 'q' }));
    await client.submit({ question: 'Synthetic question', as_of: '2023-03-01', topic_ids: ['other_gst'], parent_query_id: 'parent' });
    const [url, init] = fetchMock.mock.calls[2];
    expect(url).toBe('/api/queries'); expect(Object.keys(JSON.parse(init.body))).toEqual(['question', 'as_of', 'topic_ids', 'parent_query_id']);
    expect(init.cache).toBe('no-store'); expect(init.credentials).toBe('omit');
  });
  it('paginates conversation history instead of dropping the 101st item', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(response(Array(100).fill({ id: 'a' }))).mockResolvedValueOnce(response([{ id: 'b' }]));
    const rows = await client.queries(); expect(rows).toHaveLength(101); expect(fetchMock.mock.calls.at(-1)?.[0]).toContain('offset=100');
  });
  it('paginates the private review inbox', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(response(Array(100).fill({ id: 'a' }))).mockResolvedValueOnce(response([]));
    expect(await client.reviews()).toHaveLength(100); expect(fetchMock.mock.calls.at(-1)?.[0]).toBe('/api/admin/reviews?limit=100&offset=100');
  });
  it('clears the token and signals session expiry on 401', async () => {
    const expired = vi.fn(); const client = await loggedIn(expired); fetchMock.mockResolvedValueOnce(response({ detail: 'invalid_or_expired_credentials' }, 401));
    await expect(client.me()).rejects.toBeInstanceOf(ApiError); expect(expired).toHaveBeenCalledOnce();
    fetchMock.mockResolvedValueOnce(response(user)); await client.me(); expect(fetchMock.mock.calls.at(-1)?.[1].headers.has('Authorization')).toBe(false);
  });
  it('does not invalidate a new session because an old in-flight request fails', async () => {
    const expired = vi.fn(); const client = await loggedIn(expired); let resolveOld!: (response: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveOld = resolve; }));
    const old = client.me(); client.logout();
    fetchMock.mockResolvedValueOnce(response({ access_token: 'SYNTHETIC_NEW_TOKEN' })).mockResolvedValueOnce(response(user));
    await client.login('fixture', 'synthetic-password-fixture'); resolveOld(response({}, 401));
    await expect(old).rejects.toBeInstanceOf(ApiError); expect(expired).not.toHaveBeenCalled();
  });
  it('uses a fixed authenticated PDF path, never a model URL or token in the URL', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(new Response('synthetic PDF fixture', { headers: { 'Content-Type': 'application/pdf' } }));
    const blob = await client.pdf('doc/one'); const [url, init] = fetchMock.mock.calls.at(-1)!;
    expect(url).toBe('/api/admin/sources/doc%2Fone/pdf'); expect(url).not.toContain('TOKEN'); expect(init.headers.Authorization).toContain('Bearer '); expect(blob.type).toBe('application/pdf');
  });
  it('refuses an HTML response masquerading as a PDF', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(new Response('<html>not a PDF</html>', { headers: { 'Content-Type': 'text/html' } }));
    await expect(client.pdf('doc')).rejects.toMatchObject({ code: 'invalid_pdf' });
  });
  it('passes review revision and explicit action to the backend', async () => {
    const client = await loggedIn(); fetchMock.mockResolvedValueOnce(response({ id: 'q' }));
    await client.decide('q', { revision: 4, action: 'approve', citation_ids: ['S1'] });
    expect(JSON.parse(fetchMock.mock.calls.at(-1)?.[1].body)).toEqual({ revision: 4, action: 'approve', citation_ids: ['S1'] });
  });
  it('does not display raw provider error bodies', () => {
    expect(errorMessage(new ApiError(500, 'SYNTHETIC_PRIVATE_PROVIDER_DETAIL'))).not.toContain('SYNTHETIC_PRIVATE');
    expect(errorMessage(new ApiError(409, 'access_changed_reprocess_required'))).toMatch(/Reprocess/);
  });
});
