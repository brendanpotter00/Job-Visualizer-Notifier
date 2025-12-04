import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobCard } from '../../../../components/companies-page/JobList/JobCard';
import type { Job } from '../../../../types';

describe('JobCard', () => {
  const mockJob: Job = {
    id: '1',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Senior Frontend Engineer',
    department: 'Engineering',
    location: 'San Francisco, CA',
    isRemote: true,
    employmentType: 'Full-time',
    createdAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
    url: 'https://example.com/job/1',
    tags: ['React', 'TypeScript', 'GraphQL', 'Testing', 'CI/CD', 'Extra Tag'],
    classification: {
      isSoftwareAdjacent: true,
      category: 'frontend',
      confidence: 0.95,
      matchedKeywords: ['react', 'typescript', 'frontend'],
    },
    raw: {},
  };

  it('renders job title as a link', () => {
    render(<JobCard job={mockJob} />);
    const link = screen.getByRole('link', { name: 'Senior Frontend Engineer' });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', 'https://example.com/job/1');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('displays relative time posted', () => {
    render(<JobCard job={mockJob} />);
    expect(screen.getByText(/2 hours ago/i)).toBeInTheDocument();
  });

  it('displays department chip', () => {
    render(<JobCard job={mockJob} />);
    expect(screen.getByText('Engineering')).toBeInTheDocument();
  });

  it('displays location chip', () => {
    render(<JobCard job={mockJob} />);
    expect(screen.getByText('San Francisco, CA')).toBeInTheDocument();
  });

  it('displays remote chip when job is remote', () => {
    render(<JobCard job={mockJob} />);
    expect(screen.getByText('Remote')).toBeInTheDocument();
  });

  it('does not display remote chip when job is not remote', () => {
    const nonRemoteJob = { ...mockJob, isRemote: false };
    render(<JobCard job={nonRemoteJob} />);
    expect(screen.queryByText('Remote')).not.toBeInTheDocument();
  });

  it('displays employment type chip', () => {
    render(<JobCard job={mockJob} />);
    expect(screen.getByText('Full-time')).toBeInTheDocument();
  });

  it('displays role category chip for software roles', () => {
    render(<JobCard job={mockJob} />);
    expect(screen.getByText('frontend')).toBeInTheDocument();
  });

  it('does not display role category for non-software roles', () => {
    const nonSoftwareJob: Job = {
      ...mockJob,
      classification: {
        isSoftwareAdjacent: false,
        category: 'nonTech',
        confidence: 0.6,
        matchedKeywords: [],
      },
    };
    render(<JobCard job={nonSoftwareJob} />);
    expect(screen.queryByText('nonTech')).not.toBeInTheDocument();
  });

  it('displays first 5 tags', () => {
    render(<JobCard job={mockJob} />);
    expect(screen.getByText('React')).toBeInTheDocument();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();
    expect(screen.getByText('GraphQL')).toBeInTheDocument();
    expect(screen.getByText('Testing')).toBeInTheDocument();
    expect(screen.getByText('CI/CD')).toBeInTheDocument();
    expect(screen.queryByText('Extra Tag')).not.toBeInTheDocument();
  });

  it('handles job with no tags', () => {
    const jobWithoutTags = { ...mockJob, tags: undefined };
    render(<JobCard job={jobWithoutTags} />);
    // Should render without errors
    expect(screen.getByText('Senior Frontend Engineer')).toBeInTheDocument();
  });

  it('filters out null values from tags', () => {
    const jobWithNullTags = {
      ...mockJob,
      tags: ['React', null, 'TypeScript', null, 'GraphQL'] as any,
    };
    render(<JobCard job={jobWithNullTags} />);
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
    render(<JobCard job={jobWithEmptyTags} />);
    expect(screen.getByText('React')).toBeInTheDocument();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();
    expect(screen.getByText('GraphQL')).toBeInTheDocument();
    // Empty strings should be filtered out
  });

  it('handles job with no optional fields', () => {
    const minimalJob: Job = {
      id: '2',
      source: 'lever',
      company: 'nominal',
      title: 'Engineer',
      createdAt: new Date().toISOString(),
      url: 'https://example.com/job/2',
      classification: {
        isSoftwareAdjacent: false,
        category: 'nonTech',
        confidence: 0.5,
        matchedKeywords: [],
      },
      raw: {},
    };
    render(<JobCard job={minimalJob} />);
    expect(screen.getByText('Engineer')).toBeInTheDocument();
    expect(screen.queryByText('Engineering')).not.toBeInTheDocument();
    expect(screen.queryByText('Remote')).not.toBeInTheDocument();
  });
});
