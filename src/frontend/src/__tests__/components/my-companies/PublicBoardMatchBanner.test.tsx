import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesList } from '../../../components/my-companies/MyCompaniesList';
import { PublicBoardMatchBanner } from '../../../components/my-companies/PublicBoardMatchBanner';
import { isPublicMatchDismissed } from '../../../components/my-companies/publicMatchDismissal';
import type {
  PublicBoardMatch,
  UserCompany,
} from '../../../features/userCompanies/userCompaniesApi';

/**
 * "This looks like Spotify, which we already track — 70 of 81 roles match."
 *
 * The properties under test are the ones that decide whether this banner helps or erodes
 * trust in the whole add flow:
 *
 * - it names the company AND carries the evidence. "This looks like Spotify" is a claim the
 *   user cannot check; "70 of 81 roles match" is why they should believe it;
 * - it is a SUGGESTION — informational, never an error. Nothing failed, the board tracks
 *   fine, and ignoring this forever is a supported outcome;
 * - the destructive action routes through the row's ordinary remove handler, so the banner
 *   cannot become a one-click delete just because a heuristic fired;
 * - and it SAYS it deletes. The handler behind that button issues
 *   `DELETE FROM job_listings WHERE source_id = 'custom:<id>'`; the copy used to promise
 *   only that the history "will no longer be collected", which describes a pause. These
 *   assertions are on the words, because the words were the bug;
 * - DISMISSAL PERSISTS across a reload. A suggestion that comes back after being dismissed
 *   is one people learn to ignore, and this is the only rail against that; and
 * - a *different* later match is a different claim and is still shown — the user dismissed
 *   "this is Spotify", not "never tell me anything".
 */

function match(overrides: Partial<PublicBoardMatch> = {}): PublicBoardMatch {
  return {
    companyId: 'spotify',
    displayName: 'Spotify',
    shared: 70,
    candidateTitles: 81,
    detectedAt: '2026-08-20T12:00:00Z',
    ...overrides,
  };
}

function company(publicMatch: PublicBoardMatch | null): UserCompany {
  return {
    id: 'u-lifeatspot',
    displayName: 'Lifeatspotify',
    ats: 'discovered',
    boardToken: 'https://www.lifeatspotify.com/jobs',
    sourceId: 'custom:u-lifeatspot',
    healthState: 'healthy',
    openJobCount: 81,
    lastSuccessAt: '2026-08-20T12:00:00Z',
    trackingStartedAt: '2026-08-20T12:00:00Z',
    publicMatch,
  };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe('PublicBoardMatchBanner', () => {
  it('names the company and carries the numbers behind the claim', () => {
    renderWithProviders(
      <PublicBoardMatchBanner company={company(match())} onRemove={vi.fn()} />,
    );

    const banner = screen.getByTestId('public-board-match');
    expect(banner).toHaveTextContent('This looks like Spotify, which we already track');
    expect(banner).toHaveTextContent('70 of 81 roles on this board match');
  });

  it('is informational, not an error — nothing failed and nothing is broken', () => {
    renderWithProviders(
      <PublicBoardMatchBanner company={company(match())} onRemove={vi.fn()} />,
    );

    // MUI stamps the severity onto the class; `alert` role would be identical for a
    // failure, and the difference between "you have a problem" and "here's a shortcut" is
    // the entire tone of this banner.
    expect(screen.getByTestId('public-board-match').className).toContain(
      'MuiAlert-colorInfo',
    );
  });

  it('links to the matched company hiring trend, not to the private board', () => {
    renderWithProviders(
      <PublicBoardMatchBanner company={company(match())} onRemove={vi.fn()} />,
    );

    expect(screen.getByTestId('public-board-match-link')).toHaveAttribute(
      'href',
      '/companies?company=spotify',
    );
  });

  it('falls back to the trends page for a company this build does not know', () => {
    // A company seeded on the server but not in this bundle's compile-time list. Deep
    // linking `?company=<unknown>` silently lands the user on somebody else's chart right
    // after being told "here's Spotify" — the same guard `AlreadyPublicNotice` carries.
    renderWithProviders(
      <PublicBoardMatchBanner
        company={company(match({ companyId: 'not-in-this-build', displayName: 'Newco' }))}
        onRemove={vi.fn()}
      />,
    );

    const link = screen.getByTestId('public-board-match-link');
    expect(link).toHaveAttribute('href', '/companies');
    expect(link).toHaveTextContent('Open Company Hiring Trends');
  });

  it('hands Remove to the row handler rather than deleting anything itself', async () => {
    const onRemove = vi.fn();
    const row = company(match());
    renderWithProviders(<PublicBoardMatchBanner company={row} onRemove={onRemove} />);

    await userEvent.click(screen.getByTestId('public-board-match-remove'));

    // The row's handler opens the ordinary confirmation dialog. The banner must not be a
    // shortcut around the confirm just because a heuristic suggested the removal.
    expect(onRemove).toHaveBeenCalledWith(row);
  });

  it('calls the destructive button a delete and says what it destroys', () => {
    renderWithProviders(
      <PublicBoardMatchBanner company={company(match())} onRemove={vi.fn()} />,
    );

    // "Remove this board" reads like "stop watching it". The handler behind it deletes
    // every job row under `custom:<id>` — the label has to carry that.
    expect(screen.getByTestId('public-board-match-remove')).toHaveTextContent(
      'Delete this board',
    );

    const note = screen.getByTestId('public-board-match-delete-note');
    expect(note).toHaveTextContent('Deleting is permanent');
    expect(note).toHaveTextContent('erases the jobs already collected for this board');
    // And the reassurance that makes taking the suggestion safe: the public company is a
    // different row and this never touches it.
    expect(note).toHaveTextContent("Spotify's public page is a separate record");
  });

  it('renders nothing when the backend found no match', () => {
    renderWithProviders(
      <PublicBoardMatchBanner company={company(null)} onRemove={vi.fn()} />,
    );

    expect(screen.queryByTestId('public-board-match')).not.toBeInTheDocument();
  });

  it('renders nothing when the field is absent entirely (older server)', () => {
    const { publicMatch: _omitted, ...withoutField } = company(match());
    renderWithProviders(
      <PublicBoardMatchBanner company={withoutField as UserCompany} onRemove={vi.fn()} />,
    );

    expect(screen.queryByTestId('public-board-match')).not.toBeInTheDocument();
  });

  it('hides on dismiss and the dismissal SURVIVES A RELOAD', async () => {
    const row = company(match());
    const first = renderWithProviders(
      <PublicBoardMatchBanner company={row} onRemove={vi.fn()} />,
    );

    await userEvent.click(screen.getByTestId('public-board-match-dismiss'));
    expect(screen.queryByTestId('public-board-match')).not.toBeInTheDocument();

    // The reload: tear the tree down completely and mount it again from the same payload
    // the server keeps sending. Only persisted state can survive that.
    first.unmount();
    renderWithProviders(<PublicBoardMatchBanner company={row} onRemove={vi.fn()} />);

    expect(screen.queryByTestId('public-board-match')).not.toBeInTheDocument();
    expect(isPublicMatchDismissed('u-lifeatspot', 'spotify')).toBe(true);
  });

  it('still shows a DIFFERENT later match after one was dismissed', async () => {
    const row = company(match());
    const first = renderWithProviders(
      <PublicBoardMatchBanner company={row} onRemove={vi.fn()} />,
    );
    await userEvent.click(screen.getByTestId('public-board-match-dismiss'));
    first.unmount();

    renderWithProviders(
      <PublicBoardMatchBanner
        company={company(match({ companyId: 'stripe', displayName: 'Stripe' }))}
        onRemove={vi.fn()}
      />,
    );

    // Dismissing "this is Spotify" is not "never tell me anything".
    expect(screen.getByTestId('public-board-match')).toHaveTextContent(
      'This looks like Stripe',
    );
  });

  it('does not resurface for a different board that matches the same company', async () => {
    const first = renderWithProviders(
      <PublicBoardMatchBanner company={company(match())} onRemove={vi.fn()} />,
    );
    await userEvent.click(screen.getByTestId('public-board-match-dismiss'));
    first.unmount();

    const otherBoard = { ...company(match()), id: 'u-otherboard' };
    renderWithProviders(
      <PublicBoardMatchBanner company={otherBoard} onRemove={vi.fn()} />,
    );

    // A different board is a different claim — the dismissal is per (board, match) pair.
    expect(screen.getByTestId('public-board-match')).toBeInTheDocument();
  });

  it('still hides for the session when localStorage refuses to persist', async () => {
    const setItem = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('QuotaExceededError');
      });

    renderWithProviders(
      <PublicBoardMatchBanner company={company(match())} onRemove={vi.fn()} />,
    );
    await userEvent.click(screen.getByTestId('public-board-match-dismiss'));

    // Storage can be disabled or full. Losing the persistence is acceptable; throwing out
    // of a click handler and taking the whole list down with it is not.
    expect(screen.queryByTestId('public-board-match')).not.toBeInTheDocument();
    setItem.mockRestore();
  });

  it('reads a singular role correctly', () => {
    renderWithProviders(
      <PublicBoardMatchBanner
        company={company(match({ shared: 1, candidateTitles: 1 }))}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByTestId('public-board-match')).toHaveTextContent(
      '1 of 1 role on this board match',
    );
  });
});

/**
 * The banner ON the row — the one line of wiring in `MyCompaniesList`, and the one thing a
 * component-level test cannot see: that Remove from the banner reaches the SAME
 * confirmation dialog the row's own Remove button opens.
 */
describe('PublicBoardMatchBanner on a company row', () => {
  const OriginalRequest = globalThis.Request;
  class TestRequest extends OriginalRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      // `fetchBaseQuery` builds relative URLs, which Node's `Request` rejects.
      if (typeof input === 'string' && input.startsWith('/')) {
        super(`http://localhost${input}`, init);
      } else {
        super(input, init);
      }
    }
  }

  beforeEach(() => {
    globalThis.Request = TestRequest as unknown as typeof Request;
  });

  afterEach(() => {
    globalThis.Request = OriginalRequest;
    vi.restoreAllMocks();
  });

  function listResponse(row: UserCompany) {
    return new Response(JSON.stringify({ companies: [row] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }

  it('renders on the row and its Remove opens the ordinary confirmation dialog', async () => {
    const fetchMock = vi.fn().mockResolvedValue(listResponse(company(match())));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderWithProviders(<MyCompaniesList />);

    const banner = await screen.findByTestId('public-board-match');
    expect(banner).toHaveTextContent('This looks like Spotify');

    await userEvent.click(screen.getByTestId('public-board-match-remove'));

    // Never a one-click delete: the banner suggests, the dialog confirms.
    expect(
      await screen.findByText('Delete this company and its job history?'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('my-company-remove-confirm')).toBeInTheDocument();
  });

  it('warns in the dialog that the collected jobs are destroyed, not just paused', async () => {
    const fetchMock = vi.fn().mockResolvedValue(listResponse(company(match())));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderWithProviders(<MyCompaniesList />);

    await screen.findByTestId('public-board-match');
    await userEvent.click(screen.getByTestId('public-board-match-remove'));

    // The exact promise the old copy made ("no longer be collected") described a pause.
    // What actually runs is a DELETE of every job row under `custom:<id>`, so the dialog
    // has to name the destruction, the size of it, and the fact that re-adding starts over.
    const body = await screen.findByText(/deletes every job collected for it/i);
    expect(body).toHaveTextContent('81 open now');
    expect(body).toHaveTextContent('closed ones behind its hiring chart');
    expect(body).toHaveTextContent('This is a delete, not a pause');
    expect(body).toHaveTextContent('starts the chart over from zero');
    expect(body).not.toHaveTextContent(/no longer be collected/i);
  });

  it('leaves a row with no match rendering exactly as it did before', async () => {
    const fetchMock = vi.fn().mockResolvedValue(listResponse(company(null)));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderWithProviders(<MyCompaniesList />);

    await screen.findByTestId('my-company-row');
    expect(screen.queryByTestId('public-board-match')).not.toBeInTheDocument();
  });
});
