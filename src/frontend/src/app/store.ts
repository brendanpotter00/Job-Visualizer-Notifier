import { configureStore } from '@reduxjs/toolkit';
import appReducer from '../features/app/appSlice';
import graphFiltersReducer from '../features/filters/slices/graphFiltersSlice';
import listFiltersReducer from '../features/filters/slices/listFiltersSlice';
import recentJobsFiltersReducer from '../features/filters/slices/recentJobsFiltersSlice';
import uiReducer from '../features/ui/uiSlice';
import enabledCompaniesReducer from '../features/preferences/enabledCompaniesSlice';
import { jobsApi } from '../features/jobs/jobsApi';
import { featuresApi } from '../features/features/featuresApi';
import { adminApi } from '../features/admin/adminApi';
import { getTokenOrNull } from '../features/features/getTokenOrNull';

export const store = configureStore({
  reducer: {
    app: appReducer,
    graphFilters: graphFiltersReducer,
    listFilters: listFiltersReducer,
    recentJobsFilters: recentJobsFiltersReducer,
    ui: uiReducer,
    enabledCompanies: enabledCompaniesReducer,
    [jobsApi.reducerPath]: jobsApi.reducer,
    [featuresApi.reducerPath]: featuresApi.reducer,
    [adminApi.reducerPath]: adminApi.reducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      thunk: { extraArgument: { getTokenOrNull } },
    })
      .concat(jobsApi.middleware)
      .concat(featuresApi.middleware)
      .concat(adminApi.middleware),
});

/**
 * Root Redux state type
 */
export type RootState = ReturnType<typeof store.getState>;

/**
 * App dispatch type
 */
export type AppDispatch = typeof store.dispatch;
