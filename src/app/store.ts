import { configureStore } from '@reduxjs/toolkit';
import appReducer from '../features/app/appSlice';
import graphFiltersReducer from '../features/filters/graphFiltersSlice';
import listFiltersReducer from '../features/filters/listFiltersSlice';
import uiReducer from '../features/ui/uiSlice';
import { jobsApi } from '../features/jobs/jobsApi';

export const store = configureStore({
  reducer: {
    app: appReducer,
    graphFilters: graphFiltersReducer,
    listFilters: listFiltersReducer,
    ui: uiReducer,
    [jobsApi.reducerPath]: jobsApi.reducer,
  },
  middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(jobsApi.middleware),
});

/**
 * Root Redux state type
 */
export type RootState = ReturnType<typeof store.getState>;

/**
 * App dispatch type
 */
export type AppDispatch = typeof store.dispatch;
