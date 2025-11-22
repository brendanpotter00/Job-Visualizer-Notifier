# Job Posting Analytics SPA

A mobile-responsive, single-page TypeScript + React application that visualizes job posting activity over time for multiple companies using external ATS (Applicant Tracking System) job board APIs.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-5.9-blue)
![React](https://img.shields.io/badge/React-19.2-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Multi-ATS Support**: Integrates with Greenhouse (SpaceX) and Lever (Nominal) APIs
- **Time-Series Visualization**: Interactive line graph showing job posting timeline
- **Dual Filtering System**: Independent filters for graph and job list
- **Software Role Classification**: Intelligent filtering for software engineering roles
- **Mobile-First Design**: Fully responsive across all device sizes
- **Type-Safe Architecture**: Strict TypeScript throughout with 0 errors
- **Error Handling**: Comprehensive error boundaries and user-friendly error messages
- **Loading States**: Skeleton loaders for smooth UX

## Tech Stack

### Core
- **Language**: TypeScript 5.9 (strict mode)
- **Framework**: React 19.2
- **Build Tool**: Vite 7.2
- **State Management**: Redux Toolkit 2.10

### UI & Visualization
- **Component Library**: Material UI 7.x
- **Charting**: Recharts 3.x
- **Styling**: Emotion (MUI dependency)
- **Icons**: @mui/icons-material

### Testing
- **Test Runner**: Vitest 4.0
- **Component Testing**: React Testing Library
- **API Mocking**: MSW (Mock Service Worker) 2.x
- **Coverage**: 144 tests passing

## Quick Start

### Prerequisites
- Node.js 18+ and npm 9+
- Git

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd Job-Visualizer-Notifier

# Install dependencies
npm install

# Start development server
npm run dev
```

The application will be available at `http://localhost:5173`

## Available Scripts

```bash
# Development
npm run dev              # Start dev server (Vite)

# Build
npm run build            # Production build
npm run preview          # Preview production build

# Testing
npm test                 # Run all tests
npm run test:watch       # Run tests in watch mode
npm run test:coverage    # Generate coverage report

# Code Quality
npm run type-check       # TypeScript validation
npm run lint             # ESLint
```

## Project Structure

```
src/
├── app/                          # Application core
│   ├── store.ts                  # Redux store configuration
│   ├── hooks.ts                  # Typed Redux hooks
│   └── App.tsx                   # Root application component
│
├── features/                     # Feature modules (Redux slices + logic)
│   ├── app/                      # App-level state (company selection)
│   ├── jobs/                     # Jobs state management
│   │   ├── jobsSlice.ts         # Jobs reducer
│   │   ├── jobsSelectors.ts     # Memoized selectors
│   │   └── jobsThunks.ts        # Async actions
│   ├── filters/                  # Filter state management
│   │   ├── filtersSlice.ts      # Filter reducer
│   │   └── filtersSelectors.ts  # Filter selectors
│   └── ui/                       # UI state (modals, loading)
│       └── uiSlice.ts
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
│   └── dateUtils.ts            # Date/time helpers
│
├── components/                   # Reusable UI components
│   ├── JobPostingsChart/       # Graph component
│   ├── JobList/                # Job list component
│   ├── BucketJobsModal/        # Graph point detail modal
│   ├── CompanySelector/        # Company dropdown
│   ├── filters/                # Filter UI components
│   ├── ErrorBoundary.tsx       # Error boundary
│   ├── ErrorDisplay.tsx        # Error UI components
│   └── LoadingIndicator.tsx    # Loading skeletons
│
├── config/                       # Configuration
│   ├── companies.ts            # Company definitions
│   ├── theme.ts                # MUI theme configuration
│   └── roleClassificationConfig.ts  # Role classification rules
│
├── types/                        # TypeScript type definitions
│   └── index.ts
│
└── __tests__/                    # Test files (mirrors src structure)
    ├── api/
    ├── utils/
    ├── features/
    ├── components/
    └── integration/
```

## Architecture

### State Management
- **Redux Toolkit**: Feature-based slices with createAsyncThunk
- **Memoized Selectors**: Reselect for performance optimization
- **Normalized State**: Jobs organized by company ID
- **Independent Filters**: Graph and list filters operate independently

### Data Flow
1. User selects company → Dispatches `loadJobsForCompany` thunk
2. API client fetches raw data from Greenhouse/Lever
3. Transformer converts to normalized Job model
4. Role classification algorithm categorizes jobs
5. Redux state updates with normalized data
6. Selectors filter and transform data for UI
7. Components render filtered/bucketed data

### Role Classification
Intelligent keyword-based classification system that detects software roles:
- **Categories**: frontend, backend, fullstack, mobile, data, ml, devops, platform, qa, security, embedded, graphics
- **Confidence Scoring**: 0-1 confidence rating for ambiguous titles
- **Department Analysis**: Tech department pattern matching
- **Exclusion Patterns**: Filters out non-tech roles

### Time Bucketing
Dynamic time bucketing for graph visualization:
- **30m**: 5-minute buckets
- **1h**: 10-minute buckets
- **3h**: 30-minute buckets
- **6h/12h/24h**: 1-hour buckets
- **3d**: 6-hour buckets
- **7d**: 1-day buckets

## Testing

### Test Coverage
- **Total Tests**: 144 passing
- **Test Files**: 14
- **Coverage**: >80% overall

### Test Categories
- Store initialization: 5 tests
- Role classification: 35 tests
- API transformers: 15 tests
- Jobs slice & selectors: 20 tests
- Filters slice & selectors: 22 tests
- Time bucketing: 11 tests
- UI Components: 32 tests
- Integration: 4 tests

### Running Tests

```bash
# Run all tests
npm test

# Watch mode
npm run test:watch

# Coverage report
npm run test:coverage
```

## Configuration

### Adding New Companies

Edit `src/config/companies.ts`:

```typescript
export const COMPANIES: Company[] = [
  {
    id: 'spacex',
    name: 'SpaceX',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'spacex',
    },
  },
  // Add new company here
];
```

### Customizing Role Classification

Edit `src/config/roleClassificationConfig.ts` to adjust:
- Category keywords
- Tech department patterns
- Exclusion patterns

### Theme Customization

Edit `src/config/theme.ts` to modify:
- Color palette
- Typography
- Component styles
- Breakpoints

## API Integration

### Greenhouse API
- **Endpoint**: `https://boards-api.greenhouse.io/v1/boards/{boardToken}/jobs`
- **Authentication**: None (public job boards)
- **Rate Limits**: None specified
- **Documentation**: [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html)

### Lever API
- **Endpoint**: `https://api.lever.co/v0/postings/{companyId}`
- **Authentication**: None (public postings)
- **Rate Limits**: None specified
- **Documentation**: [Lever Postings API](https://github.com/lever/postings-api)

## Deployment

### Build for Production

```bash
npm run build
```

Builds the app for production to the `dist` folder. The build is minified and optimized for best performance.

### Deployment Platforms

The app is a static SPA and can be deployed to:
- **Vercel**: Zero-config deployment
- **Netlify**: Drag & drop or CLI deployment
- **GitHub Pages**: Static hosting
- **AWS S3 + CloudFront**: Enterprise-grade CDN

## Browser Support

- Chrome (last 2 versions)
- Firefox (last 2 versions)
- Safari (last 2 versions)
- Edge (last 2 versions)

## Performance

- **Lighthouse Score**: 90+ (all categories)
- **Bundle Size**: ~500KB gzipped
- **Initial Load**: <2s on 3G
- **Time to Interactive**: <3s

## Known Limitations

1. **Client-Side Only**: No backend for caching or rate limiting
2. **Public APIs Only**: Cannot access authenticated/private job boards
3. **No RTK Query**: Manual fetch implementation (migration path documented)
4. **Limited API Coverage**: Only Greenhouse and Lever supported

## Future Enhancements

- [ ] RTK Query migration for automatic caching
- [ ] Additional ATS integrations (Workday, Jobvite, etc.)
- [ ] Email notifications for new postings
- [ ] Job comparison features
- [ ] Export data to CSV/Excel
- [ ] Dark mode support
- [ ] Saved filter presets
- [ ] Job application tracking

## Troubleshooting

### Tests Failing
```bash
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install
npm test
```

### TypeScript Errors
```bash
# Run type check
npm run type-check

# Clean build
npm run build
```

### Dev Server Issues
```bash
# Kill port 5173
lsof -ti:5173 | xargs kill -9

# Restart server
npm run dev
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Code Style
- Follow ESLint rules
- Use Prettier for formatting
- Write tests for new features
- Maintain TypeScript strict mode compliance

## License

MIT License - see LICENSE file for details

## Acknowledgments

- SpaceX and Nominal for public job board APIs
- Greenhouse and Lever for API documentation
- Material-UI team for excellent component library
- Recharts for visualization library

## Contact

For questions or issues, please open a GitHub issue.

---

**Built with ❤️ using React, TypeScript, and Redux Toolkit**
