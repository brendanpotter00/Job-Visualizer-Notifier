import { describe, it, expect, beforeEach, vi } from 'vitest';
import { updateCompanyProgress } from '../../../features/jobs/progressHelpers';
import type { FetchProgress } from '../../../types';

describe('updateCompanyProgress', () => {
  let mockProgress: FetchProgress;
  let mockDateNow: Date;

  beforeEach(() => {
    // Mock Date.now() for consistent timestamps
    mockDateNow = new Date('2025-01-15T10:30:00Z');
    vi.setSystemTime(mockDateNow);

    mockProgress = {
      completed: 0,
      total: 3,
      companies: [
        { companyId: 'acme', status: 'pending' },
        { companyId: 'techcorp', status: 'pending' },
        { companyId: 'startup', status: 'pending' },
      ],
    };
  });

  it('should update company status to loading', () => {
    updateCompanyProgress(mockProgress, 'acme', { status: 'loading' });

    const company = mockProgress.companies.find((c) => c.companyId === 'acme');
    expect(company?.status).toBe('loading');
    expect(company?.completedAt).toBeUndefined();
    expect(mockProgress.completed).toBe(0); // Not incremented for loading
  });

  it('should update company status to success with job count', () => {
    updateCompanyProgress(mockProgress, 'acme', {
      status: 'success',
      jobCount: 42,
    });

    const company = mockProgress.companies.find((c) => c.companyId === 'acme');
    expect(company?.status).toBe('success');
    expect(company?.jobCount).toBe(42);
    expect(company?.completedAt).toBe('2025-01-15T10:30:00.000Z');
    expect(mockProgress.completed).toBe(1);
  });

  it('should update company status to error with error message', () => {
    updateCompanyProgress(mockProgress, 'acme', {
      status: 'error',
      error: 'Network timeout',
    });

    const company = mockProgress.companies.find((c) => c.companyId === 'acme');
    expect(company?.status).toBe('error');
    expect(company?.error).toBe('Network timeout');
    expect(company?.completedAt).toBe('2025-01-15T10:30:00.000Z');
    expect(mockProgress.completed).toBe(1);
  });

  it('should increment completed count for success state', () => {
    updateCompanyProgress(mockProgress, 'acme', { status: 'success', jobCount: 10 });
    expect(mockProgress.completed).toBe(1);

    updateCompanyProgress(mockProgress, 'techcorp', { status: 'success', jobCount: 20 });
    expect(mockProgress.completed).toBe(2);
  });

  it('should increment completed count for error state', () => {
    updateCompanyProgress(mockProgress, 'acme', { status: 'error', error: 'Failed' });
    expect(mockProgress.completed).toBe(1);

    updateCompanyProgress(mockProgress, 'techcorp', { status: 'error', error: 'Failed' });
    expect(mockProgress.completed).toBe(2);
  });

  it('should not increment completed count for loading state', () => {
    updateCompanyProgress(mockProgress, 'acme', { status: 'loading' });
    expect(mockProgress.completed).toBe(0);

    updateCompanyProgress(mockProgress, 'techcorp', { status: 'loading' });
    expect(mockProgress.completed).toBe(0);
  });

  it('should handle company not found gracefully', () => {
    updateCompanyProgress(mockProgress, 'nonexistent', { status: 'success' });

    // Should not throw and should not increment completed count
    expect(mockProgress.completed).toBe(0);
  });

  it('should handle transition from loading to success', () => {
    // First mark as loading
    updateCompanyProgress(mockProgress, 'acme', { status: 'loading' });
    expect(mockProgress.completed).toBe(0);

    // Then mark as success
    updateCompanyProgress(mockProgress, 'acme', { status: 'success', jobCount: 15 });
    expect(mockProgress.completed).toBe(1);

    const company = mockProgress.companies.find((c) => c.companyId === 'acme');
    expect(company?.status).toBe('success');
    expect(company?.jobCount).toBe(15);
  });

  it('should handle transition from loading to error', () => {
    // First mark as loading
    updateCompanyProgress(mockProgress, 'acme', { status: 'loading' });
    expect(mockProgress.completed).toBe(0);

    // Then mark as error
    updateCompanyProgress(mockProgress, 'acme', { status: 'error', error: 'Timeout' });
    expect(mockProgress.completed).toBe(1);

    const company = mockProgress.companies.find((c) => c.companyId === 'acme');
    expect(company?.status).toBe('error');
    expect(company?.error).toBe('Timeout');
  });

  it('should set completedAt timestamp for terminal states', () => {
    updateCompanyProgress(mockProgress, 'acme', { status: 'success', jobCount: 5 });

    const company = mockProgress.companies.find((c) => c.companyId === 'acme');
    expect(company?.completedAt).toBeDefined();
    expect(company?.completedAt).toBe('2025-01-15T10:30:00.000Z');
  });

  it('should handle optional error field', () => {
    updateCompanyProgress(mockProgress, 'acme', { status: 'success' });

    const company = mockProgress.companies.find((c) => c.companyId === 'acme');
    expect(company?.error).toBeUndefined();
  });

  it('should handle optional jobCount field', () => {
    updateCompanyProgress(mockProgress, 'acme', { status: 'error', error: 'Failed' });

    const company = mockProgress.companies.find((c) => c.companyId === 'acme');
    expect(company?.jobCount).toBeUndefined();
  });

  it('should handle multiple companies progressing', () => {
    updateCompanyProgress(mockProgress, 'acme', { status: 'loading' });
    updateCompanyProgress(mockProgress, 'techcorp', { status: 'loading' });
    expect(mockProgress.completed).toBe(0);

    updateCompanyProgress(mockProgress, 'acme', { status: 'success', jobCount: 10 });
    expect(mockProgress.completed).toBe(1);

    updateCompanyProgress(mockProgress, 'techcorp', { status: 'error', error: 'Failed' });
    expect(mockProgress.completed).toBe(2);

    updateCompanyProgress(mockProgress, 'startup', { status: 'success', jobCount: 30 });
    expect(mockProgress.completed).toBe(3);
  });
});
