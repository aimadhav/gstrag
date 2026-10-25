import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SampleClient } from '../src/sample';
import { UploadDesk } from '../src/UploadDesk';
import { PublicationsDesk } from '../src/AdminIngestion';

function setup(target?: string, client = new SampleClient('admin')) {
  const notify = vi.fn(); const publish = vi.fn(); const dirty = vi.fn();
  render(<UploadDesk client={client} initialTarget={target} onNotification={notify} onPublications={publish} onPdf={() => {}} onDirtyChange={dirty} />);
  return { user: userEvent.setup(), client, notify, publish, dirty };
}
async function uploadBook() {
  const result = setup(); await screen.findByText('Your upload tray is clear.');
  await result.user.selectOptions(screen.getByRole('combobox', { name: 'PDF source type' }), 'firm_book');
  await result.user.upload(screen.getByLabelText('PDF file'), new File(['synthetic'], 'sample-book.pdf', { type: 'application/pdf' }));
  expect(Array.from((screen.getByLabelText('PDF file').closest('form')!).elements)
    .filter((e) => e instanceof HTMLInputElement && e.type !== 'file' && !e.validity.valid)
    .map((e) => (e as HTMLInputElement).type + ': ' + (e as HTMLInputElement).validationMessage)).toEqual([]);
  // jsdom's native required-file validator does not recognise user-event's FileList.
  // Check our gate, then submit. Real required-file submission is browser-tested separately.
  expect(screen.getByRole('button', { name: 'Upload to private staging' })).toBeEnabled();
  fireEvent.submit(screen.getByLabelText('PDF file').closest('form')!);
  await screen.findByRole('heading', { name: 'Review the book parse' }); return result;
}

describe('Admin uploads and replacements', () => {
  it('does not allow empty uploads and explains private staging', async () => {
    setup(); expect(screen.getByRole('button', { name: 'Upload to private staging' })).toBeDisabled();
    expect(screen.getByText(/No OCR, provider calls or automatic approval/)).toBeInTheDocument();
  });
  it('locks a replacement to its registered source type', async () => {
    setup('sample-source-1'); await screen.findByDisplayValue('Firm GST book · sample reference (updated)');
    expect(screen.getByRole('combobox', { name: 'PDF source type' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'PDF source type' })).toHaveValue('firm_book');
    expect(screen.getByText(/old PDF and citation identity are retained/)).toBeInTheDocument();
  });
  it('stores no file in preview and requires human checks before source approval', async () => {
    await uploadBook(); expect(screen.getByText(/No file was sent or parsed/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve book source' })).toBeDisabled();
    expect(screen.getByText(/Illustrative sample · Pro only/)).toBeInTheDocument();
  });
  it('approves only after explicit confirmation and does not activate a corpus', async () => {
    const { user, client } = await uploadBook(); const review = vi.spyOn(client, 'reviewBook'); const activate = vi.spyOn(client, 'activatePublication');
    await user.type(screen.getByRole('textbox', { name: 'Book review note' }), 'Checked the synthetic original, order and all exclusions.');
    await user.click(screen.getByRole('checkbox', { name: /I inspected the original PDF/ }));
    await user.click(screen.getByRole('checkbox', { name: /I checked structure/ }));
    await user.click(screen.getByRole('button', { name: 'Approve book source' })); expect(review).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm book approval' }));
    await screen.findByText(/Source decision recorded privately/);
    expect(review).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ action: 'approve', revision: 0, source_checked: true, structure_checked: true }));
    expect(activate).not.toHaveBeenCalled();
  });
  it('rejects without making false PDF/structure attestations', async () => {
    const { user, client } = await uploadBook(); const review = vi.spyOn(client, 'reviewBook');
    await user.click(screen.getByRole('button', { name: 'Reject book source' }));
    const dialog = within(screen.getByRole('dialog')); await user.type(dialog.getByRole('textbox', { name: 'Rejection note' }), 'The parse is incomplete.');
    await user.click(dialog.getByRole('button', { name: 'Confirm book rejection' }));
    await screen.findByText(/Source decision recorded privately/);
    expect(review).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ action: 'reject', source_checked: false, structure_checked: false }));
  });
  it('collects notification identity explicitly rather than guessing from the filename', async () => {
    const { user, client } = setup(); const upload = vi.spyOn(client, 'uploadFile'); await screen.findByText('Your upload tray is clear.');
    await user.selectOptions(screen.getByRole('combobox', { name: 'PDF source type' }), 'notification');
    await user.upload(screen.getByLabelText('PDF file'), new File(['synthetic'], '08-2025.pdf', { type: 'application/pdf' }));
    expect(screen.getByRole('spinbutton', { name: 'Notification number' })).toHaveValue(null);
    await user.selectOptions(screen.getByRole('combobox', { name: 'Notification series' }), 'central_tax_rate');
    await user.type(screen.getByRole('spinbutton', { name: 'Notification number' }), '8');
    await user.type(screen.getByRole('spinbutton', { name: 'Notification year' }), '2025');
    fireEvent.submit(screen.getByLabelText('PDF file').closest('form')!);
    expect(await screen.findByRole('button', { name: 'Review notification evidence' })).toBeInTheDocument();
    expect(upload).toHaveBeenCalledWith(expect.any(File), expect.objectContaining({ source_type: 'notification', number: 8, year: 2025 }));
  });
  it('preserves the selected file after a transfer failure so it can be retried', async () => {
    const client = new SampleClient('admin'); vi.spyOn(client, 'uploadFile').mockRejectedValueOnce(new TypeError('network'));
    const { user } = setup(undefined, client); await screen.findByText('Your upload tray is clear.');
    await user.upload(screen.getByLabelText('PDF file'), new File(['synthetic'], 'sample-book.pdf', { type: 'application/pdf' }));
    fireEvent.submit(screen.getByLabelText('PDF file').closest('form')!); await screen.findByRole('alert');
    expect((screen.getByLabelText('PDF file') as HTMLInputElement).files).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Upload to private staging' })).toBeEnabled();
  });
  it('includes approved uploaded books in publication selection', async () => {
    const client = new SampleClient('admin'); const row = await client.uploadFile(new File(['x'], 'book.pdf'), { title: 'Reviewed sample book', source_type: 'firm_book', replaces_document_id: null });
    await client.reviewBook(row.id, { action: 'approve', revision: 0, stage_sha256: row.stage_sha256!, reason: 'Synthetic check', source_checked: true, structure_checked: true });
    render(<PublicationsDesk client={client} />);
    expect(await screen.findByRole('checkbox', { name: /Reviewed sample book/ })).toBeInTheDocument();
  });
  it('denies upload/history/detail operations to a sample researcher', async () => {
    const client = new SampleClient('user');
    await expect(client.uploads()).rejects.toMatchObject({ status: 403 });
    await expect(client.uploadFile(new File(['x'], 'book.pdf'), { title: 'Sample', source_type: 'icai_book', replaces_document_id: null })).rejects.toMatchObject({ status: 403 });
    await expect(client.uploadDetail('a')).rejects.toMatchObject({ status: 403 });
  });
});
