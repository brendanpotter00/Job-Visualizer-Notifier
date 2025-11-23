import { configureStore } from '@reduxjs/toolkit';
import appReducer from '../features/app/appSlice';
import jobsReducer from '../features/jobs/jobsSlice';
import graphFiltersReducer from '../features/filters/graphFiltersSlice';
import listFiltersReducer from '../features/filters/listFiltersSlice';
import uiReducer from '../features/ui/uiSlice';

export const store = configureStore({
  reducer: {
    app: appReducer,
    jobs: jobsReducer,
    graphFilters: graphFiltersReducer,
    listFilters: listFiltersReducer,
    ui: uiReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        // Ignore these paths in the state for serialization checks
        ignoredPaths: ['jobs.byCompany.*.items.*.raw'],
      },
    }),
});

/**
 * Root Redux state type
 */
export type RootState = ReturnType<typeof store.getState>;

/**
 * App dispatch type
 */
export type AppDispatch = typeof store.dispatch;
