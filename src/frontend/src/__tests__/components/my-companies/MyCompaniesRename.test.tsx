/**
 * The inline rename affordance on a company card: the keyboard contract, the pending
 * state, focus handling, and what each failure puts on screen.
 *
 * A separate file from `MyCompaniesList.test.tsx` (which pins the list's polling, health
 * badges and flag-off rendering) because this is one feature of one card and it needs its
 * own routed fetch mock — the shared file's mock answers a GET and a DELETE and nothing
 * else.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesList } from '../../../components/my-companies/MyCompaniesList';
import type { UserCompany } from '../../../features/userCompanies/userCompaniesApi';

// `fetchBaseQuery` builds relative URLs, which Node's `Request` rejects.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (typeof input === 'string' && input.startsWith('/')) {
      super(`http://localhost${input}`, init);
    } else {
      super(input, init);
    }
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const COMPANY: UserCompany = {
  id: 'u-aaaaaaaaaa',
  // The owner's actual bug: a YC-hosted board for a company that is not YC.
  displayName: 'Ycombinator',
  ats: 'discovered',
  boardToken: 'https://www.ycombinator.com/companies/raindrop/jobs',
  sourceId: 'custom:u-aaaaaaaaaa',
  healthState: 'unverified',
  openJobCount: 7,
  lastSuccessAt: '2026-08-30T10:00:00Z',
  trackingStartedAt: null,
};

let fetchMock: ReturnType<typeof vi.fn>;

/**
 * Answers the list GET, and the rename PATCH with whatever this test wants.
 * `renamed` flips after a successful PATCH so the refetch returns the new name — which
 * is what makes "did the rename stick?" a real assertion rather than a rendering of the
 * mutation's own response.
 */
function routeFetch(patchResponse: () => Response) {
  let renamed = false;
  return vi.fn(async (input: RequestInfo | URL) => {
    const req = input as Request;
    if (req.method === 'PATCH') {
      const response = patchResponse();
      if (response.ok) renamed = true;
      return response;
    }
    return jsonResponse({
      companies: [{ ...COMPANY, displayName: renamed ? 'Raindrop' : COMPANY.displayName }],
    });
  });
}

async function openTheEditor() {
  const user = userEvent.setup();
  renderWithProviders(<MyCompaniesList />);
  await screen.findByTestId('my-company-row');
  await user.click(screen.getByTestId('my-company-rename'));
  return user;
}

beforeEach(() => {
  fetchMock = routeFetch(() => jsonResponse({ ...COMPANY, displayName: 'Raindrop' }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('renaming a company from its card', () => {
  it('shows a Rename button per row, labelled with that row', async () => {
    renderWithProviders(<MyCompaniesList />);
    await screen.findByTestId('my-company-row');
    expect(
      screen.getByRole('button', { name: 'Rename Ycombinator' })
    ).toBeInTheDocument();
  });

  it('swaps the title for a labelled text field seeded with the current name', async () => {
    await openTheEditor();

    const field = screen.getByLabelText('Company name');
    expect(field).toHaveValue('Ycombinator');
    // The title link is gone while editing — one name on screen, not two.
    expect(screen.queryByTestId('my-company-link')).not.toBeInTheDocument();
  });

  it('focuses the field on open, so a keyboard user can just type', async () => {
    await openTheEditor();
    await waitFor(() =>
      expect(screen.getByTestId('my-company-name-input').querySelector('input')).toBe(
        document.activeElement
      )
    );
  });

  it('commits on Enter and the row then shows the new name', async () => {
    const user = await openTheEditor();

    await user.clear(screen.getByLabelText('Company name'));
    await user.type(screen.getByLabelText('Company name'), 'Raindrop{Enter}');

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([input]) => (input as Request).method === 'PATCH'
      );
      expect(patch).toBeDefined();
      expect((patch![0] as Request).url).toMatch(
        /\/api\/users\/companies\/u-aaaaaaaaaa$/
      );
    });

    // The editor closes, and the refetched list — not the mutation's own response —
    // is what the row renders.
    await waitFor(() => expect(screen.getByTestId('my-company-link')).toBeInTheDocument());
    expect(within(screen.getByTestId('my-company-row')).getByText('Raindrop')).toBeInTheDocument();
  });

  it('commits on the Save button too', async () => {
    const user = await openTheEditor();

    await user.clear(screen.getByLabelText('Company name'));
    await user.type(screen.getByLabelText('Company name'), 'Raindrop');
    await user.click(screen.getByTestId('my-company-name-save'));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => (input as Request).method === 'PATCH')
      ).toBe(true)
    );
  });

  it('cancels on Escape, sending nothing and keeping the old name', async () => {
    const user = await openTheEditor();

    await user.clear(screen.getByLabelText('Company name'));
    await user.type(screen.getByLabelText('Company name'), 'Raindrop{Escape}');

    await waitFor(() => expect(screen.getByTestId('my-company-link')).toBeInTheDocument());
    expect(
      fetchMock.mock.calls.some(([input]) => (input as Request).method === 'PATCH')
    ).toBe(false);
    expect(within(screen.getByTestId('my-company-row')).getByText('Ycombinator')).toBeInTheDocument();
  });

  it('cancels on the Cancel button too', async () => {
    const user = await openTheEditor();
    await user.click(screen.getByTestId('my-company-name-cancel'));

    await waitFor(() => expect(screen.getByTestId('my-company-link')).toBeInTheDocument());
    expect(
      fetchMock.mock.calls.some(([input]) => (input as Request).method === 'PATCH')
    ).toBe(false);
  });

  it('returns focus to the Rename button when the editor closes', async () => {
    // Otherwise a keyboard user is dropped on <body> — at the top of the page — after
    // renaming a row halfway down it.
    const user = await openTheEditor();
    await user.click(screen.getByTestId('my-company-name-cancel'));

    await waitFor(() =>
      expect(screen.getByTestId('my-company-rename')).toBe(document.activeElement)
    );
  });

  it('sends nothing when the name was not actually changed', async () => {
    const user = await openTheEditor();
    await user.click(screen.getByTestId('my-company-name-save'));

    await waitFor(() => expect(screen.getByTestId('my-company-link')).toBeInTheDocument());
    expect(
      fetchMock.mock.calls.some(([input]) => (input as Request).method === 'PATCH')
    ).toBe(false);
  });

  it('disables Save while the field is blank, rather than sending an empty name', async () => {
    const user = await openTheEditor();
    await user.clear(screen.getByLabelText('Company name'));
    expect(screen.getByTestId('my-company-name-save')).toBeDisabled();

    await user.type(screen.getByLabelText('Company name'), '   ');
    expect(screen.getByTestId('my-company-name-save')).toBeDisabled();
  });

  it('caps what can be typed at the length the server accepts', async () => {
    await openTheEditor();
    expect(
      screen.getByTestId('my-company-name-input').querySelector('input')
    ).toHaveAttribute('maxlength', '100');
  });

  it('trims before sending', async () => {
    const user = await openTheEditor();
    await user.clear(screen.getByLabelText('Company name'));
    await user.type(screen.getByLabelText('Company name'), '  Raindrop  {Enter}');

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([input]) => (input as Request).method === 'PATCH'
      );
      expect(patch).toBeDefined();
    });
    const patch = fetchMock.mock.calls.find(
      ([input]) => (input as Request).method === 'PATCH'
    )!;
    await expect((patch[0] as Request).text()).resolves.toBe(
      JSON.stringify({ displayName: 'Raindrop' })
    );
  });
});

describe('when the rename fails', () => {
  /** Re-point the PATCH at a failure and open the editor. */
  async function failWith(response: () => Response) {
    fetchMock = routeFetch(response);
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const user = await openTheEditor();
    await user.clear(screen.getByLabelText('Company name'));
    await user.type(screen.getByLabelText('Company name'), 'Raindrop{Enter}');
    return user;
  }

  it('explains a too-long name and keeps the draft on screen', async () => {
    await failWith(() =>
      jsonResponse(
        { reason: 'name_too_long', detail: 'That name is 140 characters.' },
        422
      )
    );

    expect(await screen.findByText('That name is 140 characters.')).toBeInTheDocument();
    // Still open, still holding what they typed: closing here would throw the draft
    // away and leave the old name up with no explanation.
    expect(screen.getByLabelText('Company name')).toHaveValue('Raindrop');
  });

  it('explains an empty name', async () => {
    await failWith(() =>
      jsonResponse({ reason: 'name_empty', detail: "A company name can't be blank." }, 422)
    );
    expect(await screen.findByText("A company name can't be blank.")).toBeInTheDocument();
  });

  it('explains a company that is gone or was never yours', async () => {
    await failWith(() => jsonResponse({ detail: 'Company not found' }, 404));
    expect(
      await screen.findByText("That company isn't in your list any more.")
    ).toBeInTheDocument();
  });

  it('explains a rate limit', async () => {
    await failWith(() => jsonResponse({ detail: 'too fast' }, 429));
    expect(
      await screen.findByText("You're renaming too quickly. Try again in a moment.")
    ).toBeInTheDocument();
  });

  it('never renders a blank or [object Object] for an unexpected failure', async () => {
    await failWith(() => jsonResponse({}, 500));
    const message = await screen.findByText("That didn't save. Please try again.");
    expect(message).toBeInTheDocument();
  });

  it('marks the field invalid so the failure is announced, not just drawn', async () => {
    await failWith(() => jsonResponse({ reason: 'name_empty', detail: 'Blank.' }, 422));
    await screen.findByText('Blank.');
    expect(
      screen.getByTestId('my-company-name-input').querySelector('input')
    ).toHaveAttribute('aria-invalid', 'true');
  });
});
