import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { ResolveResultDisplay } from '../../../components/my-companies/ResolveResultDisplay';
import type {
  AlreadyPublicResponse,
  ResolveUrlResponse,
  UserCompany,
} from '../../../features/userCompanies/userCompaniesApi';

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

const FINAL_URL = 'https://boards.greenhouse.io/duolingo';

const OK_RESULT: ResolveUrlResponse = {
  candidate: {
    ats: 'greenhouse',
    boardToken: 'duolingo',
    providerConfig: {},
    sourceUrl: FINAL_URL,
  },
  probe: { ok: true, jobCount: 65, error: null },
  via: 'direct',
  hops: [],
  finalUrl: FINAL_URL,
};

const ADDED: UserCompany = {
  id: 'u-abc1234567',
  displayName: 'duolingo',
  ats: 'greenhouse',
  boardToken: 'duolingo',
  sourceId: 'custom:u-abc1234567',
  healthState: 'unverified',
  openJobCount: 0,
  lastSuccessAt: null,
  trackingStartedAt: null,
};

/**
 * The 200 body for a board we already publish. Spotify is not decoration: the owner
 * tracks it publicly on Lever AND had added it privately, so one company had two
 * scrapers and two job sets. This is the response that stops the second one.
 */
const ALREADY_PUBLIC: AlreadyPublicResponse = {
  status: 'already_public',
  detail:
    'That URL is the same job board as our public Spotify page, so there is nothing to set up — its hiring trend is already there.',
  companyId: 'spotify',
  displayName: 'Spotify',
  finalUrl: FINAL_URL,
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResolveResultDisplay — Add company CTA', () => {
  it('shows the "Track this company" button on a readable board (probe.ok)', () => {
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);
    expect(screen.getByTestId('add-company-button')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /track this company/i })).toBeInTheDocument();
  });

  it('does NOT show the Add button when the board could not be read (probe.ok === false)', () => {
    renderWithProviders(
      <ResolveResultDisplay
        result={{
          ...OK_RESULT,
          probe: { ok: false, jobCount: 0, error: 'HTTP 404' },
        }}
      />
    );
    expect(screen.queryByTestId('add-company-button')).not.toBeInTheDocument();
  });

  it('POSTs the finalUrl and confirms with a link to the trend page on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse(ADDED, 201));
    const user = userEvent.setup();
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

    await user.click(screen.getByTestId('add-company-button'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const req = fetchMock.mock.calls[0][0] as Request;
    expect(req.method).toBe('POST');
    expect(req.url).toMatch(/\/api\/users\/companies$/);
    await expect(req.text()).resolves.toBe(JSON.stringify({ url: FINAL_URL }));

    // Success confirmation + a link onward to the private trend page.
    const success = await screen.findByTestId('add-company-success');
    expect(success).toHaveTextContent(/now tracking duolingo/i);
    const link = screen.getByTestId('view-company-link');
    expect(link).toHaveAttribute('href', '/add-companies/u-abc1234567');
  });

  it('renders the 422 reason instead of crashing', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { reason: 'empty', detail: 'That board has no open jobs.', finalUrl: FINAL_URL },
        422
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

    await user.click(screen.getByTestId('add-company-button'));

    const error = await screen.findByTestId('add-company-error');
    // The headline is the reason, in English; the body is the server's sentence.
    expect(error).toHaveTextContent('That board has no open jobs right now');
    expect(error).toHaveTextContent(/no open jobs\./i);
    // ...and NOT the raw token. For a reason we have copy for, "(code: empty)" was the
    // same fact a second time, in machine language, mid-sentence.
    expect(error).not.toHaveTextContent('code: empty');
    expect(screen.queryByTestId('add-company-success')).not.toBeInTheDocument();
  });

  it('still prints the raw code for a reason this build has no copy for', async () => {
    // The other half of the cut above. A newer server can name a reason we have no
    // headline for; there the headline is generic, so the token is the only thing that
    // makes a screenshot diagnosable and it has to survive.
    fetchMock.mockResolvedValue(
      jsonResponse(
        { reason: 'some_future_reason', detail: 'The board was rejected.', finalUrl: FINAL_URL },
        422
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

    await user.click(screen.getByTestId('add-company-button'));

    const error = await screen.findByTestId('add-company-error');
    expect(error).toHaveTextContent("We couldn't add that company");
    expect(error).toHaveTextContent('code: some_future_reason');
  });

  it('treats an idempotent 200 (already added) as success, not a crash', async () => {
    fetchMock.mockResolvedValue(jsonResponse(ADDED, 200));
    const user = userEvent.setup();
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

    await user.click(screen.getByTestId('add-company-button'));

    expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
  });

  describe('a board we already publish', () => {
    it('links to the public hiring trend instead of confirming a new company', async () => {
      fetchMock.mockResolvedValue(jsonResponse(ALREADY_PUBLIC, 200));
      const user = userEvent.setup();
      renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

      await user.click(screen.getByTestId('add-company-button'));

      const notice = await screen.findByTestId('already-public');
      expect(notice).toHaveTextContent(/we already track spotify/i);
      expect(screen.getByTestId('already-public-link')).toHaveAttribute(
        'href',
        '/companies?company=spotify',
      );
      // Nothing was created, so the "Now tracking …" confirmation must not appear —
      // that alert is the one that would send the user to a private page that has no
      // company behind it.
      expect(screen.queryByTestId('add-company-success')).not.toBeInTheDocument();
      // It is not an error either: nothing failed and there is nothing to fix.
      expect(screen.queryByTestId('add-company-error')).not.toBeInTheDocument();
    });

    it('is terminal — there is no way to add a duplicate of a board we publish', async () => {
      // CHANGED, deliberately. This used to assert a "Track it separately anyway"
      // button. This component only renders after the resolver named an
      // `(ats, boardToken)` pair, so the only `already_public` that reaches it is the
      // EXACT board-token match — the user pasted a board we already publish, by its own
      // identifier. A private duplicate re-scrapes the same feed for a chart whose
      // history starts today, with the full history one click away in this very notice.
      // Offering a strictly worse option is not user agency.
      fetchMock.mockResolvedValue(jsonResponse(ALREADY_PUBLIC, 200));
      const user = userEvent.setup();
      renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

      await user.click(screen.getByTestId('add-company-button'));

      const notice = await screen.findByTestId('already-public');
      expect(notice).toHaveTextContent(/we already track spotify/i);
      expect(screen.queryByTestId('track-anyway-button')).not.toBeInTheDocument();
      // The link is the ONLY way onward from here.
      expect(screen.getByTestId('already-public-link')).toBeInTheDocument();
    });

    it('sends exactly one add — nothing retries into a duplicate', async () => {
      // The other half: with no button there is no second POST, so a board we publish
      // costs exactly one request and creates nothing.
      fetchMock.mockResolvedValue(jsonResponse(ALREADY_PUBLIC, 200));
      const user = userEvent.setup();
      renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

      await user.click(screen.getByTestId('add-company-button'));
      await screen.findByTestId('already-public');

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const req = fetchMock.mock.calls[0][0] as Request;
      await expect(req.text()).resolves.toBe(JSON.stringify({ url: FINAL_URL }));
    });

    it('does not send trackAnyway on the first, ordinary add', async () => {
      // The check has to be the DEFAULT. If the flag ever rode along on the first
      // submit the dedupe would be dead code that still passes its own tests.
      fetchMock.mockResolvedValue(jsonResponse(ADDED, 201));
      const user = userEvent.setup();
      renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

      await user.click(screen.getByTestId('add-company-button'));

      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      const req = fetchMock.mock.calls[0][0] as Request;
      await expect(req.text()).resolves.toBe(JSON.stringify({ url: FINAL_URL }));
    });
  });
});
