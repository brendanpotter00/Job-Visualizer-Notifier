# Architecture Overview

This document provides visual diagrams and detailed explanations of the Job Visualizer application architecture.

## Table of Contents

1. [High-Level Data Flow](#high-level-data-flow)
2. [Redux State Shape](#redux-state-shape)
3. [API Client Architecture](#api-client-architecture)
4. [Filter Slice Architecture](#filter-slice-architecture)
5. [Component Hierarchy](#component-hierarchy)
6. [Time Bucketing Algorithm](#time-bucketing-algorithm)
7. [Role Classification System](#role-classification-system)

---

## High-Level Data Flow

```mermaid
graph TB
    User[User Interaction]

    subgraph "React Components"
        CompSelector[CompanySelector]
        GraphSection[Graph Section]
        ListSection[List Section]
        MetricsDash[Metrics Dashboard]
    end

    subgraph "Redux Store"
        AppSlice[App Slice<br/>selectedCompany]
        JobsSlice[Jobs Slice<br/>byCompany, loading, error]
        GraphFilters[Graph Filters Slice]
        ListFilters[List Filters Slice]
        UISlice[UI Slice<br/>modals, state]
    end

    subgraph "Selectors Layer"
        JobsSelectors[Jobs Selectors<br/>selectCurrentCompanyJobs]
        FilterSelectors[Filter Selectors<br/>selectGraphFilteredJobs<br/>selectListFilteredJobs]
        BucketSelectors[Bucket Selectors<br/>selectGraphBucketData]
    end

    subgraph "API Layer"
        RTKQuery[RTK Query API<br/>getJobsForCompany]
        BaseClient[Base Client Factory]
        Clients[ATS Clients<br/>Greenhouse<br/>Lever<br/>Ashby<br/>Workday]
        Transformers[Transformers<br/>API → Job Model]
    end

    subgraph "External APIs"
        GreenhouseAPI[Greenhouse API]
        LeverAPI[Lever API]
        AshbyAPI[Ashby API]
        WorkdayAPI[Workday API]
    end

    User --> CompSelector
    CompSelector --> AppSlice
    AppSlice --> RTKQuery
    RTKQuery --> Clients
    Clients --> GreenhouseAPI
    Clients --> LeverAPI
    Clients --> AshbyAPI
    Clients --> WorkdayAPI
    GreenhouseAPI --> Transformers
    LeverAPI --> Transformers
    AshbyAPI --> Transformers
    WorkdayAPI --> Transformers
    Transformers --> JobsSlice

    JobsSlice --> JobsSelectors
    GraphFilters --> FilterSelectors
    ListFilters --> FilterSelectors
    JobsSelectors --> FilterSelectors
    FilterSelectors --> BucketSelectors

    BucketSelectors --> GraphSection
    FilterSelectors --> ListSection
    JobsSelectors --> MetricsDash

    GraphSection --> GraphFilters
    ListSection --> ListFilters
    GraphSection --> UISlice
```

User selects company → `getJobsForCompany` RTK Query endpoint → Factory selects API client → External API fetch → Transform to normalized Job model → RTK Query cache update → Memoized selectors filter data → Components render

---

## Redux State Shape

```mermaid
graph LR
    Store[Redux Store]

    Store --> App[app]
    Store --> Jobs[jobs]
    Store --> GraphFilters[graphFilters]
    Store --> ListFilters[listFilters]
    Store --> UI[ui]

    App --> SelectedCompany[selectedCompany: string]

    Jobs --> ByCompany[byCompany: Record]
    Jobs --> Loading[loading: Record]
    Jobs --> Error[error: Record]

    ByCompany --> CompanyData[companyId]
    CompanyData --> Items[items: Job array]
    CompanyData --> Metadata[metadata]

    Metadata --> LastFetch[lastFetchTime]
    Metadata --> TotalJobs[totalJobs]
    Metadata --> SoftwareJobs[softwareJobs]
    Metadata --> OldestJob[oldestJobDate]
    Metadata --> NewestJob[newestJobDate]

    GraphFilters --> GFilters[filters: GraphFilters]
    GFilters --> GTimeWindow[timeWindow]
    GFilters --> GSearchTags[searchTags]
    GFilters --> GLocations[locations]
    GFilters --> GDepartments[departments]

    ListFilters --> LFilters[filters: ListFilters]
    LFilters --> LTimeWindow[timeWindow]
    LFilters --> LSearchTags[searchTags]
    LFilters --> LEmploymentType[employmentType]

    UI --> Modals[graphModal, listModal]
    UI --> ModalData[modal job IDs, timestamps]
```

**Jobs Slice:**
```typescript
{
  byCompany: {
    [companyId]: {
      items: Job[],          // Normalized job array
      metadata: {
        lastFetchTime: string,
        totalJobs: number,
        softwareJobs: number,
        oldestJobDate: string,
        newestJobDate: string
      }
    }
  },
  loading: { [companyId]: boolean },
  error: { [companyId]: string | null }
}
```

**Filter Slices (Graph & List identical):**
```typescript
{
  filters: {
    timeWindow: TimeWindow,
    searchTags?: SearchTag[],
    locations: string[],
    departments: string[],
    employmentType?: EmploymentType
  }
}
```

Graph and list filters are completely independent. Jobs normalized by company ID for O(1) lookup.

---

## API Client Architecture

```mermaid
graph TB
    Factory[createAPIClient Factory]

    subgraph "Configuration Object"
        Config[ClientConfig]
        Config --> Name[name: string]
        Config --> BuildURL[buildUrl: function]
        Config --> ExtractJobs[extractJobs: function]
        Config --> Transformer[transformer: function]
        Config --> Validate[validateConfig: function]
    end

    Factory --> SharedLogic[Shared Logic]

    subgraph "Shared Logic"
        SharedLogic --> ValidateConf[1. Validate Config]
        SharedLogic --> FetchData[2. Fetch from API]
        SharedLogic --> ErrorHandle[3. Error Handling]
        SharedLogic --> FilterJobs[4. Filter by since/limit]
        SharedLogic --> TransformJobs[5. Transform Jobs]
        SharedLogic --> CalcMeta[6. Calculate Metadata]
        SharedLogic --> ReturnResp[7. Return JobsResponse]
    end

    Factory --> GreenhouseClient[greenhouseClient]
    Factory --> LeverClient[leverClient]
    Factory --> AshbyClient[ashbyClient]

    GreenhouseClient --> GTransformer[transformGreenhouseJob]
    LeverClient --> LTransformer[transformLeverJob]
    AshbyClient --> ATransformer[transformAshbyJob]

    Factory --> WorkdayClient[workdayClient]
    WorkdayClient --> WTransformer[transformWorkdayJob]

    GTransformer --> UnifiedModel[Unified Job Model]
    LTransformer --> UnifiedModel
    ATransformer --> UnifiedModel
    WTransformer --> UnifiedModel

    UnifiedModel --> FinalJob[Final Job Object]
```

Factory eliminates 220+ lines of duplication. All four clients use identical error handling, filtering, and metadata calculation. Add new ATS provider in ~15 lines instead of 74.

---

## Filter Slice Architecture

```mermaid
graph TB
    Factory[createFilterSlice Factory]

    subgraph "Factory Parameters"
        Params[Parameters]
        Params --> SliceName[name: graph or list]
        Params --> InitialState[initialFilters: GraphFilters or ListFilters]
    end

    Factory --> DynamicSlice[Dynamic Slice Generation]

    subgraph "Generated Slice"
        DynamicSlice --> SliceConfig[Slice Configuration]
        SliceConfig --> StateName[name: graphFilters / listFilters]
        SliceConfig --> State[initialState]
        SliceConfig --> Reducers[21 Reducers]

        Reducers --> TimeWindow[setGraphTimeWindow / setListTimeWindow]
        Reducers --> SearchTags[5 search tag actions]
        Reducers --> Locations[4 location actions]
        Reducers --> Departments[4 department actions]
        Reducers --> Employment[employment type actions]
        Reducers --> Reset[reset filters]
        Reducers --> Sync[sync from other slice]
    end

    Factory --> GraphSlice[graphFiltersSlice]
    Factory --> ListSlice[listFiltersSlice]

    GraphSlice --> GraphActions[Graph Actions<br/>setGraphTimeWindow<br/>addGraphSearchTag<br/>...]
    ListSlice --> ListActions[List Actions<br/>setListTimeWindow<br/>addListSearchTag<br/>...]

    GraphActions --> Store[Redux Store]
    ListActions --> Store

    Store --> Components[Components]
    Components --> Dispatch[Dispatch Actions]
    Dispatch --> GraphActions
    Dispatch --> ListActions
```

Factory eliminates 158 lines of duplication. Both graph and list slices dynamically generate 21 action creators each: search tags (5), locations/departments (4 each), time window, employment type, reset, and sync actions.

---

## Component Hierarchy

```mermaid
graph TB
    App[App.tsx<br/>Redux Provider + MUI Theme]

    App --> Header[Header Section]
    App --> Main[Main Content]

    Header --> CompSelector[CompanySelector<br/>Dropdown + Company Selection]

    Main --> MetricsDash[MetricsDashboard<br/>Job Count Cards]
    Main --> GraphSection[Graph Section]
    Main --> ListSection[List Section]
    Main --> Modals[Modals]

    MetricsDash --> JobCountCards[3 JobCountCard Components<br/>3 days / 24 hours / 12 hours]

    GraphSection --> GraphFilters[GraphFilters<br/>Time/Location/Dept/Software]
    GraphSection --> JobPostingsChart[JobPostingsChart<br/>Recharts Line Graph]

    GraphFilters --> TimeWindowSelect[Time Window Selector]
    GraphFilters --> LocationFilter[Location Multi-Select]
    GraphFilters --> DeptFilter[Department Multi-Select]
    GraphFilters --> SoftwareToggle[Software Only Toggle]

    JobPostingsChart --> ChartTooltip[ChartTooltip<br/>Custom Tooltip]
    JobPostingsChart --> CustomDot[CustomDot<br/>Clickable Points]

    ListSection --> ListFilters[ListFilters<br/>Search/Tags/Employment/Sync]
    ListSection --> JobList[JobList<br/>Virtualized List]

    ListFilters --> SearchInput[Search Input]
    ListFilters --> SearchTags[Search Tags Manager]
    ListFilters --> EmploymentFilter[Employment Type Filter]
    ListFilters --> SyncButton[Sync from Graph Button]

    JobList --> JobCards[JobCard Components<br/>Individual Job Display]

    JobCards --> JobTitle[Title + Link]
    JobCards --> JobMeta[Metadata Chips<br/>Location/Dept/Type/Category]
    JobCards --> JobDesc[Description Preview]
    JobCards --> JobTimestamp[Created Date]

    Modals --> BucketJobsModal[BucketJobsModal<br/>Graph Point Details]

    BucketJobsModal --> ModalJobList[JobList Component<br/>Reused from List Section]

    style App fill:#e1f5ff
    style GraphSection fill:#fff4e6
    style ListSection fill:#f3e5f5
    style Modals fill:#e8f5e9
```

App.tsx provides Redux/MUI setup. CompanySelector auto-loads jobs (single dispatch). MetricsDashboard shows job counts (no timer re-renders). Graph and List sections have independent filter systems with memoized data. BucketJobsModal reuses JobList for drill-down.

---

## Time Bucketing Algorithm

```mermaid
graph TB
    Start[Start: Jobs Array + Time Window]

    Start --> GetWindow[Get Time Window Duration]
    GetWindow --> CalcBucketSize[Calculate Bucket Size<br/>30m → 5min<br/>1h → 10min<br/>24h → 1hr<br/>7d → 1day]

    CalcBucketSize --> CalcRange[Calculate Time Range<br/>endTime = now<br/>startTime = now - window]

    CalcRange --> CreateBuckets[Create Empty Buckets]

    CreateBuckets --> Loop{For each bucket interval}

    Loop --> RoundStart[Round to bucket boundary<br/>align to bucket size]
    RoundStart --> CreateBucket[Create TimeBucket object<br/>bucketStart, bucketEnd<br/>jobs: array, count: 0]

    CreateBucket --> NextBucket{More buckets?}
    NextBucket -->|Yes| Loop
    NextBucket -->|No| FillBuckets[Fill Buckets with Jobs]

    FillBuckets --> JobLoop{For each job}
    JobLoop --> CheckTime{Job createdAt in range?}
    CheckTime -->|No| JobLoop
    CheckTime -->|Yes| FindBucket[Find matching bucket<br/>by timestamp]

    FindBucket --> AddJob[Add job ID to bucket<br/>Increment count]
    AddJob --> MoreJobs{More jobs?}
    MoreJobs -->|Yes| JobLoop
    MoreJobs -->|No| CalcCumulative[Calculate Cumulative Counts]

    CalcCumulative --> Cumulative[For each bucket:<br/>cumulativeCount = previous + current]
    Cumulative --> Sort[Sort buckets chronologically]
    Sort --> Return[Return TimeBucket array]

    Return --> End[End: Ready for Graph]

    style Start fill:#e1f5ff
    style End fill:#c8e6c9
    style CreateBuckets fill:#fff9c4
    style FillBuckets fill:#fff9c4
    style CalcCumulative fill:#fff9c4
```

### Bucket Size Mapping

| Time Window | Bucket Size | Max Buckets | Purpose |
|-------------|-------------|-------------|---------|
| 30m | 5 minutes | 6 | High granularity for recent activity |
| 1h | 10 minutes | 6 | Short-term trends |
| 3h | 30 minutes | 6 | Medium-term patterns |
| 6h | 1 hour | 6 | Half-day overview |
| 12h | 1 hour | 12 | Daily patterns |
| 24h | 1 hour | 24 | Full day cycle |
| 3d | 6 hours | 12 | Multi-day trends |
| 7d | 1 day | 7 | Weekly overview |
| 14d | 1 day | 14 | Two-week patterns |
| 30d | 1 day | 30 | Monthly view |
| 90d | 3 days | 30 | Quarterly trends |
| 180d | 6 days | 30 | Half-year overview |
| 1y | 12 days | 30 | Annual patterns |
| 2y | 24 days | 30 | Two-year trends |

Empty buckets created for entire range (critical for proper graph spacing). Buckets align to clean boundaries. Cumulative counts for line graphs. Time complexity: O(n + b). Results memoized via Redux selectors.

---

## Performance Optimizations

```mermaid
graph LR
    State[Redux State Changes]

    State --> Selectors[Memoized Selectors]

    Selectors --> L1[Level 1: Basic Selectors<br/>selectCurrentCompanyJobs<br/>selectGraphFilters]

    L1 --> L2[Level 2: Filtering<br/>selectGraphFilteredJobs<br/>selectListFilteredJobs]

    L2 --> L3[Level 3: Transformations<br/>selectGraphBucketData<br/>selectAvailableLocations]

    L3 --> Components[React Components]

    Components --> UseMemo[useMemo Hooks<br/>Chart data transformation<br/>Bucket job filtering]

    UseMemo --> UseCallback[useCallback Hooks<br/>Event handlers<br/>Modal actions]

    UseCallback --> Render[Final Render]

    style State fill:#e1f5ff
    style Selectors fill:#fff9c4
    style Components fill:#f3e5f5
    style Render fill:#c8e6c9
```

Selector memoization via `createSelector` from Reselect. Chart data wrapped in `useMemo`. Filter independence prevents cross-contamination. No timer re-renders in MetricsDashboard. Single dispatch in CompanySelector. RTK Query provides automatic caching and background refetching.

Key complexities: Load jobs O(n), time bucketing O(n + b), filtering O(n) memoized.

---

## Error Handling Flow

```mermaid
graph TB
    Start[API Call Initiated]

    Start --> Fetch[Fetch from ATS API]

    Fetch --> Success{Request Successful?}

    Success -->|No| CheckStatus{HTTP Status?}

    CheckStatus -->|500/429/503| Retryable[Create APIError<br/>isRetryable: true]
    CheckStatus -->|401/403/404| NonRetryable[Create APIError<br/>isRetryable: false]
    CheckStatus -->|Network Error| NetworkError[Create APIError<br/>Network failure]

    Success -->|Yes| Parse{Parse JSON}

    Parse -->|Success| Validate[Validate Response Structure]
    Parse -->|Failure| ParseError[Create APIError<br/>Invalid JSON]

    Validate -->|Success| Transform[Transform to Job Model]
    Validate -->|Failure| ValidationError[Create APIError<br/>Unexpected structure]

    Transform -->|Success| Return[Return JobsResponse]
    Transform -->|Failure| TransformError[Log Warning<br/>Skip invalid job]

    TransformError --> PartialReturn[Return Partial JobsResponse]

    Retryable --> RTKQueryError[RTK Query Error State]
    NonRetryable --> RTKQueryError
    NetworkError --> RTKQueryError
    ParseError --> RTKQueryError
    ValidationError --> RTKQueryError

    RTKQueryError --> ErrorSlice[Update Error State]
    ErrorSlice --> ShowUI[Display Error in UI]

    Return --> SuccessSlice[Update Redux Jobs State]
    PartialReturn --> SuccessSlice
    SuccessSlice --> UpdateUI[Render Jobs in UI]

    style Start fill:#e1f5ff
    style Return fill:#c8e6c9
    style PartialReturn fill:#fff9c4
    style Retryable fill:#ffcdd2
    style NonRetryable fill:#ffcdd2
    style RTKQueryError fill:#ffcdd2
    style ShowUI fill:#ffcdd2
    style UpdateUI fill:#c8e6c9
```

---

## Summary

This architecture provides clear separation of concerns, code reuse via factory patterns, RTK Query for efficient data fetching and caching, aggressive memoization, easy extensibility, full TypeScript coverage, comprehensive error handling, and efficient scaling to 1000+ jobs.

**Key Technologies:**
- RTK Query for API data management
- Redux Toolkit for UI state
- Factory patterns for API clients and filter slices
- Memoized selectors for performance
- Four ATS provider integrations (Greenhouse, Lever, Ashby, Workday)

For implementation details, see `CLAUDE.md`. For migration guidance, see `docs/MIGRATION.md`.
