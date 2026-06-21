import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobListingCard } from '../../../../components/shared/JobCard/JobListingCard';
import type { Job } from '../../../../types';

describe('JobListingCard', () => {
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

  it('displays first 5 tags', () => {
    render(<JobListingCard job={mockJob} />);
    expect(screen.getByText('React')).toBeInTheDocument();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();
    expect(screen.getByText('GraphQL')).toBeInTheDocument();
    expect(screen.getByText('Testing')).toBeInTheDocument();
    expect(screen.getByText('CI/CD')).toBeInTheDocument();
    expect(screen.queryByText('Extra Tag')).not.toBeInTheDocument();
  });

  it('handles job with no tags', () => {
    const jobWithoutTags = { ...mockJob, tags: undefined };
    render(<JobListingCard job={jobWithoutTags} />);
    // Should render without errors
    expect(screen.getByText('Senior Frontend Engineer')).toBeInTheDocument();
  });

  it('filters out null values from tags', () => {
    const jobWithNullTags = {
      ...mockJob,
      tags: ['React', null, 'TypeScript', null, 'GraphQL'] as any,
    };
    render(<JobListingCard job={jobWithNullTags} />);
    expect(screen.getByText('React')).toBeInTheDocument();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();
    expect(screen.getByText('GraphQL')).toBeInTheDocument();
    // Should not crash or display null chips
  });

  it('filters out empty strings from tags', () => {
    const jobWithEmptyTags = {
      ...mockJob,
      tags: ['React', '', 'TypeScript', '', 'GraphQL'] as any,
    };
    render(<JobListingCard job={jobWithEmptyTags} />);
    expect(screen.getByText('React')).toBeInTheDocument();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();
    expect(screen.getByText('GraphQL')).toBeInTheDocument();
    // Empty strings should be filtered out
  });

  it('handles job with no optional fields', () => {
    const minimalJob: Job = {
      id: '2',
      source: 'backend-scraper',
      company: 'spotify',
      title: 'Engineer',
      createdAt: new Date().toISOString(),
      url: 'https://example.com/job/2',
      raw: {},
    };
    render(<JobListingCard job={minimalJob} />);
    expect(screen.getByText('Engineer')).toBeInTheDocument();
    expect(screen.queryByText('Engineering')).not.toBeInTheDocument();
    expect(screen.queryByText('Remote')).not.toBeInTheDocument();
  });
});
