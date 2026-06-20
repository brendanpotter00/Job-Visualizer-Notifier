import { configureStore } from '@reduxjs/toolkit';
import appReducer from '../features/app/appSlice';
import graphFiltersReducer from '../features/filters/slices/graphFiltersSlice';
import recentJobsFiltersReducer from '../features/filters/slices/recentJobsFiltersSlice';
import uiReducer from '../features/ui/uiSlice';
import enabledCompaniesReducer from '../features/preferences/enabledCompaniesSlice';
import { jobsApi } from '../features/jobs/jobsApi';
import { featuresApi } from '../features/features/featuresApi';
import { companiesApi } from '../features/companies/companiesApi';
import { feedbackApi } from '../features/feedback/feedbackApi';
import { adminApi } from '../features/admin/adminApi';
import { getTokenOrNull } from '../features/features/getTokenOrNull';

export const store = configureStore({
  reducer: {
    app: appReducer,
    graphFilters: graphFiltersReducer,
    recentJobsFilters: recentJobsFiltersReducer,
    ui: uiReducer,
    enabledCompanies: enabledCompaniesReducer,
    [jobsApi.reducerPath]: jobsApi.reducer,
    [featuresApi.reducerPath]: featuresApi.reducer,
    [companiesApi.reducerPath]: companiesApi.reducer,
    [feedbackApi.reducerPath]: feedbackApi.reducer,
    [adminApi.reducerPath]: adminApi.reducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      thunk: { extraArgument: { getTokenOrNull } },
    })
      .concat(jobsApi.middleware)
      .concat(featuresApi.middleware)
      .concat(companiesApi.middleware)
      .concat(feedbackApi.middleware)
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
