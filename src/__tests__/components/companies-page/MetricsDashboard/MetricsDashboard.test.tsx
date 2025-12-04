import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MetricsDashboard } from '../../../../components/companies-page/MetricsDashboard/MetricsDashboard';
import { createTestStore } from '../../../../test/testUtils';
import type { Job } from '../../../../types';

// Mock Date.now() to have consistent time for tests
const MOCK_NOW = new Date('2025-11-23T12:00:00Z').getTime();
vi.spyOn(Date, 'now').mockReturnValue(MOCK_NOW);

describe('MetricsDashboard', () => {
  // Jobs with different timestamps for testing time windows
  const jobPosted6HoursAgo: Job = {
    id: '1',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Senior Frontend Engineer',
    department: 'Engineering',
    location: 'San Francisco, CA',
    employmentType: 'Full-time',
    createdAt: new Date(MOCK_NOW - 6 * 60 * 60 * 1000).toISOString(), // 6 hours ago
    url: 'https://example.com/job/1',
    classification: {
      isSoftwareAdjacent: true,
      category: 'frontend',
      confidence: 0.95,
      matchedKeywords: ['react', 'frontend'],
    },
    raw: {},
  };

  const jobPosted18HoursAgo: Job = {
    id: '2',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Backend Engineer',
    department: 'Engineering',
    location: 'Remote',
    employmentType: 'Full-time',
    createdAt: new Date(MOCK_NOW - 18 * 60 * 60 * 1000).toISOString(), // 18 hours ago
    url: 'https://example.com/job/2',
    classification: {
      isSoftwareAdjacent: true,
      category: 'backend',
      confidence: 0.9,
      matchedKeywords: ['node', 'backend'],
    },
    raw: {},
  };

  const jobPosted30HoursAgo: Job = {
    id: '3',
    source: 'greenhouse',
    company: 'spacex',
    title: 'DevOps Engineer',
    department: 'Engineering',
    location: 'Austin, TX',
    employmentType: 'Full-time',
    createdAt: new Date(MOCK_NOW - 30 * 60 * 60 * 1000).toISOString(), // 30 hours ago (outside 24h window)
    url: 'https://example.com/job/3',
    classification: {
      isSoftwareAdjacent: true,
      category: 'devops',
      confidence: 0.95,
      matchedKeywords: ['kubernetes', 'devops'],
    },
    raw: {},
  };

  const jobPosted2DaysAgo: Job = {
    id: '4',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Platform Engineer',
    department: 'Engineering',
    location: 'Seattle, WA',
    employmentType: 'Full-time',
    createdAt: new Date(MOCK_NOW - 2 * 24 * 60 * 60 * 1000).toISOString(), // 2 days ago (within 3 days)
    url: 'https://example.com/job/4',
    classification: {
      isSoftwareAdjacent: true,
      category: 'platform',
      confidence: 0.9,
      matchedKeywords: ['infrastructure', 'platform'],
    },
    raw: {},
  };

  const jobPosted4DaysAgo: Job = {
    id: '5',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Security Engineer',
    department: 'Security',
    location: 'Remote',
    employmentType: 'Full-time',
    createdAt: new Date(MOCK_NOW - 4 * 24 * 60 * 60 * 1000).toISOString(), // 4 days ago (outside 3 days)
    url: 'https://example.com/job/5',
    classification: {
      isSoftwareAdjacent: true,
      category: 'security',
      confidence: 0.95,
      matchedKeywords: ['security', 'cybersecurity'],
    },
    raw: {},
  };

  const createMockStore = (
    jobsOrConfig: Job[] | { jobs: Job[]; companyId?: string; metadata?: any } = []
  ) => {
    // Determine if argument is jobs array or config object
    const isConfig = !Array.isArray(jobsOrConfig) && typeof jobsOrConfig === 'object';
    const jobs = isConfig ? jobsOrConfig.jobs : jobsOrConfig;
    const companyId = isConfig && jobsOrConfig.companyId ? jobsOrConfig.companyId : 'spacex';

    // Calculate metadata from jobs if not explicitly provided
    const metadata =
      isConfig && jobsOrConfig.metadata
        ? jobsOrConfig.metadata
        : {
            totalCount: jobs.length,
            softwareCount: jobs.filter((j) => j.classification.isSoftwareAdjacent).length,
            newestJobDate: jobs.length > 0 ? '2025-11-23T10:00:00Z' : undefined,
            oldestJobDate: jobs.length > 0 ? '2025-11-20T08:00:00Z' : undefined,
            fetchedAt: new Date().toISOString(),
          };

    // Build cache key matching RTK Query format
    const cacheKey = `getJobsForCompany({"companyId":"${companyId}"})`;

    const store = createTestStore({
      app: {
        selectedCompanyId: companyId,
        selectedATS: 'greenhouse' as const,
        isInitialized: true,
      },
      graphFilters: {
        filters: {
          timeWindow: '7d' as const,
          softwareOnly: false,
        },
      },
      listFilters: {
        filters: {
          timeWindow: '7d' as const,
          softwareOnly: false,
        },
      },
      ui: {
        graphModal: {
          open: false,
        },
        globalLoading: false,
        notifications: [],
      },
      // Preload RTK Query cache
      jobsApi: {
        queries: {
          [cacheKey]: {
            status: 'fulfilled',
            endpointName: 'getJobsForCompany',
            requestId: 'test-request',
            data: {
              jobs,
              metadata,
            },
            startedTimeStamp: Date.now(),
            fulfilledTimeStamp: Date.now(),
          },
        },
        mutations: {},
        provided: {},
        subscriptions: {},
        config: {
          online: true,
          focused: true,
          middlewareRegistered: true,
          refetchOnFocus: false,
          refetchOnReconnect: false,
          refetchOnMountOrArgChange: false,
          keepUnusedDataFor: 60,
          reducerPath: 'jobsApi',
        },
      },
    });

    return store;
  };

  beforeEach(() => {
    // Reset any mocks if needed
  });

  it('renders all four metric sections', () => {
    const store = createMockStore([
      jobPosted6HoursAgo,
      jobPosted18HoursAgo,
      jobPosted30HoursAgo,
      jobPosted2DaysAgo,
      jobPosted4DaysAgo,
    ]);
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    expect(screen.getByText('Total Jobs')).toBeInTheDocument();
    expect(screen.getByText('Past 3 Days')).toBeInTheDocument();
    expect(screen.getByText('Past 24 Hours')).toBeInTheDocument();
    expect(screen.getByText('Past 12 Hours')).toBeInTheDocument();
  });

  it('displays correct total jobs count from metadata', () => {
    const store = createMockStore([
      jobPosted6HoursAgo,
      jobPosted18HoursAgo,
      jobPosted30HoursAgo,
      jobPosted2DaysAgo,
      jobPosted4DaysAgo,
    ]);
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('displays zero when no metadata available', () => {
    const store = createMockStore([]);
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Both Total Jobs and Filtered Jobs should show 0
    const zeros = screen.getAllByText('0');
    expect(zeros.length).toBeGreaterThanOrEqual(2);
  });

  it('displays correct count for jobs posted in past 3 days', () => {
    const store = createMockStore([
      jobPosted6HoursAgo,
      jobPosted18HoursAgo,
      jobPosted30HoursAgo,
      jobPosted2DaysAgo,
      jobPosted4DaysAgo,
    ]);
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Should show 4 jobs (6h, 18h, 30h, and 2 days ago - all within 3 days)
    expect(screen.getByText('4')).toBeInTheDocument();
  });

  it('displays correct count for jobs posted in past 24 hours', () => {
    const store = createMockStore([
      jobPosted6HoursAgo,
      jobPosted18HoursAgo,
      jobPosted30HoursAgo,
      jobPosted2DaysAgo,
      jobPosted4DaysAgo,
    ]);
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Should show 2 jobs (6 hours and 18 hours ago, both within 24 hours)
    const counts = screen.getAllByText('2');
    expect(counts.length).toBeGreaterThan(0);
  });

  it('displays correct count for jobs posted in past 12 hours', () => {
    const store = createMockStore([
      jobPosted6HoursAgo,
      jobPosted18HoursAgo,
      jobPosted30HoursAgo,
      jobPosted2DaysAgo,
      jobPosted4DaysAgo,
    ]);
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Should show 1 job (only the one from 6 hours ago is within 12 hours)
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('displays zero when no jobs in time window', () => {
    const store = createMockStore([jobPosted4DaysAgo]); // Only job outside 3-day window
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Should show 0 for all three time windows (3 days, 24h, 12h)
    const zeros = screen.getAllByText('0');
    expect(zeros.length).toBeGreaterThanOrEqual(3);
  });

  it('renders link cards for job postings and LinkedIn', () => {
    const store = createMockStore([
      jobPosted6HoursAgo,
      jobPosted18HoursAgo,
      jobPosted30HoursAgo,
      jobPosted2DaysAgo,
      jobPosted4DaysAgo,
    ]);
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    expect(screen.getByText('Official Job Postings')).toBeInTheDocument();
    expect(screen.getByText('Find Recruiters')).toBeInTheDocument();
  });

  it('displays job postings URL when configured', () => {
    const store = createMockStore();
    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    const link = screen.getByText('View All Openings');
    expect(link).toBeInTheDocument();
    expect(link.closest('a')).toHaveAttribute('href', 'https://boards.greenhouse.io/spacex');
    expect(link.closest('a')).toHaveAttribute('target', '_blank');
    expect(link.closest('a')).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('displays LinkedIn URL when configured', () => {
    const store = createMockStore({
      jobs: [{ ...jobPosted6HoursAgo, company: 'palantir' }],
      companyId: 'palantir',
      metadata: {
        totalCount: 5,
        softwareCount: 4,
        newestJobDate: '2025-11-23T10:00:00Z',
        fetchedAt: new Date().toISOString(),
      },
    });

    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Palantir has both URLs configured, should show LinkedIn Search link
    const linkedInLink = screen.getByText('LinkedIn Search');
    expect(linkedInLink).toBeInTheDocument();
    expect(linkedInLink.closest('a')).toHaveAttribute(
      'href',
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2220708%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=%40ld&sortBy=%22date_posted%22'
    );
    expect(linkedInLink.closest('a')).toHaveAttribute('target', '_blank');
    expect(linkedInLink.closest('a')).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('displays placeholder text when URLs are not configured', () => {
    const store = createMockStore({
      jobs: [],
      companyId: 'nonexistent-company',
      metadata: {
        totalCount: 0,
        softwareCount: 0,
        fetchedAt: new Date().toISOString(),
      },
    });

    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Should show "URL not configured" for both job postings and LinkedIn recruiter
    const notConfiguredTexts = screen.getAllByText('URL not configured');
    expect(notConfiguredTexts.length).toBe(2);
  });

  it('does not render metric icons', () => {
    const store = createMockStore();
    const { container } = render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Should have no icons - no SVG elements
    const svgIcons = container.querySelectorAll('svg');
    expect(svgIcons.length).toBe(0);
  });

  it('renders single Paper card container', () => {
    const store = createMockStore();
    const { container } = render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Check for single Paper container
    const paperElements = container.querySelectorAll('.MuiPaper-root');
    expect(paperElements.length).toBe(1);

    // Check for Stack containers inside
    const stackContainers = container.querySelectorAll('.MuiStack-root');
    expect(stackContainers.length).toBeGreaterThan(0);
  });

  it('displays correct company name in context', () => {
    const store = createMockStore({
      jobs: [{ ...jobPosted6HoursAgo, company: 'nominal' }],
      companyId: 'nominal',
      metadata: {
        totalCount: 15,
        softwareCount: 12,
        newestJobDate: '2025-11-23T09:00:00Z',
        fetchedAt: new Date().toISOString(),
      },
    });

    render(
      <Provider store={store}>
        <MetricsDashboard />
      </Provider>
    );

    // Should display total jobs for Nominal
    expect(screen.getByText('15')).toBeInTheDocument();
  });
});
