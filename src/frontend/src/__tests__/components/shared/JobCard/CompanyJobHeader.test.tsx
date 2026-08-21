import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest';
import { act, render, screen, fireEvent } from '@testing-library/react';
import { CompanyJobHeader } from '../../../../components/shared/JobCard/CompanyJobHeader';
import { JobListingCard } from '../../../../components/shared/JobCard/JobListingCard';
import { renderWithProviders } from '../../../../test/testUtils';
import type { Job } from '../../../../types';

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

// Both flags are read as module constants at render time, and BOTH vary by
// environment: `.env.local` turns the custom-companies flag on for the running
// dev stack while CI leaves it off. Mocking them (rather than stubbing env vars)
// pins each test to the state it is actually asserting, so neither branch can
// pass or fail for environmental reasons.
const mocks = vi.hoisted(() => ({
  customCompanies: { isEnabled: true, isDiscoveryProgressEnabled: false },
  auth: { isAuthenticated: true },
}));
vi.mock('../../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: mocks.customCompanies,
}));
vi.mock('../../../../features/auth/useAuth', () => ({ useAuth: () => mocks.auth }));

/** The board the bug was reported on: id is opaque, name is the board host. */
const JANE_STREET = {
  id: 'u-ajhs85a7y0',
  displayName: 'www.janestreet.com',
  ats: 'discovered',
  boardToken: 'https://www.janestreet.com/join-jane-street/open-roles/',
  sourceId: 'custom:u-ajhs85a7y0',
  healthState: 'unverified',
  openJobCount: 90,
  lastSuccessAt: null,
  trackingStartedAt: null,
};

function customJob(): Job {
  return {
    id: 'custom-1',
    source: 'backend-scraper',
    company: JANE_STREET.id,
    title: 'Regulatory Exam Manager',
    location: 'New York, NY, US',
    createdAt: new Date().toISOString(),
    firstSeenAt: new Date().toISOString(),
    url: 'https://www.janestreet.com/join-jane-street/position/123/',
    raw: {},
  };
}

describe('CompanyJobHeader', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeAll(() => {
    globalThis.Request = TestRequest as unknown as typeof Request;
  });
  afterAll(() => {
    globalThis.Request = OriginalRequest;
  });

  beforeEach(() => {
    mocks.customCompanies.isEnabled = true;
    mocks.auth.isAuthenticated = true;
    fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ companies: [JANE_STREET] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
    );
    vi.stubGlobal('fetch', fetchMock);
  });

  describe('first-party companies (the ~130 in companies.ts)', () => {
    it('names the company from the static list and points the logo at its icon', () => {
      const { container } = render(
        <CompanyJobHeader companyId="spacex" title="Propulsion Engineer" logoSize={44} />
      );
      expect(screen.getByText('SpaceX')).toBeInTheDocument();
      expect(container.querySelector('img')).toHaveAttribute('src', '/logos/icons/spacex.png');
    });

    it('still falls back to the company initial when its icon file is missing', () => {
      const { container } = render(
        <CompanyJobHeader companyId="spacex" title="Propulsion Engineer" logoSize={44} />
      );
      fireEvent.error(container.querySelector('img')!);
      expect(screen.getByText('S')).toBeInTheDocument();
    });

    it('resolves without Redux, so a first-party card never subscribes to the store', () => {
      // A bare `render` (no Provider) would throw if the static branch touched
      // RTK Query. This is what keeps the per-card cost off the Recent Jobs and
      // companies pages, which mount hundreds of these.
      expect(() =>
        render(<CompanyJobHeader companyId="figma" title="Design Engineer" logoSize={44} />)
      ).not.toThrow();
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  describe('user-added companies (`u-…` runtime ids)', () => {
    it('names the board from the user-companies payload, not the internal id', async () => {
      renderWithProviders(
        <CompanyJobHeader
          companyId={JANE_STREET.id}
          title="Regulatory Exam Manager"
          logoSize={44}
        />
      );
      expect(await screen.findByText('www.janestreet.com')).toBeInTheDocument();
      expect(screen.queryByText(JANE_STREET.id)).not.toBeInTheDocument();
    });

    it('shows a neutral tile — no id initial, no hostname initial, no 404 fetch', async () => {
      const { container } = renderWithProviders(
        <CompanyJobHeader
          companyId={JANE_STREET.id}
          title="Regulatory Exam Manager"
          logoSize={44}
        />
      );
      await screen.findByText('www.janestreet.com');
      // Brand art is committed per first-party id, so there is nothing to
      // request here: no <img> at all, and the generic mark instead of "U"
      // (from the id) or "W" (from the hostname).
      expect(container.querySelector('img')).toBeNull();
      expect(container.querySelector('svg')).not.toBeNull();
      expect(screen.queryByText('U')).not.toBeInTheDocument();
      expect(screen.queryByText('W')).not.toBeInTheDocument();
    });

    it('omits the board line entirely while the name is unknown', async () => {
      // Signed out, so the owner-scoped lookup never runs. The card must show
      // the job title alone — never the raw id as a stand-in.
      mocks.auth.isAuthenticated = false;
      renderWithProviders(
        <CompanyJobHeader companyId={JANE_STREET.id} title="Regulatory Exam Manager" logoSize={44} />
      );
      // RTK Query dispatches its request a microtask after mount, so flush the
      // queue before asserting the negative — checking synchronously would pass
      // even with the sign-in gate removed.
      await act(async () => {
        await Promise.resolve();
      });
      expect(fetchMock).not.toHaveBeenCalled();
      expect(screen.getByText('Regulatory Exam Manager')).toBeInTheDocument();
      expect(screen.queryByText(JANE_STREET.id)).not.toBeInTheDocument();
      expect(screen.queryByText('www.janestreet.com')).not.toBeInTheDocument();
    });

    it('makes no request and mounts nothing store-connected while the flag is off', () => {
      // Flag-off must be byte-for-byte the pre-feature app. A bare `render`
      // proves the store-connected branch was never mounted.
      mocks.customCompanies.isEnabled = false;
      expect(() =>
        render(
          <CompanyJobHeader
            companyId={JANE_STREET.id}
            title="Regulatory Exam Manager"
            logoSize={44}
          />
        )
      ).not.toThrow();
      expect(screen.queryByText(JANE_STREET.id)).not.toBeInTheDocument();
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  describe('wired into the job card', () => {
    it('renders the board name over the title instead of the internal id', async () => {
      renderWithProviders(<JobListingCard job={customJob()} />);
      expect(await screen.findByText('www.janestreet.com')).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Regulatory Exam Manager' })).toBeInTheDocument();
      expect(screen.queryByText('u-ajhs85a7y0')).not.toBeInTheDocument();
    });
  });
});
