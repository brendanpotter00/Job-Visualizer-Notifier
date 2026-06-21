import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RecentJobCard } from '../../../../components/recent-jobs-page/RecentJobCard/RecentJobCard';
import type { Job } from '../../../../types';

const mockJob: Job = {
  id: '1',
  source: 'backend-scraper',
  company: 'spacex',
  title: 'Backend Engineer',
  location: 'San Francisco, CA',
  isRemote: false,
  employmentType: 'Full-time',
  createdAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  url: 'https://example.com/job/1',
  raw: {},
};

describe('RecentJobCard', () => {
  it('renders the company name header and job title', () => {
    render(<RecentJobCard job={mockJob} companyName="SpaceX" />);
    expect(screen.getByText('SpaceX')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument();
  });

  it('renders the company logo wired from job.company, decoratively', () => {
    const { container } = render(<RecentJobCard job={mockJob} companyName="SpaceX" />);
    // The logo is decorative here (the name is already visible text), so it has
    // an empty alt and is queried by src rather than accessible name.
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute('src', '/logos/icons/spacex.png');
    // It must not announce the company name a second time.
    expect(screen.queryByRole('img', { name: 'SpaceX' })).not.toBeInTheDocument();
  });
});
