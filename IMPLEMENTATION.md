# Job Posting Analytics SPA - Implementation Guide

> **Document Version**: 1.0
> **Last Updated**: 2025-11-20
> **Target Agent**: Claude Code
> **Estimated Complexity**: High (14 implementation steps)

---

## Table of Contents

1. [Implementation Overview](#implementation-overview)
2. [Project Architecture](#project-architecture)
3. [Technology Stack](#technology-stack)
4. [Data Models & Type System](#data-models--type-system)
5. [State Management Architecture](#state-management-architecture)
6. [API Integration Strategy](#api-integration-strategy)
7. [Component Architecture](#component-architecture)
8. [Testing Strategy](#testing-strategy)
9. [Implementation Sequence](#implementation-sequence)
10. [Validation Checklist](#validation-checklist)

---

## Implementation Overview

### Purpose

Build a mobile-responsive, single-page TypeScript + React application that visualizes job posting activity over time for multiple companies using external ATS (Applicant Tracking System) job board APIs.

### Core Features

- **Multi-ATS Support**: Greenhouse (SpaceX) and Lever (Nominal)
- **Time-Series Visualization**: Interactive line graph showing job posting timeline
- **Dual Filtering System**: Independent filters for graph and job list
- **Software Role Focus**: Intelligent filtering for software engineering roles
- **Mobile-First Design**: Fully responsive across all device sizes
- **Type-Safe Architecture**: Strict TypeScript throughout

### Key Constraints

- **No Backend**: Client-side only application
- **No Authentication**: Public job board data only
- **No RTK Query Initially**: Manual fetch with migration path
- **Strict TypeScript**: No `any` types unless unavoidable
- **Test Coverage Required**: Unit and component tests mandatory

---

## Project Architecture

### Directory Structure

```
src/
├── app/                          # Application core
│   ├── store.ts                  # Redux store configuration
│   ├── rootReducer.ts            # Combined reducers
│   └── App.tsx                   # Root application component
│
├── features/                     # Feature modules (Redux slices + components)
│   ├── jobs/
│   │   ├── jobsSlice.ts         # Jobs state management
│   │   ├── jobsSelectors.ts     # Memoized selectors
│   │   ├── jobsThunks.ts        # Async actions
│   │   └── types.ts             # Job-related types
│   │
│   ├── filters/
│   │   ├── filtersSlice.ts      # Filter state management
│   │   ├── filtersSelectors.ts  # Filter selectors
│   │   └── types.ts             # Filter-related types
│   │
│   └── ui/
│       ├── uiSlice.ts           # UI state (modals, loading)
│       └── types.ts             # UI state types
│
├── api/                          # External API integrations
│   ├── greenhouseClient.ts      # Greenhouse API client
│   ├── leverClient.ts           # Lever API client
│   ├── types.ts                 # API response types
│   └── transformers/            # Raw API → Internal model
│       ├── greenhouseTransformer.ts
│       └── leverTransformer.ts
│
├── utils/                        # Shared utilities
│   ├── roleClassification.ts   # Software role detection
│   ├── timeBucketing.ts        # Graph time bucket logic
│   ├── dateUtils.ts            # Date/time helpers
│   └── constants.ts            # App-wide constants
│
├── components/                   # Shared/reusable components
│   ├── JobPostingsChart/       # Graph component
│   │   ├── JobPostingsChart.tsx
│   │   ├── ChartTooltip.tsx
│   │   └── types.ts
│   │
│   ├── JobList/                # Job list component
│   │   ├── JobList.tsx
│   │   ├── JobCard.tsx
│   │   └── types.ts
│   │
│   ├── BucketJobsModal/        # Graph point detail modal
│   │   └── BucketJobsModal.tsx
│   │
│   └── filters/                # Filter UI components
│       ├── GraphFilters.tsx
│       ├── ListFilters.tsx
│       └── FilterControls/
│           ├── TimeWindowSelect.tsx
│           ├── CompanySelect.tsx
│           └── SearchInput.tsx
│
├── hooks/                        # Custom React hooks
│   ├── useJobs.ts              # Job data access
│   ├── useFilters.ts           # Filter state access
│   └── useFilteredJobs.ts      # Combined filtering logic
│
├── config/                       # Configuration
│   ├── companies.ts            # Company definitions
│   └── theme.ts                # MUI theme configuration
│
└── __tests__/                    # Test files (mirrors src structure)
    ├── utils/
    ├── api/
    └── components/
```

### Architecture Principles

1. **Feature-Based Organization**: Related code grouped by feature (jobs, filters, ui)
2. **Separation of Concerns**: API, state, UI clearly separated
3. **Type Safety**: Strict TypeScript with explicit interfaces
4. **Testability**: Each module designed for isolated testing
5. **Future-Proof**: Structure supports RTK Query migration

---

## Technology Stack

### Core Framework

- **Language**: TypeScript 5.x (strict mode)
- **Framework**: React 18.x
- **Build Tool**: Vite 5.x
- **Package Manager**: npm or pnpm (recommended)

### State Management

- **Redux**: @reduxjs/toolkit 2.x
- **Pattern**: Redux Toolkit slices with createAsyncThunk
- **Selectors**: Reselect (included in RTK) for memoization

### UI & Visualization

- **Component Library**: Material UI (MUI) 5.x
- **Charting**: Recharts 2.x
- **Styling**: Emotion (MUI dependency)
- **Icons**: @mui/icons-material

### Testing

- **Test Runner**: Jest 29.x
- **Component Testing**: React Testing Library
- **API Mocking**: MSW (Mock Service Worker) 2.x
- **Coverage**: Jest built-in coverage

### Development Tools

- **Linting**: ESLint + TypeScript ESLint
- **Formatting**: Prettier
- **Type Checking**: tsc --noEmit in CI

---

## Data Models & Type System

### Core Domain Types

#### 1. Internal Job Model

The normalized job representation used throughout the application.

```typescript
/**
 * Normalized job posting model.
 * All ATS-specific data is transformed into this structure.
 */
interface Job {
  /** Unique identifier (from ATS) */
  id: string;

  /** ATS source system */
  source: 'greenhouse' | 'lever';

  /** Company identifier (e.g., 'spacex', 'nominal') */
  company: string;

  /** Job title */
  title: string;

  /** Department or division */
  department?: string;

  /** Team within department (if available) */
  team?: string;

  /** Location (city, state, country) */
  location?: string;

  /** Remote work indicator */
  isRemote?: boolean;

  /** Employment type (full-time, contract, intern, etc.) */
  employmentType?: string;

  /** Job creation/posting timestamp (ISO 8601) */
  createdAt: string;

  /** Direct link to job posting */
  url: string;

  /** Tags, keywords, or job families from ATS */
  tags?: string[];

  /** Role classification (computed) */
  classification: RoleClassification;

  /** Original ATS response for debugging */
  raw: unknown;
}
```

#### 2. Role Classification

Software role detection and categorization.

```typescript
/**
 * Software role categories for filtering and analytics.
 */
type SoftwareRoleCategory =
  | 'frontend'
  | 'backend'
  | 'fullstack'
  | 'mobile'
  | 'data'
  | 'ml'
  | 'devops'
  | 'platform'
  | 'qa'
  | 'security'
  | 'graphics'
  | 'embedded'
  | 'otherTech'
  | 'nonTech';

/**
 * Result of role classification analysis.
 */
interface RoleClassification {
  /** Is this a software/tech role? */
  isSoftwareAdjacent: boolean;

  /** Specific category */
  category: SoftwareRoleCategory;

  /** Confidence score (0-1) */
  confidence: number;

  /** Keywords that triggered classification */
  matchedKeywords: string[];
}

/**
 * Configuration for role classification.
 */
interface RoleClassificationConfig {
  /** Keywords by category */
  categoryKeywords: Record<SoftwareRoleCategory, string[]>;

  /** Department name patterns */
  techDepartments: RegExp[];

  /** Title exclusion patterns (non-tech roles) */
  exclusionPatterns: RegExp[];
}
```

#### 3. Time Windows & Bucketing

```typescript
/**
 * Supported time window options.
 */
type TimeWindow =
  | '30m'
  | '1h'
  | '3h'
  | '6h'
  | '12h'
  | '24h'
  | '3d'
  | '7d';

/**
 * Time window display configuration.
 */
interface TimeWindowConfig {
  value: TimeWindow;
  label: string;
  durationMs: number;
  bucketSizeMs: number; // Granularity for graphing
}

/**
 * Time bucket for graph data.
 */
interface TimeBucket {
  /** Bucket start time (ISO 8601) */
  bucketStart: string;

  /** Bucket end time (ISO 8601) */
  bucketEnd: string;

  /** Number of jobs in bucket */
  count: number;

  /** Job IDs in this bucket */
  jobIds: string[];
}
```

#### 4. Company Configuration

```typescript
/**
 * ATS provider type.
 */
type ATSProvider = 'greenhouse' | 'lever';

/**
 * Company configuration for multi-ATS support.
 */
interface Company {
  /** Unique company identifier */
  id: string;

  /** Display name */
  name: string;

  /** ATS provider */
  ats: ATSProvider;

  /** ATS-specific configuration */
  config: GreenhouseConfig | LeverConfig;
}

interface GreenhouseConfig {
  type: 'greenhouse';
  /** Board token or identifier */
  boardToken: string;
  /** Optional custom API base URL */
  apiBaseUrl?: string;
}

interface LeverConfig {
  type: 'lever';
  /** Company identifier in Lever URL */
  companyId: string;
  /** Full jobs URL (e.g., 'https://jobs.lever.co/nominal') */
  jobsUrl: string;
}
```

#### 5. Filter Types

```typescript
/**
 * Graph filter state.
 */
interface GraphFilters {
  timeWindow: TimeWindow;
  location?: string;
  department?: string;
  employmentType?: string;
  roleCategory?: SoftwareRoleCategory | 'all';
  softwareOnly: boolean;
}

/**
 * List filter state (independent from graph).
 */
interface ListFilters {
  timeWindow: TimeWindow;
  searchQuery: string;
  location?: string;
  department?: string;
  employmentType?: string;
  roleCategory?: SoftwareRoleCategory | 'all';
  softwareOnly: boolean;
}
```

### ATS-Specific Response Types

#### Greenhouse API Response

```typescript
/**
 * Greenhouse job board API response.
 * @see https://developers.greenhouse.io/job-board.html
 */
interface GreenhouseJobResponse {
  id: number;
  title: string;
  absolute_url: string;
  location: {
    name: string;
  };
  departments: Array<{
    id: number;
    name: string;
  }>;
  offices: Array<{
    id: number;
    name: string;
    location: string;
  }>;
  updated_at: string; // ISO timestamp
  metadata?: Array<{
    id: number;
    name: string;
    value: string;
  }>;
}

interface GreenhouseAPIResponse {
  jobs: GreenhouseJobResponse[];
}
```

#### Lever API Response

```typescript
/**
 * Lever job posting API response.
 * @see https://github.com/lever/postings-api
 */
interface LeverJobResponse {
  id: string;
  text: string; // Job title
  hostedUrl: string;
  categories: {
    commitment?: string; // Full-time, Part-time, etc.
    department?: string;
    location?: string;
    team?: string;
  };
  createdAt: number; // Unix timestamp (milliseconds)
  tags?: string[];
  workplaceType?: 'remote' | 'onsite' | 'unspecified';
}
```

---

## State Management Architecture

### Redux Store Shape

```typescript
/**
 * Root Redux state.
 */
interface RootState {
  app: AppState;
  jobs: JobsState;
  filters: FiltersState;
  ui: UIState;
}

/**
 * Application-level state.
 */
interface AppState {
  /** Currently selected company */
  selectedCompanyId: string;

  /** Current view type (derived from company.ats) */
  selectedView: ATSProvider;

  /** App initialization status */
  isInitialized: boolean;
}

/**
 * Jobs state (normalized by company).
 */
interface JobsState {
  byCompany: {
    [companyId: string]: {
      /** Job data */
      items: Job[];

      /** Last fetch timestamp */
      lastFetchedAt?: string;

      /** Loading state */
      isLoading: boolean;

      /** Error message if fetch failed */
      error?: string;

      /** Fetch metadata */
      metadata: {
        totalCount: number;
        softwareCount: number;
        oldestJobDate?: string;
        newestJobDate?: string;
      };
    };
  };
}

/**
 * Filter state (graph and list are independent).
 */
interface FiltersState {
  graph: GraphFilters;
  list: ListFilters;
}

/**
 * UI state (modals, notifications, etc.).
 */
interface UIState {
  /** Graph bucket detail modal */
  graphModal: {
    open: boolean;
    bucketStart?: string;
    bucketEnd?: string;
    filteredJobIds?: string[];
  };

  /** Global loading overlay */
  globalLoading: boolean;

  /** Toast notifications */
  notifications: Array<{
    id: string;
    type: 'success' | 'error' | 'info' | 'warning';
    message: string;
  }>;
}
```

### Redux Slices

#### 1. App Slice

```typescript
// src/features/app/appSlice.ts

const appSlice = createSlice({
  name: 'app',
  initialState: {
    selectedCompanyId: 'spacex', // Default to SpaceX
    selectedView: 'greenhouse' as ATSProvider,
    isInitialized: false,
  },
  reducers: {
    setSelectedCompanyId(state, action: PayloadAction<string>) {
      state.selectedCompanyId = action.payload;
      // selectedView is derived in selector based on company config
    },
    setInitialized(state) {
      state.isInitialized = true;
    },
  },
});
```

#### 2. Jobs Slice

```typescript
// src/features/jobs/jobsSlice.ts

const jobsSlice = createSlice({
  name: 'jobs',
  initialState: {
    byCompany: {},
  } as JobsState,
  reducers: {
    // Sync reducers for manual updates
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadJobsForCompany.pending, (state, action) => {
        const { companyId } = action.meta.arg;
        if (!state.byCompany[companyId]) {
          state.byCompany[companyId] = {
            items: [],
            isLoading: true,
            error: undefined,
            metadata: { totalCount: 0, softwareCount: 0 },
          };
        } else {
          state.byCompany[companyId].isLoading = true;
          state.byCompany[companyId].error = undefined;
        }
      })
      .addCase(loadJobsForCompany.fulfilled, (state, action) => {
        const { companyId } = action.meta.arg;
        const { jobs, metadata } = action.payload;

        state.byCompany[companyId] = {
          items: jobs,
          isLoading: false,
          error: undefined,
          lastFetchedAt: new Date().toISOString(),
          metadata,
        };
      })
      .addCase(loadJobsForCompany.rejected, (state, action) => {
        const { companyId } = action.meta.arg;
        state.byCompany[companyId] = {
          ...state.byCompany[companyId],
          isLoading: false,
          error: action.error.message || 'Failed to load jobs',
        };
      });
  },
});
```

#### 3. Filters Slice

```typescript
// src/features/filters/filtersSlice.ts

const filtersSlice = createSlice({
  name: 'filters',
  initialState: {
    graph: {
      timeWindow: '24h',
      softwareOnly: true,
      roleCategory: 'all',
    },
    list: {
      timeWindow: '24h',
      searchQuery: '',
      softwareOnly: true,
      roleCategory: 'all',
    },
  } as FiltersState,
  reducers: {
    // Graph filters
    setGraphTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.graph.timeWindow = action.payload;
    },
    setGraphLocation(state, action: PayloadAction<string | undefined>) {
      state.graph.location = action.payload;
    },
    toggleGraphSoftwareOnly(state) {
      state.graph.softwareOnly = !state.graph.softwareOnly;
    },

    // List filters
    setListTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.list.timeWindow = action.payload;
    },
    setListSearchQuery(state, action: PayloadAction<string>) {
      state.list.searchQuery = action.payload;
    },
    toggleListSoftwareOnly(state) {
      state.list.softwareOnly = !state.list.softwareOnly;
    },

    // Reset filters
    resetGraphFilters(state) {
      state.graph = { ...initialState.graph };
    },
    resetListFilters(state) {
      state.list = { ...initialState.list };
    },
  },
});
```

### Selectors (Memoized)

```typescript
// src/features/jobs/jobsSelectors.ts

import { createSelector } from '@reduxjs/toolkit';

/** Select all jobs for current company */
export const selectCurrentCompanyJobs = createSelector(
  [(state: RootState) => state.app.selectedCompanyId,
   (state: RootState) => state.jobs.byCompany],
  (companyId, byCompany) => byCompany[companyId]?.items || []
);

/** Select jobs filtered by graph filters */
export const selectGraphFilteredJobs = createSelector(
  [selectCurrentCompanyJobs,
   (state: RootState) => state.filters.graph],
  (jobs, filters) => {
    return jobs.filter(job => {
      // Time window filter
      if (!isWithinTimeWindow(job.createdAt, filters.timeWindow)) {
        return false;
      }

      // Software-only filter
      if (filters.softwareOnly && !job.classification.isSoftwareAdjacent) {
        return false;
      }

      // Location filter
      if (filters.location && job.location !== filters.location) {
        return false;
      }

      // Role category filter
      if (filters.roleCategory && filters.roleCategory !== 'all') {
        if (job.classification.category !== filters.roleCategory) {
          return false;
        }
      }

      return true;
    });
  }
);

/** Select bucketed data for graph */
export const selectGraphBucketData = createSelector(
  [selectGraphFilteredJobs,
   (state: RootState) => state.filters.graph.timeWindow],
  (jobs, timeWindow) => {
    return bucketJobsByTime(jobs, timeWindow);
  }
);
```

---

## API Integration Strategy

### Design Principles

1. **ATS Abstraction**: Each ATS has dedicated client module
2. **Transformation Layer**: Raw API responses → normalized Job model
3. **Error Handling**: Consistent error types across all clients
4. **Rate Limiting**: Built-in retry logic with exponential backoff
5. **RTK Query Ready**: Architecture supports future migration

### API Client Structure

#### Base Client Interface

```typescript
// src/api/types.ts

/**
 * Standard API client interface.
 * All ATS clients implement this interface.
 */
interface JobAPIClient {
  /**
   * Fetch jobs for a company.
   * @param config - Company-specific configuration
   * @param options - Fetch options
   * @returns Normalized jobs array
   */
  fetchJobs(
    config: GreenhouseConfig | LeverConfig,
    options?: FetchJobsOptions
  ): Promise<FetchJobsResult>;
}

interface FetchJobsOptions {
  /** Filter to jobs created after this timestamp */
  since?: string;

  /** Maximum number of jobs to fetch */
  limit?: number;

  /** AbortSignal for request cancellation */
  signal?: AbortSignal;
}

interface FetchJobsResult {
  jobs: Job[];
  metadata: {
    totalCount: number;
    softwareCount: number;
    fetchedAt: string;
  };
}

/**
 * API error types.
 */
class APIError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public atsProvider?: ATSProvider,
    public retryable: boolean = false
  ) {
    super(message);
    this.name = 'APIError';
  }
}
```

#### Greenhouse Client

```typescript
// src/api/greenhouseClient.ts

/**
 * Greenhouse job board API client.
 */
export const greenhouseClient: JobAPIClient = {
  async fetchJobs(config, options = {}) {
    if (config.type !== 'greenhouse') {
      throw new Error('Invalid config type for Greenhouse client');
    }

    const baseUrl = config.apiBaseUrl || 'https://boards-api.greenhouse.io';
    const url = `${baseUrl}/v1/boards/${config.boardToken}/jobs`;

    try {
      const response = await fetch(url, {
        signal: options.signal,
        headers: {
          'Accept': 'application/json',
        },
      });

      if (!response.ok) {
        throw new APIError(
          `Greenhouse API error: ${response.statusText}`,
          response.status,
          'greenhouse',
          response.status >= 500 || response.status === 429
        );
      }

      const data: GreenhouseAPIResponse = await response.json();

      // Transform to internal model
      const jobs = data.jobs.map(transformGreenhouseJob);

      // Apply 'since' filter if provided
      const filteredJobs = options.since
        ? jobs.filter(job => new Date(job.createdAt) >= new Date(options.since!))
        : jobs;

      return {
        jobs: filteredJobs,
        metadata: {
          totalCount: filteredJobs.length,
          softwareCount: filteredJobs.filter(j => j.classification.isSoftwareAdjacent).length,
          fetchedAt: new Date().toISOString(),
        },
      };
    } catch (error) {
      if (error instanceof APIError) {
        throw error;
      }
      throw new APIError(
        `Failed to fetch Greenhouse jobs: ${error.message}`,
        undefined,
        'greenhouse',
        true
      );
    }
  },
};
```

#### Lever Client

```typescript
// src/api/leverClient.ts

/**
 * Lever postings API client.
 */
export const leverClient: JobAPIClient = {
  async fetchJobs(config, options = {}) {
    if (config.type !== 'lever') {
      throw new Error('Invalid config type for Lever client');
    }

    // Lever API endpoint: https://api.lever.co/v0/postings/{company}
    const url = `https://api.lever.co/v0/postings/${config.companyId}`;

    try {
      const response = await fetch(url, {
        signal: options.signal,
        headers: {
          'Accept': 'application/json',
        },
      });

      if (!response.ok) {
        throw new APIError(
          `Lever API error: ${response.statusText}`,
          response.status,
          'lever',
          response.status >= 500 || response.status === 429
        );
      }

      const data: LeverJobResponse[] = await response.json();

      // Transform to internal model
      const jobs = data.map(job => transformLeverJob(job, config.companyId));

      // Apply filters
      const filteredJobs = options.since
        ? jobs.filter(job => new Date(job.createdAt) >= new Date(options.since!))
        : jobs;

      return {
        jobs: filteredJobs,
        metadata: {
          totalCount: filteredJobs.length,
          softwareCount: filteredJobs.filter(j => j.classification.isSoftwareAdjacent).length,
          fetchedAt: new Date().toISOString(),
        },
      };
    } catch (error) {
      if (error instanceof APIError) {
        throw error;
      }
      throw new APIError(
        `Failed to fetch Lever jobs: ${error.message}`,
        undefined,
        'lever',
        true
      );
    }
  },
};
```

### Transformation Layer

```typescript
// src/api/transformers/greenhouseTransformer.ts

import { classifyJobRole } from '../../utils/roleClassification';

export function transformGreenhouseJob(raw: GreenhouseJobResponse): Job {
  // Extract department (first department if multiple)
  const department = raw.departments[0]?.name;

  // Extract location (first office if multiple)
  const location = raw.offices[0]?.name || raw.location?.name;

  // Create base job object
  const job: Omit<Job, 'classification'> = {
    id: raw.id.toString(),
    source: 'greenhouse',
    company: 'spacex', // TODO: Make dynamic based on config
    title: raw.title,
    department,
    location,
    createdAt: raw.updated_at, // Greenhouse uses updated_at
    url: raw.absolute_url,
    tags: raw.metadata?.map(m => m.value) || [],
    raw,
  };

  // Classify role
  const classification = classifyJobRole(job);

  return {
    ...job,
    classification,
  };
}
```

```typescript
// src/api/transformers/leverTransformer.ts

import { classifyJobRole } from '../../utils/roleClassification';

export function transformLeverJob(raw: LeverJobResponse, companyId: string): Job {
  const job: Omit<Job, 'classification'> = {
    id: raw.id,
    source: 'lever',
    company: companyId,
    title: raw.text,
    department: raw.categories.department,
    team: raw.categories.team,
    location: raw.categories.location,
    isRemote: raw.workplaceType === 'remote',
    employmentType: raw.categories.commitment,
    createdAt: new Date(raw.createdAt).toISOString(),
    url: raw.hostedUrl,
    tags: raw.tags || [],
    raw,
  };

  const classification = classifyJobRole(job);

  return {
    ...job,
    classification,
  };
}
```

### Async Thunks

```typescript
// src/features/jobs/jobsThunks.ts

import { createAsyncThunk } from '@reduxjs/toolkit';
import { COMPANIES } from '../../config/companies';
import { greenhouseClient } from '../../api/greenhouseClient';
import { leverClient } from '../../api/leverClient';

export const loadJobsForCompany = createAsyncThunk(
  'jobs/loadJobsForCompany',
  async (
    { companyId, timeWindow }: { companyId: string; timeWindow: TimeWindow },
    { signal, rejectWithValue }
  ) => {
    const company = COMPANIES.find(c => c.id === companyId);

    if (!company) {
      return rejectWithValue(`Company not found: ${companyId}`);
    }

    // Calculate 'since' timestamp based on time window
    const since = calculateSinceTimestamp(timeWindow);

    try {
      // Select appropriate client based on ATS type
      const client = company.ats === 'greenhouse' ? greenhouseClient : leverClient;

      const result = await client.fetchJobs(company.config, {
        since,
        signal,
      });

      return {
        companyId,
        jobs: result.jobs,
        metadata: result.metadata,
      };
    } catch (error) {
      if (error instanceof APIError) {
        return rejectWithValue({
          message: error.message,
          statusCode: error.statusCode,
          retryable: error.retryable,
        });
      }
      return rejectWithValue({ message: 'Unknown error occurred' });
    }
  }
);
```

---

## Component Architecture

### Component Hierarchy

```
App
├── ThemeProvider (MUI)
├── Provider (Redux)
└── Layout
    ├── Header
    │   ├── CompanySelect
    │   └── TimeWindowSelect
    ├── MainContent
    │   ├── GraphSection
    │   │   ├── GraphFilters
    │   │   └── JobPostingsChart
    │   ├── ListSection
    │   │   ├── ListFilters
    │   │   └── JobList
    │   │       └── JobCard (repeated)
    │   └── BucketJobsModal
    └── Footer (optional)
```

### Key Components

#### 1. JobPostingsChart

```typescript
// src/components/JobPostingsChart/JobPostingsChart.tsx

interface JobPostingsChartProps {
  /** Bucketed data for the chart */
  data: TimeBucket[];

  /** Click handler for data points */
  onPointClick: (bucket: TimeBucket) => void;

  /** Loading state */
  isLoading?: boolean;

  /** Optional height override */
  height?: number;
}

export const JobPostingsChart: React.FC<JobPostingsChartProps> = ({
  data,
  onPointClick,
  isLoading = false,
  height = 400,
}) => {
  // Transform TimeBucket[] to Recharts format
  const chartData = data.map(bucket => ({
    time: new Date(bucket.bucketStart).getTime(),
    count: bucket.count,
    label: formatBucketLabel(bucket),
    bucket, // Store original for click handler
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart
        data={chartData}
        onClick={(e) => {
          if (e && e.activePayload) {
            onPointClick(e.activePayload[0].payload.bucket);
          }
        }}
      >
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          dataKey="time"
          type="number"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(tick) => format(new Date(tick), 'HH:mm')}
        />
        <YAxis />
        <Tooltip content={<CustomTooltip />} />
        <Line
          type="monotone"
          dataKey="count"
          stroke="#000"
          strokeWidth={2}
          dot={{ r: 4 }}
          activeDot={{ r: 6 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
};
```

#### 2. JobList

```typescript
// src/components/JobList/JobList.tsx

interface JobListProps {
  /** Jobs to display */
  jobs: Job[];

  /** Loading state */
  isLoading?: boolean;

  /** Empty state message */
  emptyMessage?: string;
}

export const JobList: React.FC<JobListProps> = ({
  jobs,
  isLoading = false,
  emptyMessage = 'No jobs found',
}) => {
  if (isLoading) {
    return <CircularProgress />;
  }

  if (jobs.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', py: 4 }}>
        <Typography color="text.secondary">{emptyMessage}</Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={2}>
      {jobs.map(job => (
        <JobCard key={job.id} job={job} />
      ))}
    </Stack>
  );
};
```

#### 3. BucketJobsModal

```typescript
// src/components/BucketJobsModal/BucketJobsModal.tsx

export const BucketJobsModal: React.FC = () => {
  const dispatch = useAppDispatch();
  const { open, bucketStart, bucketEnd, filteredJobIds } = useAppSelector(
    state => state.ui.graphModal
  );

  const jobs = useAppSelector(state => {
    if (!filteredJobIds) return [];
    const allJobs = selectCurrentCompanyJobs(state);
    return allJobs.filter(job => filteredJobIds.includes(job.id));
  });

  const handleClose = () => {
    dispatch(closeGraphModal());
  };

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullScreen={useMediaQuery(theme.breakpoints.down('sm'))}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>
        Jobs posted between{' '}
        {bucketStart && format(new Date(bucketStart), 'PPpp')} and{' '}
        {bucketEnd && format(new Date(bucketEnd), 'PPpp')}
      </DialogTitle>
      <DialogContent>
        <JobList jobs={jobs} />
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
};
```

---

## Testing Strategy

### Test Coverage Requirements

- **Minimum Coverage**: 80% overall
- **Critical Paths**: 100% (role classification, time bucketing, data transformation)
- **Redux Logic**: 100% (reducers, selectors, thunks)
- **Components**: 80% (key user interactions)

### Test Structure

```
src/__tests__/
├── utils/
│   ├── roleClassification.test.ts
│   ├── timeBucketing.test.ts
│   └── dateUtils.test.ts
├── api/
│   ├── greenhouseClient.test.ts
│   ├── leverClient.test.ts
│   └── transformers/
│       ├── greenhouseTransformer.test.ts
│       └── leverTransformer.test.ts
├── features/
│   ├── jobs/
│   │   ├── jobsSlice.test.ts
│   │   ├── jobsSelectors.test.ts
│   │   └── jobsThunks.test.ts
│   └── filters/
│       ├── filtersSlice.test.ts
│       └── filtersSelectors.test.ts
└── components/
    ├── JobPostingsChart.test.tsx
    ├── JobList.test.tsx
    └── BucketJobsModal.test.tsx
```

### Testing Examples

#### Role Classification Tests

```typescript
// src/__tests__/utils/roleClassification.test.ts

describe('classifyJobRole', () => {
  it('should classify frontend roles correctly', () => {
    const job = createMockJob({
      title: 'Senior Frontend Engineer',
      department: 'Engineering',
    });

    const result = classifyJobRole(job);

    expect(result.isSoftwareAdjacent).toBe(true);
    expect(result.category).toBe('frontend');
    expect(result.matchedKeywords).toContain('frontend');
  });

  it('should classify non-tech roles as nonTech', () => {
    const job = createMockJob({
      title: 'HR Manager',
      department: 'Human Resources',
    });

    const result = classifyJobRole(job);

    expect(result.isSoftwareAdjacent).toBe(false);
    expect(result.category).toBe('nonTech');
  });

  it('should handle ambiguous titles with confidence scoring', () => {
    const job = createMockJob({
      title: 'Technical Program Manager',
      department: 'Engineering',
    });

    const result = classifyJobRole(job);

    expect(result.isSoftwareAdjacent).toBe(true);
    expect(result.confidence).toBeLessThan(1.0);
  });
});
```

#### API Client Tests with MSW

```typescript
// src/__tests__/api/greenhouseClient.test.ts

import { rest } from 'msw';
import { setupServer } from 'msw/node';
import { greenhouseClient } from '../../api/greenhouseClient';

const server = setupServer(
  rest.get('https://boards-api.greenhouse.io/v1/boards/:token/jobs', (req, res, ctx) => {
    return res(
      ctx.json({
        jobs: [
          {
            id: 123,
            title: 'Software Engineer',
            absolute_url: 'https://example.com/job/123',
            location: { name: 'Los Angeles, CA' },
            departments: [{ id: 1, name: 'Engineering' }],
            offices: [],
            updated_at: '2025-11-20T12:00:00Z',
          },
        ],
      })
    );
  })
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('greenhouseClient', () => {
  it('should fetch and transform jobs correctly', async () => {
    const result = await greenhouseClient.fetchJobs({
      type: 'greenhouse',
      boardToken: 'test-token',
    });

    expect(result.jobs).toHaveLength(1);
    expect(result.jobs[0]).toMatchObject({
      id: '123',
      source: 'greenhouse',
      title: 'Software Engineer',
      location: 'Los Angeles, CA',
    });
  });

  it('should handle API errors gracefully', async () => {
    server.use(
      rest.get('https://boards-api.greenhouse.io/v1/boards/:token/jobs', (req, res, ctx) => {
        return res(ctx.status(500), ctx.json({ error: 'Internal Server Error' }));
      })
    );

    await expect(
      greenhouseClient.fetchJobs({
        type: 'greenhouse',
        boardToken: 'test-token',
      })
    ).rejects.toThrow('Greenhouse API error');
  });
});
```

#### Component Tests

```typescript
// src/__tests__/components/JobList.test.tsx

import { render, screen } from '@testing-library/react';
import { JobList } from '../../components/JobList/JobList';
import { createMockJob } from '../testUtils';

describe('JobList', () => {
  it('should render job cards for each job', () => {
    const jobs = [
      createMockJob({ id: '1', title: 'Job 1' }),
      createMockJob({ id: '2', title: 'Job 2' }),
    ];

    render(<JobList jobs={jobs} />);

    expect(screen.getByText('Job 1')).toBeInTheDocument();
    expect(screen.getByText('Job 2')).toBeInTheDocument();
  });

  it('should show empty message when no jobs', () => {
    render(<JobList jobs={[]} emptyMessage="No results" />);

    expect(screen.getByText('No results')).toBeInTheDocument();
  });

  it('should show loading spinner when loading', () => {
    render(<JobList jobs={[]} isLoading />);

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });
});
```

---

## Implementation Sequence

### Phase 1: Foundation (Steps 1-3)

#### STEP-01: Project & Tooling Setup

**Objective**: Initialize project with all required dependencies and configurations.

**Actions**:
1. Initialize Vite + React + TypeScript project
   ```bash
   npm create vite@latest . -- --template react-ts
   ```

2. Install core dependencies:
   ```bash
   npm install react-redux @reduxjs/toolkit recharts @mui/material @emotion/react @emotion/styled @mui/icons-material date-fns
   ```

3. Install dev dependencies:
   ```bash
   npm install -D jest @testing-library/react @testing-library/jest-dom @testing-library/user-event @types/jest msw eslint @typescript-eslint/eslint-plugin @typescript-eslint/parser prettier
   ```

4. Configure TypeScript (`tsconfig.json`):
   ```json
   {
     "compilerOptions": {
       "strict": true,
       "noImplicitAny": true,
       "strictNullChecks": true,
       "esModuleInterop": true
     }
   }
   ```

5. Configure Jest (`jest.config.js`)

6. Add npm scripts:
   ```json
   {
     "scripts": {
       "dev": "vite",
       "build": "tsc && vite build",
       "test": "jest",
       "test:watch": "jest --watch",
       "test:coverage": "jest --coverage",
       "type-check": "tsc --noEmit",
       "lint": "eslint src --ext ts,tsx"
     }
   }
   ```

**Validation**:
- [ ] `npm run dev` starts dev server
- [ ] `npm run type-check` passes with no errors
- [ ] `npm run test` runs (even with no tests)

---

#### STEP-02: Global Architecture & Redux Skeleton

**Objective**: Set up folder structure and Redux store foundation.

**Actions**:
1. Create folder structure:
   ```
   src/
   ├── app/
   ├── features/{jobs,filters,ui}/
   ├── api/
   ├── utils/
   ├── components/
   ├── config/
   └── hooks/
   ```

2. Create `src/app/store.ts`:
   - Configure Redux store with Redux Toolkit
   - Add placeholder slices (app, jobs, filters, ui)

3. Create stub slice files:
   - `src/features/jobs/jobsSlice.ts`
   - `src/features/filters/filtersSlice.ts`
   - `src/features/ui/uiSlice.ts`
   - Each exports minimal initial state

4. Create `src/app/App.tsx`:
   - Wrap with Redux `Provider`
   - Add basic layout skeleton

5. Add type definitions:
   - `src/types/index.ts` with core types (Job, Company, etc.)

**Validation**:
- [ ] Store initializes without errors
- [ ] Initial state shape matches specification
- [ ] Basic test confirms store creation

**Tests**:
```typescript
// src/__tests__/app/store.test.ts
import { store } from '../../app/store';

test('store initializes with expected shape', () => {
  const state = store.getState();
  expect(state).toHaveProperty('app');
  expect(state).toHaveProperty('jobs');
  expect(state).toHaveProperty('filters');
  expect(state).toHaveProperty('ui');
});
```

---

#### STEP-03: Internal Job Model & Classification Utilities

**Objective**: Implement core domain logic for job role classification.

**Actions**:
1. Define types in `src/types/job.ts`:
   - `Job` interface
   - `SoftwareRoleCategory` type
   - `RoleClassification` interface

2. Implement `src/utils/roleClassification.ts`:
   ```typescript
   export function classifyJobRole(job: Partial<Job>): RoleClassification {
     // Keyword-based classification logic
     // Title analysis
     // Department analysis
     // Tag analysis
     // Confidence scoring
   }
   ```

3. Create classification config:
   - `src/config/roleClassificationConfig.ts`
   - Category keywords mapping
   - Tech department patterns
   - Exclusion patterns

4. Add helper functions:
   - `isSoftwareRole(job: Job): boolean`
   - `getCategoryKeywords(category: SoftwareRoleCategory): string[]`

**Validation**:
- [ ] All keyword patterns tested
- [ ] Edge cases handled (empty title, ambiguous roles)
- [ ] Confidence scoring works as expected

**Tests**:
```typescript
// src/__tests__/utils/roleClassification.test.ts

describe('classifyJobRole', () => {
  const testCases = [
    { title: 'Senior Frontend Engineer', expected: 'frontend' },
    { title: 'Backend Developer', expected: 'backend' },
    { title: 'Data Scientist', expected: 'data' },
    { title: 'Machine Learning Engineer', expected: 'ml' },
    { title: 'HR Manager', expected: 'nonTech' },
    { title: 'Sales Executive', expected: 'nonTech' },
  ];

  testCases.forEach(({ title, expected }) => {
    it(`should classify "${title}" as ${expected}`, () => {
      const job = { title, department: 'Engineering' };
      const result = classifyJobRole(job);
      expect(result.category).toBe(expected);
    });
  });

  it('should have higher confidence for clear titles', () => {
    const job = { title: 'Software Engineer' };
    const result = classifyJobRole(job);
    expect(result.confidence).toBeGreaterThan(0.8);
  });
});
```

---

### Phase 2: Data Layer (Steps 4-7)

#### STEP-04: ATS API Clients

**Objective**: Implement Greenhouse and Lever API clients with transformation.

**Actions**:
1. Create API types:
   - `src/api/types.ts`: Response interfaces for both ATS

2. Implement `src/api/greenhouseClient.ts`:
   - Fetch function with error handling
   - Rate limit handling
   - AbortSignal support

3. Implement `src/api/leverClient.ts`:
   - Fetch function with error handling
   - Response parsing

4. Create transformers:
   - `src/api/transformers/greenhouseTransformer.ts`
   - `src/api/transformers/leverTransformer.ts`
   - Both transform raw API → Job model

5. Add API error class:
   - `src/api/errors.ts`
   - Structured error handling

**Validation**:
- [ ] Sample API responses transform correctly
- [ ] Error handling covers all failure modes
- [ ] Type safety maintained throughout

**Tests**:
```typescript
// src/__tests__/api/transformers/greenhouseTransformer.test.ts

import { transformGreenhouseJob } from '../../../api/transformers/greenhouseTransformer';

const mockGreenhouseResponse = {
  id: 12345,
  title: 'Software Engineer',
  absolute_url: 'https://example.com/job/12345',
  location: { name: 'Los Angeles' },
  departments: [{ id: 1, name: 'Engineering' }],
  offices: [],
  updated_at: '2025-11-20T10:00:00Z',
};

test('transforms Greenhouse job correctly', () => {
  const job = transformGreenhouseJob(mockGreenhouseResponse);

  expect(job).toMatchObject({
    id: '12345',
    source: 'greenhouse',
    title: 'Software Engineer',
    location: 'Los Angeles',
    department: 'Engineering',
  });
  expect(job.classification.isSoftwareAdjacent).toBe(true);
});
```

---

#### STEP-05: Jobs Slice & Async Thunks

**Objective**: Complete Redux jobs state management with async loading.

**Actions**:
1. Implement `src/features/jobs/jobsSlice.ts`:
   - Full state shape from specification
   - Reducers for CRUD operations
   - Extra reducers for async thunk states

2. Implement `src/features/jobs/jobsThunks.ts`:
   - `loadJobsForCompany` thunk
   - Company config lookup
   - ATS client selection logic
   - Error handling

3. Create `src/config/companies.ts`:
   - Company definitions (SpaceX, Nominal)
   - ATS configurations

4. Implement `src/features/jobs/jobsSelectors.ts`:
   - `selectJobsForCompany`
   - `selectCurrentCompanyJobs`
   - `selectJobsMetadata`

**Validation**:
- [ ] Thunk handles success/failure correctly
- [ ] State updates are immutable
- [ ] Selectors memoize properly

**Tests**:
```typescript
// src/__tests__/features/jobs/jobsThunks.test.ts

import { configureStore } from '@reduxjs/toolkit';
import jobsReducer from '../../../features/jobs/jobsSlice';
import { loadJobsForCompany } from '../../../features/jobs/jobsThunks';

const mockStore = configureStore({ reducer: { jobs: jobsReducer } });

test('loadJobsForCompany handles success', async () => {
  // Mock API client
  jest.mock('../../../api/greenhouseClient', () => ({
    fetchJobs: jest.fn().mockResolvedValue({
      jobs: [{ id: '1', title: 'Test Job' }],
      metadata: { totalCount: 1 },
    }),
  }));

  await mockStore.dispatch(
    loadJobsForCompany({ companyId: 'spacex', timeWindow: '24h' })
  );

  const state = mockStore.getState().jobs;
  expect(state.byCompany.spacex.items).toHaveLength(1);
  expect(state.byCompany.spacex.isLoading).toBe(false);
});
```

---

#### STEP-06: Filter Slices

**Objective**: Implement independent filter state for graph and list.

**Actions**:
1. Implement `src/features/filters/filtersSlice.ts`:
   - Graph filter state + actions
   - List filter state + actions
   - Reset actions

2. Implement `src/features/filters/filtersSelectors.ts`:
   - `selectGraphFilters`
   - `selectListFilters`
   - Computed filter helpers

3. Add filter types:
   - `src/types/filters.ts`

**Validation**:
- [ ] Filter updates are independent
- [ ] Reset actions work correctly
- [ ] Type safety for filter values

**Tests**:
```typescript
// src/__tests__/features/filters/filtersSlice.test.ts

import filtersReducer, {
  setGraphTimeWindow,
  toggleGraphSoftwareOnly,
} from '../../../features/filters/filtersSlice';

test('updates graph time window', () => {
  const initialState = { graph: { timeWindow: '24h' }, list: {} };
  const newState = filtersReducer(initialState, setGraphTimeWindow('1h'));
  expect(newState.graph.timeWindow).toBe('1h');
});

test('toggles software-only filter', () => {
  const initialState = { graph: { softwareOnly: true }, list: {} };
  const newState = filtersReducer(initialState, toggleGraphSoftwareOnly());
  expect(newState.graph.softwareOnly).toBe(false);
});
```

---

#### STEP-07: Time Bucketing Logic

**Objective**: Implement time bucketing algorithm for graph visualization.

**Actions**:
1. Create `src/utils/timeBucketing.ts`:
   ```typescript
   export function bucketJobsByTime(
     jobs: Job[],
     timeWindow: TimeWindow
   ): TimeBucket[] {
     // Calculate bucket size based on time window
     // Group jobs into time buckets
     // Return sorted bucket array
   }
   ```

2. Add time utilities:
   - `src/utils/dateUtils.ts`
   - `calculateSinceTimestamp(timeWindow: TimeWindow): string`
   - `getBucketSize(timeWindow: TimeWindow): number`
   - `formatBucketLabel(bucket: TimeBucket): string`

3. Implement bucket resolution logic:
   - ≤24h: hourly buckets
   - 3-7 days: 6-hour or daily buckets

**Validation**:
- [ ] Buckets are evenly sized
- [ ] Jobs assigned to correct buckets
- [ ] Edge cases handled (bucket boundaries)

**Tests**:
```typescript
// src/__tests__/utils/timeBucketing.test.ts

import { bucketJobsByTime } from '../../utils/timeBucketing';

test('creates hourly buckets for 24h window', () => {
  const jobs = [
    { id: '1', createdAt: '2025-11-20T10:30:00Z' },
    { id: '2', createdAt: '2025-11-20T10:45:00Z' },
    { id: '3', createdAt: '2025-11-20T11:15:00Z' },
  ];

  const buckets = bucketJobsByTime(jobs, '24h');

  // Should have buckets for 10:00-11:00 and 11:00-12:00
  expect(buckets.some(b => b.count === 2)).toBe(true); // 10:00 hour
  expect(buckets.some(b => b.count === 1)).toBe(true); // 11:00 hour
});

test('handles empty job arrays', () => {
  const buckets = bucketJobsByTime([], '24h');
  expect(buckets).toHaveLength(24); // 24 empty hourly buckets
  expect(buckets.every(b => b.count === 0)).toBe(true);
});
```

---

### Phase 3: UI Components (Steps 8-11)

#### STEP-08: Graph Component

**Objective**: Build interactive Recharts line graph with click handling.

**Actions**:
1. Implement `src/components/JobPostingsChart/JobPostingsChart.tsx`:
   - Recharts LineChart setup
   - Data transformation for Recharts
   - Click handler for points
   - Tooltip component

2. Create `src/components/JobPostingsChart/ChartTooltip.tsx`:
   - Custom tooltip with bucket info

3. Implement graph filters:
   - `src/components/filters/GraphFilters.tsx`
   - Location, department, role category dropdowns
   - Software-only toggle

4. Wire up to Redux:
   - Use `selectGraphBucketData` selector
   - Dispatch modal open action on click

**Validation**:
- [ ] Graph renders with sample data
- [ ] Click opens modal with correct bucket
- [ ] Filters update graph data
- [ ] Responsive on mobile

**Tests**:
```typescript
// src/__tests__/components/JobPostingsChart.test.tsx

import { render, screen, fireEvent } from '@testing-library/react';
import { JobPostingsChart } from '../../components/JobPostingsChart/JobPostingsChart';

test('renders chart with data points', () => {
  const data = [
    { bucketStart: '2025-11-20T10:00:00Z', bucketEnd: '2025-11-20T11:00:00Z', count: 5, jobIds: [] },
  ];

  render(<JobPostingsChart data={data} onPointClick={jest.fn()} />);

  // Recharts renders SVG
  expect(screen.getByRole('img', { hidden: true })).toBeInTheDocument();
});

test('calls onPointClick when point is clicked', () => {
  const onPointClick = jest.fn();
  const data = [
    { bucketStart: '2025-11-20T10:00:00Z', bucketEnd: '2025-11-20T11:00:00Z', count: 5, jobIds: ['1', '2'] },
  ];

  render(<JobPostingsChart data={data} onPointClick={onPointClick} />);

  // Simulate click on chart point (requires Recharts test utils)
  // fireEvent.click(...);
  // expect(onPointClick).toHaveBeenCalledWith(data[0]);
});
```

---

#### STEP-09: Job List & List Filters

**Objective**: Build filterable job list with search and filters.

**Actions**:
1. Implement `src/components/JobList/JobList.tsx`:
   - Map jobs to JobCard components
   - Loading state
   - Empty state

2. Implement `src/components/JobList/JobCard.tsx`:
   - Display job details
   - Link to external posting
   - Posted time (relative format)

3. Implement `src/components/filters/ListFilters.tsx`:
   - Search input with debouncing
   - Time window select
   - Software-only toggle
   - Additional filter controls

4. Wire up to Redux:
   - Use `selectListFilteredJobs` selector
   - Dispatch filter actions

**Validation**:
- [ ] Jobs render correctly
- [ ] Search filters jobs
- [ ] Filters are independent from graph
- [ ] Mobile responsive layout

**Tests**:
```typescript
// src/__tests__/components/JobList.test.tsx

import { render, screen } from '@testing-library/react';
import { JobList } from '../../components/JobList/JobList';

test('renders job cards', () => {
  const jobs = [
    { id: '1', title: 'Job 1', company: 'SpaceX', url: 'http://example.com' },
  ];

  render(<JobList jobs={jobs} />);
  expect(screen.getByText('Job 1')).toBeInTheDocument();
});

test('shows empty state when no jobs', () => {
  render(<JobList jobs={[]} />);
  expect(screen.getByText(/no jobs/i)).toBeInTheDocument();
});
```

---

#### STEP-10: Bucket Jobs Modal

**Objective**: Build modal for graph point details.

**Actions**:
1. Implement `src/components/BucketJobsModal/BucketJobsModal.tsx`:
   - MUI Dialog component
   - Read modal state from Redux
   - Display filtered jobs
   - Close action

2. Implement `src/features/ui/uiSlice.ts`:
   - `openGraphModal` action
   - `closeGraphModal` action
   - Modal state management

3. Wire up to graph:
   - Graph click dispatches `openGraphModal`
   - Modal reads `ui.graphModal` state

**Validation**:
- [ ] Modal opens on graph click
- [ ] Shows correct jobs for bucket
- [ ] Closes properly
- [ ] Full-screen on mobile

**Tests**:
```typescript
// src/__tests__/components/BucketJobsModal.test.tsx

import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BucketJobsModal } from '../../components/BucketJobsModal/BucketJobsModal';
import { createMockStore } from '../testUtils';

test('renders when open', () => {
  const store = createMockStore({
    ui: {
      graphModal: {
        open: true,
        bucketStart: '2025-11-20T10:00:00Z',
        bucketEnd: '2025-11-20T11:00:00Z',
        filteredJobIds: ['1'],
      },
    },
  });

  render(
    <Provider store={store}>
      <BucketJobsModal />
    </Provider>
  );

  expect(screen.getByText(/jobs posted between/i)).toBeInTheDocument();
});
```

---

#### STEP-11: Company Selector & Multi-View

**Objective**: Implement company switching and view management.

**Actions**:
1. Implement `src/config/companies.ts`:
   ```typescript
   export const COMPANIES: Company[] = [
     {
       id: 'spacex',
       name: 'SpaceX',
       ats: 'greenhouse',
       config: { type: 'greenhouse', boardToken: 'spacex' },
     },
     {
       id: 'nominal',
       name: 'Nominal',
       ats: 'lever',
       config: { type: 'lever', companyId: 'nominal', jobsUrl: 'https://jobs.lever.co/nominal' },
     },
   ];
   ```

2. Implement `src/components/filters/CompanySelect.tsx`:
   - MUI Select with company options
   - Dispatch company selection

3. Update `src/features/app/appSlice.ts`:
   - `setSelectedCompanyId` action
   - Derive view type from selected company

4. Update thunk to handle company switching:
   - Auto-load jobs when company changes
   - Cache jobs per company

**Validation**:
- [ ] Company dropdown lists all companies
- [ ] Selecting company loads correct data
- [ ] View adapts to ATS type
- [ ] Jobs cached per company

**Tests**:
```typescript
// src/__tests__/features/app/appSlice.test.ts

import appReducer, { setSelectedCompanyId } from '../../../features/app/appSlice';

test('updates selected company', () => {
  const initialState = { selectedCompanyId: 'spacex' };
  const newState = appReducer(initialState, setSelectedCompanyId('nominal'));
  expect(newState.selectedCompanyId).toBe('nominal');
});
```

---

### Phase 4: Polish & Validation (Steps 12-14)

#### STEP-12: Mobile Responsiveness & Theming

**Objective**: Ensure mobile responsiveness and apply monochrome theme.

**Actions**:
1. Create `src/config/theme.ts`:
   ```typescript
   import { createTheme } from '@mui/material/styles';

   export const theme = createTheme({
     palette: {
       mode: 'light',
       primary: { main: '#000000' },
       secondary: { main: '#666666' },
       background: { default: '#ffffff', paper: '#f5f5f5' },
     },
     typography: {
       fontFamily: '"Inter", "Helvetica", "Arial", sans-serif',
     },
   });
   ```

2. Wrap app with ThemeProvider:
   - `src/app/App.tsx`

3. Implement responsive layouts:
   - Use MUI Grid and Box with breakpoints
   - Stack components vertically on mobile
   - Full-screen modal on small screens

4. Test on multiple screen sizes:
   - Mobile (320px, 375px, 414px)
   - Tablet (768px, 1024px)
   - Desktop (1280px, 1920px)

**Validation**:
- [ ] Layout adapts to all breakpoints
- [ ] No horizontal scroll on mobile
- [ ] Touch targets are ≥44px
- [ ] Theme applied consistently

---

#### STEP-13: Error & Loading Handling

**Objective**: Implement robust error handling and loading states.

**Actions**:
1. Add loading indicators:
   - Graph loading skeleton
   - List loading spinner
   - Company switch loading overlay

2. Implement error UI:
   - `src/components/ErrorBoundary.tsx`
   - `src/components/ErrorDisplay.tsx`
   - Retry button for failed loads

3. Add notifications:
   - `src/features/ui/uiSlice.ts` notifications state
   - MUI Snackbar for toast messages

4. Handle edge cases:
   - Network errors
   - API rate limits (429)
   - Malformed responses
   - Empty results

**Validation**:
- [ ] Loading states show appropriately
- [ ] Error messages are user-friendly
- [ ] Retry works after failure
- [ ] Network errors handled gracefully

**Tests**:
```typescript
// src/__tests__/features/jobs/jobsThunks.test.ts

test('handles API error with retry', async () => {
  const mockClient = {
    fetchJobs: jest.fn()
      .mockRejectedValueOnce(new APIError('Network error', undefined, 'greenhouse', true))
      .mockResolvedValueOnce({ jobs: [], metadata: {} }),
  };

  // First call fails
  await expect(loadJobsForCompany({ companyId: 'spacex' })).rejects.toThrow();

  // Retry succeeds
  await expect(loadJobsForCompany({ companyId: 'spacex' })).resolves.toBeTruthy();
});
```

---

#### STEP-14: Final Integration & Regression Tests

**Objective**: End-to-end validation of entire application.

**Actions**:
1. Create integration tests:
   - `src/__tests__/integration/fullWorkflow.test.tsx`
   - Test complete user flows

2. Manual testing checklist:
   - [ ] Load SpaceX jobs (Greenhouse)
   - [ ] Filter graph by time window
   - [ ] Click graph point → modal opens
   - [ ] Filter list independently
   - [ ] Switch to Nominal (Lever)
   - [ ] Verify mobile layout
   - [ ] Test error scenarios

3. Performance testing:
   - Load 1000+ jobs
   - Measure render time
   - Check for memory leaks

4. Accessibility audit:
   - Keyboard navigation
   - Screen reader compatibility
   - ARIA labels
   - Color contrast

**Validation**:
- [ ] All tests passing (>80% coverage)
- [ ] No TypeScript errors
- [ ] No console errors/warnings
- [ ] Performance metrics acceptable

**Integration Test Example**:
```typescript
// src/__tests__/integration/fullWorkflow.test.tsx

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { store } from '../../app/store';
import App from '../../app/App';

test('complete user workflow', async () => {
  const user = userEvent.setup();

  render(
    <Provider store={store}>
      <App />
    </Provider>
  );

  // Wait for initial load
  await waitFor(() => {
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  // Verify jobs loaded
  expect(screen.getByText(/software engineer/i)).toBeInTheDocument();

  // Change time window
  const timeWindowSelect = screen.getByLabelText(/time window/i);
  await user.click(timeWindowSelect);
  await user.click(screen.getByText('1 hour'));

  // Click graph point (requires chart to be rendered)
  // ... chart interaction ...

  // Verify modal opens
  await waitFor(() => {
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  // Close modal
  await user.click(screen.getByText(/close/i));

  // Switch company
  const companySelect = screen.getByLabelText(/company/i);
  await user.click(companySelect);
  await user.click(screen.getByText('Nominal'));

  // Verify Lever jobs loaded
  await waitFor(() => {
    expect(screen.getByText(/nominal/i)).toBeInTheDocument();
  });
});
```

---

## Validation Checklist

### Pre-Implementation

- [ ] All dependencies installed
- [ ] TypeScript configured (strict mode)
- [ ] Jest configured with React Testing Library
- [ ] ESLint + Prettier configured
- [ ] Folder structure created

### Post-Implementation (Gating Criteria)

#### Functionality
- [ ] SpaceX jobs load from Greenhouse API
- [ ] Nominal jobs load from Lever API
- [ ] Graph displays correct time-series data
- [ ] Graph filters affect chart data
- [ ] List filters work independently
- [ ] Clicking graph point opens modal
- [ ] Modal shows correct job subset
- [ ] Company switching works
- [ ] Time window changes update data

#### Code Quality
- [ ] TypeScript strict mode: 0 errors
- [ ] ESLint: 0 errors, minimal warnings
- [ ] Test coverage: ≥80% overall
- [ ] Critical path coverage: 100%
- [ ] No `any` types (except unavoidable)
- [ ] All TODOs resolved or documented

#### UI/UX
- [ ] Mobile responsive (320px - 1920px)
- [ ] Theme applied consistently
- [ ] Loading states render correctly
- [ ] Error states user-friendly
- [ ] Keyboard navigable
- [ ] ARIA labels present
- [ ] No console errors

#### Performance
- [ ] Handles 1000+ jobs without lag
- [ ] No memory leaks
- [ ] Memoization working (selectors)
- [ ] API calls not duplicated

#### Documentation
- [ ] README.md updated with:
  - Setup instructions
  - Available scripts
  - Architecture overview
  - Testing guide
- [ ] Code comments for complex logic
- [ ] Type definitions documented

---

## Future Migration Path: RTK Query

### When to Migrate

Migrate to RTK Query when:
- API caching becomes critical
- Request deduplication needed
- Automatic refetching desired
- Normalized cache preferred

### Migration Strategy

1. **Install RTK Query** (already included in @reduxjs/toolkit)

2. **Create API Slice**:
   ```typescript
   // src/api/apiSlice.ts
   import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

   export const jobsApi = createApi({
     reducerPath: 'jobsApi',
     baseQuery: fetchBaseQuery({ baseUrl: '/' }),
     endpoints: (builder) => ({
       getGreenhouseJobs: builder.query<Job[], { boardToken: string }>({
         queryFn: async ({ boardToken }) => {
           const result = await greenhouseClient.fetchJobs({
             type: 'greenhouse',
             boardToken,
           });
           return { data: result.jobs };
         },
       }),
       getLeverJobs: builder.query<Job[], { companyId: string }>({
         queryFn: async ({ companyId }) => {
           const result = await leverClient.fetchJobs({
             type: 'lever',
             companyId,
             jobsUrl: `https://jobs.lever.co/${companyId}`,
           });
           return { data: result.jobs };
         },
       }),
     }),
   });
   ```

3. **Replace Thunks with Hooks**:
   ```typescript
   // Before
   const dispatch = useAppDispatch();
   useEffect(() => {
     dispatch(loadJobsForCompany({ companyId: 'spacex', timeWindow: '24h' }));
   }, [companyId]);

   // After
   const { data: jobs, isLoading } = useGetGreenhouseJobsQuery({
     boardToken: 'spacex',
   });
   ```

4. **Keep Existing Structure**:
   - Client modules remain unchanged
   - Transformers remain unchanged
   - Types remain unchanged
   - Only slice logic changes

---

## Appendix: Quick Reference

### Key File Locations

| Concept | Primary File |
|---------|-------------|
| Redux Store | `src/app/store.ts` |
| Job Types | `src/types/job.ts` |
| Role Classification | `src/utils/roleClassification.ts` |
| Time Bucketing | `src/utils/timeBucketing.ts` |
| Greenhouse Client | `src/api/greenhouseClient.ts` |
| Lever Client | `src/api/leverClient.ts` |
| Jobs Slice | `src/features/jobs/jobsSlice.ts` |
| Filters Slice | `src/features/filters/filtersSlice.ts` |
| Graph Component | `src/components/JobPostingsChart/` |
| Job List | `src/components/JobList/` |
| Modal | `src/components/BucketJobsModal/` |

### npm Scripts

```bash
npm run dev              # Start dev server (Vite)
npm run build            # Production build
npm run test             # Run all tests
npm run test:watch       # Watch mode
npm run test:coverage    # Coverage report
npm run type-check       # TypeScript validation
npm run lint             # ESLint
npm run format           # Prettier
```

### Testing Commands

```bash
# Run specific test file
npm test -- roleClassification.test.ts

# Update snapshots
npm test -- -u

# Debug tests
node --inspect-brk node_modules/.bin/jest --runInBand
```

### Common Patterns

#### Reading from Redux
```typescript
const jobs = useAppSelector(selectCurrentCompanyJobs);
const filters = useAppSelector(state => state.filters.graph);
```

#### Dispatching Actions
```typescript
const dispatch = useAppDispatch();
dispatch(setGraphTimeWindow('1h'));
dispatch(loadJobsForCompany({ companyId: 'spacex', timeWindow: '24h' }));
```

#### Memoized Selectors
```typescript
const filteredJobs = useAppSelector(selectGraphFilteredJobs);
// Only recomputes when dependencies change
```

---

## Notes for AI Agent (Claude Code)

### Execution Strategy

1. **Sequential Execution**: Follow steps in order (STEP-01 → STEP-14)
2. **Validation Gates**: Complete validation checklist after each step
3. **Test-First**: Write tests before or immediately after implementation
4. **Incremental Commits**: Commit after each completed step
5. **Error Handling**: If a step fails, resolve before proceeding

### Communication

- **Progress Updates**: Report completion of each step
- **Blockers**: Immediately flag if step cannot be completed
- **Clarifications**: Ask questions if requirements ambiguous
- **Deviations**: Explain any deviations from plan

### Quality Standards

- **Type Safety**: Enforce strict TypeScript (no `any`)
- **Test Coverage**: Maintain ≥80% coverage
- **Code Style**: Follow ESLint/Prettier rules
- **Documentation**: Add JSDoc for complex functions

### Success Criteria

Implementation is complete when:
1. All 14 steps validated ✓
2. All tests passing ✓
3. No TypeScript errors ✓
4. Manual testing checklist complete ✓
5. README.md updated ✓

---

**End of Implementation Document**
