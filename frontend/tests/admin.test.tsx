import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { ApiError } from '../src/api';
import { SampleClient } from '../src/sample';
import { ImportDesk, PublicationsDesk, SourceInbox } from '../src/AdminIngestion';

async function preview() {
  const user = userEvent.setup(); render(<App />);
  await user.click(screen.getByRole('button', { name: 'Admin preview' }));
  await screen.findByRole('textbox', { name: /Answer draft/ }); return user;
}
async function incoming() {
  const user = await preview(); await user.click(screen.getByRole('button', { name: 'Incoming notifications' }));
  await screen.findByRole('heading', { name: 'Source decision' }); return user;
}
async function completeReview(user: ReturnType<typeof userEvent.setup>) {
  fireEvent.change(screen.getByLabelText('Issue date', { exact: true }), { target: { value: '2025-01-01' } });
  fireEvent.change(screen.getByLabelText('Effective date', { exact: true }), { target: { value: '2025-01-02' } });
  for (const [label, ref] of [['Identity source item', '#/texts/0'], ['Issue date source item', '#/texts/1'], ['Effective date source item', '#/texts/2']]) {
    await user.selectOptions(screen.getByRole('combobox', { name: label }), ref);
  }
  // Paste the long form values like a reviewer copying a prepared note. Per-character
  // re-renders make this full workflow unnecessarily sensitive to machine load.
  for (const [name, value] of [['Clause 1 subject', 'Synthetic complete condition'],
    ['Clause 1 provisions', 'Synthetic entry; Second entry'], ['Clause 1 operative change', 'Synthetic reviewed change']]) {
    await user.click(screen.getByRole('textbox', { name })); await user.paste(value);
  }
  await user.click(screen.getByRole('checkbox', { name: /#\/texts\/3/ }));
  await user.click(screen.getByRole('checkbox', { name: /I checked clause 1/ }));
  await user.click(screen.getByRole('checkbox', { name: /I inspected the original PDF/ }));
}

describe('Admin operations', () => {
  it('keeps all admin navigation hidden from a researcher', async () => {
    const user = userEvent.setup(); render(<App />); await user.click(screen.getByRole('button', { name: 'Preview workspace' }));
    for (const name of ['Admin overview', 'Incoming notifications', 'Corpus publications', 'Import history', 'Review inbox']) expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
  });
  it('loads the overview and navigates through the source checkpoint', async () => {
    const user = await preview(); await user.click(screen.getByRole('button', { name: 'Admin overview' }));
    await screen.findByRole('heading', { name: 'Good research needs good judgment.' });
    expect(await screen.findByText('149')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Review the source/ }));
    expect(await screen.findByRole('heading', { name: 'Source decision' })).toBeInTheDocument();
  });
  it('shows the original items, unknown dates and disabled approval initially', async () => {
    await incoming(); expect(screen.getByLabelText('Issue date', { exact: true })).toHaveValue('');
    expect(screen.getByLabelText('Effective date', { exact: true })).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Approve source metadata' })).toBeDisabled();
    expect(screen.getByRole('heading', { name: 'Original parsed items' })).toBeInTheDocument();
    expect(screen.getByText('Notification No. 8/2025-Central Tax (Rate)', { exact: true })).toBeInTheDocument();
  });
  it('records source approval only after a complete form and explicit confirmation', async () => {
    const user = await incoming(); await completeReview(user);
    await user.click(screen.getByRole('button', { name: 'Approve source metadata' }));
    const dialog = screen.getByRole('dialog', { name: 'Confirm source approval' });
    expect(within(dialog).getByText(/does not index, activate or approve an answer/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Confirm source approval' }));
    expect(await screen.findByText(/Source decision recorded/)).toBeInTheDocument();
    expect(screen.getByText('Previous decision: approved · Revision 1')).toBeInTheDocument();
  });
  it('rejects with a reason and does not publish anything', async () => {
    const user = await incoming(); await user.click(screen.getByRole('button', { name: 'Reject source' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Reject incoming source' }));
    await user.type(dialog.getByRole('textbox', { name: 'Rejection reason' }), 'Needs a separate policy for this source.');
    await user.click(dialog.getByRole('button', { name: 'Confirm rejection' }));
    await screen.findByText(/Source decision recorded/); expect(screen.getByText(/Previous decision: rejected/)).toBeInTheDocument();
  });
  it('protects unsaved source review when navigating away', async () => {
    const user = await incoming(); await user.type(screen.getByRole('textbox', { name: 'Clause 1 subject' }), 'Private edit');
    await user.click(screen.getByRole('button', { name: 'People & access' }));
    const dialog = screen.getByRole('dialog', { name: 'Leave with unsaved review changes?' });
    await user.click(within(dialog).getByRole('button', { name: 'Keep editing' }));
    expect(screen.getByRole('textbox', { name: 'Clause 1 subject' })).toHaveValue('Private edit');
    await user.click(screen.getByRole('button', { name: 'People & access' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Discard and leave' }));
    expect(await screen.findByRole('heading', { name: 'Create an account' })).toBeInTheDocument();
  });
  it('protects the existing human answer draft when navigating away', async () => {
    const user = await preview(); await user.type(screen.getByRole('textbox', { name: /Answer draft/ }), ' Private edit');
    await user.click(screen.getByRole('button', { name: 'Admin overview' }));
    expect(screen.getByRole('dialog', { name: 'Leave with unsaved review changes?' })).toBeInTheDocument();
  });
  it('warns before replacing a dirty source with another source', async () => {
    const user = await incoming(); await user.type(screen.getByRole('textbox', { name: 'Clause 1 subject' }), 'Unsent changes');
    await user.click(screen.getByRole('button', { name: /central_tax_rate:9\/2025:en/ }));
    const dialog = screen.getByRole('dialog', { name: 'Discard source-review changes?' });
    await user.click(within(dialog).getByRole('button', { name: 'Discard changes' }));
    expect(await screen.findByRole('heading', { name: 'Notification 9/2025 · illustrative sample' })).toBeInTheDocument();
  });
  it('requires re-attestation if selected complete-clause source items change', async () => {
    const user = await incoming(); await completeReview(user);
    expect(screen.getByRole('button', { name: 'Approve source metadata' })).toBeEnabled();
    await user.click(screen.getByRole('checkbox', { name: /#\/texts\/2/ }));
    expect(screen.getByRole('checkbox', { name: /I checked clause 1/ })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Approve source metadata' })).toBeDisabled();
  });
  it('retains input-event date edits and clears the source attestation after metadata changes', async () => {
    const user = await incoming(); await completeReview(user);
    fireEvent.input(screen.getByLabelText('Issue date', { exact: true }), { target: { value: '2025-01-02' } });
    await user.type(screen.getByRole('textbox', { name: 'Clause 1 subject' }), ' changed');
    expect(screen.getByLabelText('Issue date', { exact: true })).toHaveValue('2025-01-02');
    expect(screen.getByRole('checkbox', { name: /I inspected the original PDF/ })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Approve source metadata' })).toBeDisabled();
  });
  it('offers an admin blob-download fallback and revokes it when the viewer closes', async () => {
    const revoke = vi.fn(); vi.stubGlobal('URL', class extends URL {
      static createObjectURL() { return 'blob:synthetic-pdf'; }
      static revokeObjectURL = revoke;
    });
    const client = new SampleClient('admin'); vi.spyOn(client, 'pdf').mockResolvedValue(new Blob(['synthetic'], { type: 'application/pdf' }));
    render(<App initialClient={client} />); const user = userEvent.setup();
    await user.type(screen.getByRole('textbox', { name: 'Username' }), 'fixture-admin');
    await user.type(screen.getByLabelText('Password', { exact: true }), 'fixture-password-only');
    await user.click(screen.getByRole('button', { name: 'Sign in to workspace' }));
    await screen.findByRole('textbox', { name: /Answer draft/ });
    await user.click(screen.getByText('Firm GST book · sample reference', { exact: true }));
    await user.click(screen.getAllByRole('button', { name: /View PDF source/ })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'Protected PDF source' });
    const link = within(dialog).getByRole('link', { name: 'Download PDF' });
    expect(link).toHaveAttribute('href', 'blob:synthetic-pdf'); expect(link).toHaveAttribute('download', 'gst-source.pdf');
    expect(link.getAttribute('href')).not.toContain('TOKEN');
    await user.click(within(dialog).getByRole('button', { name: 'Close Protected PDF source' }));
    expect(revoke).toHaveBeenCalledWith('blob:synthetic-pdf');
  });
  it('can filter incoming versions without losing their actual review statuses', async () => {
    const user = await incoming(); await user.selectOptions(screen.getByRole('combobox', { name: 'Review status' }), 'approved');
    const list = within(screen.getByRole('complementary', { name: 'Incoming notification list' }));
    expect(list.getAllByRole('button')).toHaveLength(1); expect(list.getByText('Source approved')).toBeInTheDocument();
  });
  it('shows safe stale-review errors without treating the failed decision as approved', async () => {
    const client = new SampleClient('admin'); vi.spyOn(client, 'approveSource').mockRejectedValue(new ApiError(409, 'stale_source_review_revision'));
    render(<SourceInbox client={client} onPdf={() => {}} onDirtyChange={() => {}} />);
    await screen.findByRole('heading', { name: 'Source decision' }); const user = userEvent.setup(); await completeReview(user);
    await user.click(screen.getByRole('button', { name: 'Approve source metadata' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm source approval' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Another admin changed'); expect(screen.queryByText(/Source decision recorded/)).not.toBeInTheDocument();
  });
  it('prepares selected approved sources without silently activating them', async () => {
    const client = new SampleClient('admin'); const prepare = vi.spyOn(client, 'preparePublication'); const activate = vi.spyOn(client, 'activatePublication');
    render(<PublicationsDesk client={client} />); const user = userEvent.setup();
    await user.click(await screen.findByRole('checkbox', { name: /central_tax_rate:9\/2025:en/ }));
    await user.click(screen.getByRole('button', { name: 'Prepare selected sources (1)' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Confirm snapshot preparation' }));
    expect(dialog.getByRole('button', { name: 'Confirm preparation' })).toBeDisabled();
    await user.click(dialog.getByRole('checkbox')); await user.click(dialog.getByRole('button', { name: 'Confirm preparation' }));
    await screen.findByText(/Snapshot prepared privately/); expect(prepare).toHaveBeenCalledWith(['b'.repeat(64)], '1'.repeat(64)); expect(activate).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', { name: 'Backend verification instructions' })).toBeInTheDocument();
  });
  it('enables activation only for a verified current-base snapshot and asks for confirmation', async () => {
    const client = new SampleClient('admin'); const activate = vi.spyOn(client, 'activatePublication'); render(<PublicationsDesk client={client} />);
    const user = userEvent.setup(); const buttons = await screen.findAllByRole('button', { name: 'Activate snapshot' });
    expect(buttons[0]).toBeDisabled(); expect(buttons[1]).toBeEnabled();
    await user.click(buttons[1]); const dialog = within(screen.getByRole('dialog', { name: 'Confirm corpus activation' }));
    expect(activate).not.toHaveBeenCalled(); await user.click(dialog.getByRole('checkbox')); await user.click(dialog.getByRole('button', { name: 'Confirm activation' }));
    await screen.findByText(/Verified snapshot activated/); expect(activate).toHaveBeenCalledWith('d'.repeat(64), '1'.repeat(64));
  });
  it('shows unavailable worker controls without asking for a scheduler secret', async () => {
    const client = new SampleClient('admin'); vi.spyOn(client, 'syncStatus').mockResolvedValue({ enabled: false, worker_ready: false, max_documents: 2, max_pages: 1, since_year: 2025, jobs: [] });
    render(<ImportDesk client={client} />); const button = await screen.findByRole('button', { name: 'Run bounded import' });
    expect(button).toBeDisabled(); expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
  it('confirms an import and clearly labels a sample-only result', async () => {
    const client = new SampleClient('admin'); const trigger = vi.spyOn(client, 'triggerSync'); render(<ImportDesk client={client} />); const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Run bounded import' })); expect(trigger).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm bounded import' }));
    expect(await screen.findByText('Sample import recorded in this tab only. No PDF was downloaded or parsed.')).toBeInTheDocument();
    expect(trigger).toHaveBeenCalledWith(expect.stringMatching(/^admin:/)); expect(await screen.findByText('Completed · staging only')).toBeInTheDocument();
  });
  it('reuses the same key after a lost trigger response', async () => {
    const client = new SampleClient('admin'); const original = client.triggerSync.bind(client);
    const trigger = vi.spyOn(client, 'triggerSync').mockRejectedValueOnce(new TypeError('Network failed')).mockImplementation(original);
    render(<ImportDesk client={client} />); const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Run bounded import' })); await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm bounded import' }));
    await screen.findByRole('alert'); await user.click(screen.getByRole('button', { name: 'Retry import request' })); await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm bounded import' }));
    await screen.findByText(/Sample import recorded/); expect(trigger.mock.calls[0][0]).toBe(trigger.mock.calls[1][0]);
  });
  it('denies all new sample-admin operations to sample researchers', async () => {
    const client = new SampleClient('user');
    for (const request of [() => client.incomingSources(), () => client.corpusStatus(), () => client.publications(), () => client.syncStatus(), () => client.triggerSync('x')]) await expect(request()).rejects.toMatchObject({ status: 403 });
  });
});
