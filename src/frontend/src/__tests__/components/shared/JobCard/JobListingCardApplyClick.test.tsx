import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createEvent, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { JobListingCard } from '../../../../components/shared/JobCard/JobListingCard';
import type { Job } from '../../../../types';

const track = vi.fn();
const hookArgs = vi.fn();
vi.mock('../../../../features/analytics/useTrackApplyClick', () => ({
  useTrackApplyClick: (job: Job, surface: string | undefined) => {
    hookArgs(job.id, surface);
    return track;
  },
}));
vi.mock('../../../../hooks/useIsMobile', () => ({ useIsMobile: () => false }));

const job: Job = {
  id: '42',
  source: 'backend-scraper',
  sourceId: 'greenhouse_api',
  company: 'spacex',
  title: 'Backend Engineer',
  createdAt: new Date().toISOString(),
  firstSeenAt: new Date().toISOString(),
  url: 'https://example.com/42',
  raw: {},
};

describe('JobListingCard apply-click tracking', () => {
  beforeEach(() => {
    track.mockReset();
    hookArgs.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('passes the surface to the tracker', () => {
    render(<JobListingCard job={job} surface="recent" />);
    expect(hookArgs).toHaveBeenCalledWith('42', 'recent');
  });

  it('logs one click on Apply without blocking the native link', () => {
    vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<JobListingCard job={job} surface="recent" />);
    const apply = screen.getByRole('link', { name: 'Apply' });
    const click = createEvent.click(apply);
    fireEvent(apply, click);
    expect(track).toHaveBeenCalledTimes(1);
    // The anchor's own navigation (target=_blank) is left to happen.
    expect(click.defaultPrevented).toBe(false);
    // And it does not bubble into the card's own open-the-posting handler.
    expect(window.open).not.toHaveBeenCalled();
  });

  it('logs one click when the card body opens the posting', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<JobListingCard job={job} surface="company" />);
    fireEvent.click(screen.getByRole('heading', { name: 'Backend Engineer' }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledTimes(1);
  });

  it('does not log a card-body click that only navigates in-app (card link)', () => {
    render(
      <MemoryRouter>
        <JobListingCard job={job} surface="landing" cardLink={{ to: '/jobs', label: 'See jobs' }} />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByRole('heading', { name: 'Backend Engineer' }));
    expect(track).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('link', { name: 'Apply' }));
    expect(track).toHaveBeenCalledTimes(1);
  });
});
