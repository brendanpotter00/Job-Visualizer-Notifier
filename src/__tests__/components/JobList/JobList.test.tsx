import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobList } from '../../../components/JobList/JobList';
import type { Job } from '../../../types';

describe('JobList', () => {
  const mockJobs: Job[] = [
    {
      id: '1',
      source: 'greenhouse',
      company: 'spacex',
      title: 'Frontend Engineer',
      createdAt: new Date().toISOString(),
      url: 'https://example.com/job/1',
      classification: {
        isSoftwareAdjacent: true,
        category: 'frontend',
        confidence: 0.9,
        matchedKeywords: ['react'],
      },
      raw: {},
    },
    {
      id: '2',
      source: 'lever',
      company: 'nominal',
      title: 'Backend Engineer',
      createdAt: new Date().toISOString(),
      url: 'https://example.com/job/2',
      classification: {
        isSoftwareAdjacent: true,
        category: 'backend',
        confidence: 0.85,
        matchedKeywords: ['node'],
      },
      raw: {},
    },
  ];

  it('displays loading skeletons when loading', () => {
    const { container } = render(<JobList jobs={[]} isLoading={true} />);
    // Check for skeleton elements (MUI Skeleton uses span with specific class)
    const skeletons = container.querySelectorAll('.MuiSkeleton-root');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('displays empty state when no jobs', () => {
    render(<JobList jobs={[]} isLoading={false} />);
    expect(screen.getByText(/no jobs found matching your filters/i)).toBeInTheDocument();
  });

  it('displays job count with correct pluralization for multiple jobs', () => {
    render(<JobList jobs={mockJobs} isLoading={false} />);
    expect(screen.getByText('2 jobs found')).toBeInTheDocument();
  });

  it('displays job count with correct pluralization for single job', () => {
    render(<JobList jobs={[mockJobs[0]]} isLoading={false} />);
    expect(screen.getByText('1 job found')).toBeInTheDocument();
  });

  it('renders all jobs', () => {
    render(<JobList jobs={mockJobs} isLoading={false} />);
    expect(screen.getByText('Frontend Engineer')).toBeInTheDocument();
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
  });

  it('does not show jobs when loading', () => {
    render(<JobList jobs={mockJobs} isLoading={true} />);
    expect(screen.queryByText('Frontend Engineer')).not.toBeInTheDocument();
    expect(screen.queryByText('Backend Engineer')).not.toBeInTheDocument();
  });
});
