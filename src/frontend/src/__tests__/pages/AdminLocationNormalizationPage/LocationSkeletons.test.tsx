import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  AliasForwardTableSkeleton,
  AliasOriginalsSkeleton,
  AliasReverseTableSkeleton,
  HealthOverviewSkeleton,
  IntegrityTableSkeleton,
  LocationPageBodySkeleton,
  ProblemJobsTableSkeleton,
} from '../../../pages/AdminLocationNormalizationPage/components/LocationSkeletons';

const headerLabels = () => screen.getAllByRole('columnheader').map((h) => h.textContent);

describe('LocationSkeletons', () => {
  it('HealthOverviewSkeleton: four stat tiles over two chip rows', () => {
    const { container } = render(<HealthOverviewSkeleton />);
    expect(container.querySelectorAll('.MuiPaper-outlined')).toHaveLength(4);
  });

  it('IntegrityTableSkeleton mirrors the invariants table header', () => {
    render(<IntegrityTableSkeleton />);
    expect(headerLabels()).toEqual(['ID', 'Invariant', 'Count', 'Status']);
  });

  it('AliasForwardTableSkeleton mirrors the forward table header, with pagination', () => {
    render(<AliasForwardTableSkeleton />);
    expect(headerLabels()).toEqual(['Raw text', 'Source', 'Confidence', 'Canonical', 'Actions']);
    expect(screen.getByTestId('table-skeleton-pagination')).toBeInTheDocument();
  });

  it('AliasReverseTableSkeleton mirrors the reverse table header, without pagination', () => {
    render(<AliasReverseTableSkeleton />);
    expect(headerLabels()).toEqual(['Canonical', 'Kind', 'Raw texts']);
    expect(screen.queryByTestId('table-skeleton-pagination')).not.toBeInTheDocument();
  });

  it('ProblemJobsTableSkeleton mirrors the problem-jobs header', () => {
    render(<ProblemJobsTableSkeleton />);
    expect(headerLabels()).toEqual(['ID', 'Title', 'Company', 'Location', 'Status', 'Action']);
  });

  it('AliasOriginalsSkeleton renders a subtitle and a few string lines', () => {
    const { container } = render(<AliasOriginalsSkeleton />);
    expect(container.querySelectorAll('.MuiSkeleton-root')).toHaveLength(4);
  });

  it('LocationPageBodySkeleton holds every section in page order, with no headings', () => {
    render(<LocationPageBodySkeleton />);
    const titles = ['Health overview', 'Integrity invariants', 'Alias cache browser', 'Problem jobs'];
    for (const title of titles) expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
