import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { App, AnswerText, QueryCard } from '../src/App';
import { SampleClient } from '../src/sample';
import { conversations } from '../src/helpers';
import type { Query } from '../src/types';

async function preview(admin = false) {
  const user = userEvent.setup(); render(<App />);
  await user.click(screen.getByRole('button', { name: admin ? 'Admin preview' : 'Preview workspace' }));
  await screen.findByText(/Sample data only\. No API calls/); return user;
}

describe('User workspace', () => {
  it('shows login and a clearly labelled, no-network sample preview', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); await preview();
    expect(screen.getByText(/Sample data only/)).toBeInTheDocument(); expect(screen.getByRole('heading', { name: 'Clarity for your GST questions.' })).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled(); expect(screen.queryByRole('button', { name: 'Review inbox' })).not.toBeInTheDocument();
  });
  it('displays approved plain-text citations, never a PDF download link', async () => {
    await preview(); expect(screen.getByText('Approved by admin')).toBeInTheDocument();
    expect(screen.getByText(/Firm book · p. 12/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /View PDF/ })).not.toBeInTheDocument(); expect(document.querySelector('a[href*="/admin/"]')).toBeNull();
  });
  it('never renders an answer from a pending response even if malformed extra content arrives', () => {
    const row = { id: 'q', question: 'Synthetic question', status: 'pending_review', message: 'Waiting for review.',
      created_at: '2026-10-23T10:00:00Z', answer: 'PRIVATE_UNAPPROVED_DRAFT', citations: [{ source_name: 'PRIVATE_SOURCE' }] } as Query;
    render(<QueryCard query={row} username="fixture" />); expect(screen.queryByText('PRIVATE_UNAPPROVED_DRAFT')).not.toBeInTheDocument(); expect(screen.queryByText('PRIVATE_SOURCE')).not.toBeInTheDocument();
  });
  it('escapes HTML in approved answers instead of interpreting model markup', () => {
    render(<AnswerText text={'Book explanation\n<img src=x onerror=alert(1)>\n\nPractical effect\n<script>bad()</script>'} />);
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument(); expect(document.querySelector('img')).toBeNull(); expect(document.querySelector('script')).toBeNull();
  });
  it('submits a follow-up into its existing conversation and hides the new draft', async () => {
    const user = await preview(); await user.type(screen.getByRole('textbox', { name: 'GST question' }), 'What additional facts should I provide?');
    await user.click(screen.getByRole('button', { name: 'Send question' }));
    await screen.findByText('What additional facts should I provide?'); expect(screen.getByText('Awaiting admin review')).toBeInTheDocument();
    expect(screen.getByText(/Sample question saved/)).toBeInTheDocument(); expect(screen.queryByText('Illustrative source excerpt for the interface preview. No actual PDF or legal claim is supplied.')).not.toBeInTheDocument();
  });
  it('starts a fresh question without leaking previous answer text into the composer', async () => {
    const user = await preview(); await user.click(screen.getByRole('button', { name: 'New question' }));
    expect(screen.getByRole('heading', { name: 'Start with a good question.' })).toBeInTheDocument(); expect(screen.getByRole('textbox', { name: 'GST question' })).toHaveValue('');
    expect(screen.queryByRole('heading', { name: 'Book explanation' })).not.toBeInTheDocument();
  });
  it('resets page scroll when entering the workspace and opening a fresh conversation', async () => {
    const user = await preview(); expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
    vi.mocked(window.scrollTo).mockClear();
    await user.click(screen.getByRole('button', { name: 'New question' }));
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });
  it('filters conversation history and handles an empty result', async () => {
    const user = await preview(); await user.click(screen.getByRole('button', { name: 'Conversation history' }));
    await user.type(screen.getByRole('textbox', { name: 'Search conversations' }), 'no-such-question'); expect(screen.getByText('No conversations found.')).toBeInTheDocument();
  });
  it('shows Plus access without a customer-facing source catalogue or engine details', async () => {
    const user = await preview(); await user.selectOptions(screen.getByRole('combobox', { name: 'Preview as' }), 'plus');
    await screen.findByText('Plus access');
    const context = within(screen.getByRole('complementary', { name: 'Your workspace' }));
    expect(context.getByText('Your plan is managed by your administrator.')).toBeInTheDocument();
    expect(context.queryByText(/Included sources|ICAI books|Firm books|Notifications|retrieval|Gemini/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Firm book · p. 12/)).not.toBeInTheDocument();
  });
  it('keeps the Pro context minimal while preserving approved answer citations', async () => {
    await preview(); const context = within(screen.getByRole('complementary', { name: 'Your workspace' }));
    expect(context.getByText('Pro access')).toBeInTheDocument();
    expect(context.queryByText(/Included sources|ICAI books|Firm books|Notifications|retrieval|Gemini/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Firm book · p. 12/)).toBeInTheDocument();
  });
  it('offers a dismissible recruiter placeholder before login without network calls', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); const user = userEvent.setup(); render(<App />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Recruiter?' }));
    const dialog = screen.getByRole('dialog', { name: 'For recruiters' });
    expect(within(dialog).getByText('The technical walkthrough will be added after the project is complete.')).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: 'Close For recruiters' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Welcome back.' })).toBeInTheDocument();
  });
  it('opens the same recruiter placeholder from the workspace and handles Escape cancellation', async () => {
    const user = await preview(); await user.click(screen.getByRole('button', { name: 'Recruiter?' }));
    const dialog = screen.getByRole('dialog', { name: 'For recruiters' });
    expect(within(dialog).getByText('Verified results, when it’s ready.')).toBeInTheDocument();
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Approved by admin')).toBeInTheDocument();
  });
  it('labels the recruiter outline as planned, not as published technical pages', async () => {
    const user = await preview(); await user.click(screen.getByRole('button', { name: 'Recruiter?' }));
    const dialog = within(screen.getByRole('dialog', { name: 'For recruiters' }));
    expect(dialog.getByText('Not published yet')).toBeInTheDocument();
    expect(dialog.getAllByRole('listitem')).toHaveLength(3);
    expect(dialog.queryByRole('link')).not.toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Back to project' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Approved by admin')).toBeInTheDocument();
  });
  it('exits the preview and removes the research screen from the DOM', async () => {
    const user = await preview(); await user.click(screen.getByRole('button', { name: 'Exit preview' }));
    await screen.findByRole('heading', { name: 'Welcome back.' }); expect(screen.queryByText('Approved by admin')).not.toBeInTheDocument();
  });
  it('supports the mobile navigation and how-it-works dialog', async () => {
    const user = await preview(); await user.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(screen.getByRole('button', { name: 'Close navigation' })).toBeInTheDocument(); await user.click(screen.getByRole('button', { name: 'Close navigation' }));
    await user.click(screen.getByRole('button', { name: 'How this works' }));
    expect(screen.getByRole('dialog', { name: 'A review-first research flow' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close A review-first research flow' })); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('Admin review', () => {
  it('loads private evidence and requires source selection plus explicit confirmation', async () => {
    const user = await preview(true); await screen.findByRole('textbox', { name: /Answer draft/ });
    const approve = screen.getByRole('button', { name: 'Approve answer' }); expect(approve).toBeDisabled();
    for (const box of screen.getAllByRole('checkbox')) await user.click(box); expect(approve).toBeEnabled();
    await user.click(approve); const dialog = screen.getByRole('dialog', { name: 'Confirm approval' });
    expect(screen.getByRole('textbox', { name: /Answer draft/ })).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Keep reviewing' })); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.click(approve); await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm approval' }));
    await screen.findByText('Answer approved and released to the requester.');
  });
  it('saves an edited draft without publishing it', async () => {
    const user = await preview(true); const draft = await screen.findByRole('textbox', { name: /Answer draft/ });
    await user.clear(draft); await user.type(draft, 'A synthetic manually reviewed statement [S1].');
    await user.click(screen.getByRole('button', { name: 'Save private draft' }));
    await screen.findByText('Draft saved privately. Nothing has been published.'); expect(screen.getByText('Awaiting admin review')).toBeInTheDocument();
  });
  it('requests clarification only after an admin writes and sends a public message', async () => {
    const user = await preview(true); await screen.findByRole('textbox', { name: /Answer draft/ }); await user.click(screen.getByRole('button', { name: 'Ask for clarification' }));
    await user.type(screen.getByRole('textbox', { name: 'Public message' }), 'Please provide the transaction facts.');
    await user.click(screen.getByRole('button', { name: 'Send decision' })); await screen.findByText('Decision sent to the requester.');
  });
  it('reports sample PDF unavailability instead of inventing a PDF link', async () => {
    const user = await preview(true); await screen.findByRole('textbox', { name: /Answer draft/ });
    const source = screen.getByText('Firm GST book · sample reference', { exact: true });
    await user.click(source);
    await user.click(within(source.closest('details')!).getByRole('button', { name: /View PDF source/ }));
    await screen.findByText('PDF viewing uses the real backend. The sample preview contains no PDF files.');
    expect(document.querySelector('a[href*="TOKEN"]')).toBeNull();
  });
  it('opens account creation and only assigns researcher plans', async () => {
    const user = await preview(true); await user.click(screen.getByRole('button', { name: 'People & access' }));
    await screen.findByRole('heading', { name: 'Create an account' });
    await user.type(screen.getByRole('textbox', { name: 'Username' }), 'sample.new'); await user.type(screen.getByLabelText('Initial password'), 'synthetic-password-fixture');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Access plan' }), 'plus'); await user.click(screen.getByRole('button', { name: 'Create researcher' }));
    await screen.findByText('sample.new', { exact: true }); expect(screen.getByLabelText('Initial password')).toHaveValue('');
    expect(screen.getByText(/This creates a researcher, never an admin/)).toBeInTheDocument();
  });
  it('shows the registered library and links to private upload/replacement', async () => {
    const user = await preview(true); await user.click(screen.getByRole('button', { name: 'Source library' }));
    await screen.findByRole('heading', { name: 'Know what’s behind the answer.' });
    expect(screen.getByText(/Uploads are staged privately/)).toBeInTheDocument(); expect(await screen.findAllByRole('button', { name: /View PDF/ })).toHaveLength(3);
  });
});

describe('Preview and history helpers', () => {
  it('keeps preview clients isolated and denies admin methods to a preview user', async () => {
    const one = new SampleClient('user'); const two = new SampleClient('user');
    await one.submit({ question: 'Unique sample question', as_of: '2023-03-01', topic_ids: ['other_gst'] }); expect(await one.queries()).toHaveLength(2); expect(await two.queries()).toHaveLength(1);
    await expect(one.users()).rejects.toMatchObject({ status: 403 });
  });
  it('groups follow-ups and uses the first question as the conversation title', () => {
    const base = { question: 'First question', id: 'a', conversation_id: 'c', created_at: '2026-10-21T00:00:00Z' } as Query;
    const groups = conversations([{ ...base, id: 'b', question: 'Follow-up', created_at: '2026-10-22T00:00:00Z' }, base]);
    expect(groups[0].title).toBe('First question'); expect(groups[0].rows.map((r) => r.id)).toEqual(['a', 'b']);
  });
});
