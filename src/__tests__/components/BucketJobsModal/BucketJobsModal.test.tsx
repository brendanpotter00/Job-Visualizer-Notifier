import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import userEvent from '@testing-library/user-event';
import { BucketJobsModal } from '../../../components/BucketJobsModal/BucketJobsModal';
import jobsReducer from '../../../features/jobs/jobsSlice';
import uiReducer from '../../../features/ui/uiSlice';
import appReducer from '../../../features/app/appSlice';
import filtersReducer from '../../../features/filters/filtersSlice';
import type { Job } from '../../../types';

const mockJobs: Job[] = [
  {
    id: '1',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Frontend Engineer',
    createdAt: '2025-11-21T10:00:00Z',
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
    source: 'greenhouse',
    company: 'spacex',
    title: 'Backend Engineer',
    createdAt: '2025-11-21T10:15:00Z',
    url: 'https://example.com/job/2',
    classification: {
      isSoftwareAdjacent: true,
      category: 'backend',
      confidence: 0.85,
      matchedKeywords: ['node'],
    },
    raw: {},
  },
  {
    id: '3',
    source: 'greenhouse',
    company: 'spacex',
    title: 'DevOps Engineer',
    createdAt: '2025-11-21T11:00:00Z',
    url: 'https://example.com/job/3',
    classification: {
      isSoftwareAdjacent: true,
      category: 'devops',
      confidence: 0.88,
      matchedKeywords: ['kubernetes'],
    },
    raw: {},
  },
];

describe('BucketJobsModal', () => {
  const createTestStore = (modalState: any) =>
    configureStore({
      reducer: {
        app: appReducer,
        jobs: jobsReducer,
        ui: uiReducer,
        filters: filtersReducer,
      },
      preloadedState: {
        app: {
          selectedCompanyId: 'spacex',
          selectedView: 'greenhouse' as const,
          isInitialized: true,
        },
        jobs: {
          byCompany: {
            spacex: {
              items: mockJobs,
              isLoading: false,
              error: undefined,
              metadata: {
                totalCount: mockJobs.length,
                softwareCount: mockJobs.length,
              },
            },
          },
        },
        ui: {
          graphModal: modalState,
          globalLoading: false,
          notifications: [],
        },
      },
    });

  it('does not render when modal is closed', () => {
    const store = createTestStore({ open: false });
    render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders modal when open with bucket data', () => {
    const store = createTestStore({
      open: true,
      bucketStart: '2025-11-21T10:00:00Z',
      bucketEnd: '2025-11-21T10:30:00Z',
      filteredJobIds: ['1', '2'],
    });
    render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('displays bucket time range in title', () => {
    const store = createTestStore({
      open: true,
      bucketStart: '2025-11-21T10:00:00Z',
      bucketEnd: '2025-11-21T10:30:00Z',
      filteredJobIds: ['1', '2'],
    });
    render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );
    expect(screen.getByText('Jobs Posted')).toBeInTheDocument();
    // Time will be converted to local timezone, just check that it exists
    expect(screen.getByText(/Nov 21, 2025/)).toBeInTheDocument();
  });

  it('displays only jobs in the filtered job IDs', () => {
    const store = createTestStore({
      open: true,
      bucketStart: '2025-11-21T10:00:00Z',
      bucketEnd: '2025-11-21T10:30:00Z',
      filteredJobIds: ['1', '2'],
    });
    render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );
    expect(screen.getByText('Frontend Engineer')).toBeInTheDocument();
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
    expect(screen.queryByText('DevOps Engineer')).not.toBeInTheDocument();
  });

  it('displays job count', () => {
    const store = createTestStore({
      open: true,
      bucketStart: '2025-11-21T10:00:00Z',
      bucketEnd: '2025-11-21T10:30:00Z',
      filteredJobIds: ['1', '2'],
    });
    render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );
    expect(screen.getByText('2 jobs found')).toBeInTheDocument();
  });

  it('closes modal when close button is clicked', async () => {
    const store = createTestStore({
      open: true,
      bucketStart: '2025-11-21T10:00:00Z',
      bucketEnd: '2025-11-21T10:30:00Z',
      filteredJobIds: ['1', '2'],
    });
    const user = userEvent.setup();

    render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );

    const closeButton = screen.getByLabelText('close');
    await user.click(closeButton);

    // Check that closeGraphModal action was dispatched
    const state = store.getState();
    expect(state.ui.graphModal.open).toBe(false);
  });

  it('handles empty bucket (no jobs)', () => {
    const store = createTestStore({
      open: true,
      bucketStart: '2025-11-21T10:00:00Z',
      bucketEnd: '2025-11-21T10:30:00Z',
      filteredJobIds: [],
    });
    render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );
    expect(screen.getByText(/no jobs found matching your filters/i)).toBeInTheDocument();
  });

  it('handles missing bucket times gracefully', () => {
    const store = createTestStore({
      open: true,
      bucketStart: undefined,
      bucketEnd: undefined,
      filteredJobIds: ['1', '2'],
    });
    const { container } = render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );
    expect(container.querySelector('[role="dialog"]')).not.toBeInTheDocument();
  });

  it('displays all jobs when filteredJobIds includes all IDs', () => {
    const store = createTestStore({
      open: true,
      bucketStart: '2025-11-21T10:00:00Z',
      bucketEnd: '2025-11-21T12:00:00Z',
      filteredJobIds: ['1', '2', '3'],
    });
    render(
      <Provider store={store}>
        <BucketJobsModal />
      </Provider>
    );
    expect(screen.getByText('Frontend Engineer')).toBeInTheDocument();
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
    expect(screen.getByText('DevOps Engineer')).toBeInTheDocument();
    expect(screen.getByText('3 jobs found')).toBeInTheDocument();
  });
});
