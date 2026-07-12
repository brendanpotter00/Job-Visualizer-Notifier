import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobListingCard } from '../../../../components/shared/JobCard/JobListingCard';
import { useIsMobile } from '../../../../hooks/useIsMobile';
import { RESPONSIVE } from '../../../../config/responsive';
import type { Job } from '../../../../types';

// JobListingCard branches on useIsMobile() for the compact mobile layout. We
// mock the hook (rather than @mui/material/useMediaQuery) because useIsMobile
// imports useMediaQuery from the '@mui/material' barrel, which the submodule
// mock used by RootLayout.test.tsx does not reach. Mocking the hook directly is
// the established way to control a custom breakpoint hook. Default to desktop
// (false) in beforeEach so the existing text/link/img tests keep their original
// desktop behavior and the mock never leaks a mobile value between tests.
vi.mock('../../../../hooks/useIsMobile');

describe('JobListingCard', () => {
  beforeEach(() => {
    vi.mocked(useIsMobile).mockReturnValue(false);
  });

  const mockJob: Job = {
    id: '1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Senior Frontend Engineer',
    department: 'Engineering',
    location: 'San Francisco, CA',
    isRemote: true,
    employmentType: 'Full-time',
    createdAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
    firstSeenAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
    url: 'https://example.com/job/1',
    tags: ['React', 'TypeScript', 'GraphQL', 'Testing', 'CI/CD', 'Extra Tag'],
    raw: {},
  };

  it('renders the job title as a heading', () => {
    render(<JobListingCard job={mockJob} />);
    expect(
      screen.getByRole('heading', { name: 'Senior Frontend Engineer' })
    ).toBeInTheDocument();
  });

  it('renders a black Apply link to the job posting', () => {
    render(<JobListingCard job={mockJob} />);
    const apply = screen.getByRole('link', { name: 'Apply' });
    expect(apply).toHaveAttribute('href', 'https://example.com/job/1');
    expect(apply).toHaveAttribute('target', '_blank');
    expect(apply).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders the company logo (resolved from job.company)', () => {
    // Guards the CompanyLogo wiring: 'spacex' -> /logos/icons/spacex.png. The logo
    // is decorative (the company name is shown as adjacent text), so it has an
    // empty alt and is queried by src rather than accessible name.
    const { container } = render(<JobListingCard job={mockJob} />);
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute('src', '/logos/icons/spacex.png');
    // It must not announce the company name a second time.
    expect(screen.queryByRole('img', { name: 'SpaceX' })).not.toBeInTheDocument();
  });

  it('displays relative time posted', () => {
    render(<JobListingCard job={mockJob} />);
    expect(screen.getByText(/2 hours ago/i)).toBeInTheDocument();
  });

  it('keys the "Posted X ago" label off firstSeenAt, not the stale ATS createdAt', () => {
    // Reposted-listing case: postedOn (createdAt) is months stale while the job was
    // first seen an hour ago. The label must reflect firstSeenAt so the top-of-recent
    // cards read consistently with why they rank first.
    const repostedJob: Job = {
      ...mockJob,
      createdAt: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString(), // ~3 months ago
      firstSeenAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(), // 1 hour ago
    };
    render(<JobListingCard job={repostedJob} />);
    expect(screen.getByText(/about 1 hour ago/i)).toBeInTheDocument();
    expect(screen.queryByText(/months ago/i)).not.toBeInTheDocument();
  });

  it('displays department chip', () => {
    render(<JobListingCard job={mockJob} />);
    expect(screen.getByText('Engineering')).toBeInTheDocument();
  });

  it('displays location chip', () => {
    render(<JobListingCard job={mockJob} />);
    expect(screen.getByText('San Francisco, CA')).toBeInTheDocument();
  });

  it('renders one chip per canonical tag when job.locations is populated', () => {
    const multiLocationJob: Job = {
      ...mockJob,
      location: 'Austin, TX, USA; Atlanta, GA, USA', // raw fallback NOT used when tags exist
      locations: [
        {
          canonicalName: 'Austin, TX, US',
          kind: 'city',
          city: 'Austin',
          region: 'TX',
          country: 'US',
          remoteScope: null,
          isPrimary: true,
        },
        {
          canonicalName: 'Atlanta, GA, US',
          kind: 'city',
          city: 'Atlanta',
          region: 'GA',
          country: 'US',
          remoteScope: null,
          isPrimary: false,
        },
      ],
    };
    render(<JobListingCard job={multiLocationJob} />);

    // One chip per canonical tag...
    expect(screen.getByText('Austin, TX, US')).toBeInTheDocument();
    expect(screen.getByText('Atlanta, GA, US')).toBeInTheDocument();
    // ...and the raw location string is NOT rendered when tags are present.
    expect(screen.queryByText('Austin, TX, USA; Atlanta, GA, USA')).not.toBeInTheDocument();
  });

  it('falls back to the raw job.location string when job.locations is empty', () => {
    const noTagsJob: Job = {
      ...mockJob,
      location: 'Remote - Worldwide',
      locations: [],
    };
    render(<JobListingCard job={noTagsJob} />);
    expect(screen.getByText('Remote - Worldwide')).toBeInTheDocument();
  });

  it('falls back to the raw job.location string when job.locations is undefined', () => {
    const undefinedTagsJob: Job = {
      ...mockJob,
      location: 'Hawthorne, CA',
      locations: undefined,
    };
    render(<JobListingCard job={undefinedTagsJob} />);
    expect(screen.getByText('Hawthorne, CA')).toBeInTheDocument();
  });

  it('displays remote chip when job is remote', () => {
    render(<JobListingCard job={mockJob} />);
    expect(screen.getByText('Remote')).toBeInTheDocument();
  });

  it('does not display remote chip when job is not remote', () => {
    const nonRemoteJob = { ...mockJob, isRemote: false };
    render(<JobListingCard job={nonRemoteJob} />);
    expect(screen.queryByText('Remote')).not.toBeInTheDocument();
  });

  it('displays employment type chip', () => {
    render(<JobListingCard job={mockJob} />);
    expect(screen.getByText('Full-time')).toBeInTheDocument();
  });

  it('handles job with no tags', () => {
    const jobWithoutTags = { ...mockJob, tags: undefined };
    render(<JobListingCard job={jobWithoutTags} />);
    // Should render without errors
    expect(screen.getByText('Senior Frontend Engineer')).toBeInTheDocument();
  });

  it('handles job with no optional fields', () => {
    const minimalJob: Job = {
      id: '2',
      source: 'backend-scraper',
      company: 'spotify',
      title: 'Engineer',
      createdAt: new Date().toISOString(),
      firstSeenAt: new Date().toISOString(),
      url: 'https://example.com/job/2',
      raw: {},
    };
    render(<JobListingCard job={minimalJob} />);
    expect(screen.getByText('Engineer')).toBeInTheDocument();
    expect(screen.queryByText('Engineering')).not.toBeInTheDocument();
    expect(screen.queryByText('Remote')).not.toBeInTheDocument();
  });

  // Regression guard for Ledger #2: the compact mobile overrides are gated on
  // useIsMobile(), so desktop must receive NO override and stay byte-for-byte
  // identical, while mobile shrinks the logo and chips.
  describe('responsive (mobile vs desktop)', () => {
    // The logo size is applied to the CompanyLogo tile (the <img>'s parent Box)
    // as width/height; getComputedStyle reports it deterministically in jsdom.
    function logoTile(container: HTMLElement): HTMLElement {
      const img = container.querySelector('img');
      expect(img).not.toBeNull();
      return img!.parentElement as HTMLElement;
    }

    // The mobile chip override is emitted as a descendant rule scoped to the
    // CardContent's own Emotion class (`.css-xxx .MuiChip-root{height:20px}`).
    // Scoping by class avoids cross-test stylesheet contamination.
    function scopedChipRule(container: HTMLElement): string {
      const content = container.querySelector('.MuiCardContent-root') as HTMLElement;
      const cls = Array.from(content.classList).find((c) => c.startsWith('css-'));
      if (!cls) return '';
      const styleText = Array.from(document.querySelectorAll('style'))
        .map((s) => s.textContent ?? '')
        .join('\n');
      const escaped = cls.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const re = new RegExp(`\\.${escaped}\\s+\\.MuiChip-root\\{[^}]*\\}`, 'g');
      return (styleText.match(re) ?? []).join('\n');
    }

    it('desktop (isMobile=false): renders the logo at 44px and applies NO chip override', () => {
      vi.mocked(useIsMobile).mockReturnValue(false);
      const { container } = render(<JobListingCard job={mockJob} />);

      const tile = logoTile(container);
      expect(tile).toHaveStyle({
        width: `${RESPONSIVE.logoSize.default}px`,
        height: `${RESPONSIVE.logoSize.default}px`,
      });

      // No mobile chip-height override is emitted on desktop.
      expect(scopedChipRule(container)).toBe('');
    });

    it('mobile (isMobile=true): renders the logo at 32px and applies the chip override', () => {
      vi.mocked(useIsMobile).mockReturnValue(true);
      const { container } = render(<JobListingCard job={mockJob} />);

      const tile = logoTile(container);
      expect(tile).toHaveStyle({
        width: `${RESPONSIVE.logoSize.compact}px`,
        height: `${RESPONSIVE.logoSize.compact}px`,
      });

      // The compact chip height is applied via the descendant override.
      expect(scopedChipRule(container)).toContain(`height:${RESPONSIVE.jobCard.chipHeight}px`);
    });

    it('mobile shrinks the Apply button below the theme 44px floor', () => {
      vi.mocked(useIsMobile).mockReturnValue(true);
      render(<JobListingCard job={mockJob} />);

      const apply = screen.getByRole('link', { name: 'Apply' });
      expect(apply).toHaveStyle({ minHeight: `${RESPONSIVE.jobCard.applyMinHeight}px` });
    });
  });
});
