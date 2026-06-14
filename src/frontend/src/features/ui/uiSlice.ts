import { createSlice, PayloadAction } from '@reduxjs/toolkit';

/**
 * UI state (modals, notifications, etc.)
 */
export interface UIState {
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

  /**
   * Demo-only: when true, hide admin-only UI affordances (the Admin section
   * in the sidebar). Ephemeral and not persisted — resets to false on refresh.
   */
  hideAdminFeatures: boolean;
}

const initialState: UIState = {
  graphModal: {
    open: false,
  },
  globalLoading: false,
  notifications: [],
  hideAdminFeatures: false,
};

interface OpenGraphModalPayload {
  bucketStart: string;
  bucketEnd: string;
  filteredJobIds: string[];
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    openGraphModal(state, action: PayloadAction<OpenGraphModalPayload>) {
      state.graphModal = {
        open: true,
        ...action.payload,
      };
    },
    closeGraphModal(state) {
      state.graphModal = {
        open: false,
      };
    },
    setGlobalLoading(state, action: PayloadAction<boolean>) {
      state.globalLoading = action.payload;
    },
    addNotification(state, action: PayloadAction<Omit<UIState['notifications'][0], 'id'>>) {
      const id = Date.now().toString();
      state.notifications.push({ id, ...action.payload });
    },
    removeNotification(state, action: PayloadAction<string>) {
      state.notifications = state.notifications.filter((n) => n.id !== action.payload);
    },
    setHideAdminFeatures(state, action: PayloadAction<boolean>) {
      state.hideAdminFeatures = action.payload;
    },
  },
});

export const {
  openGraphModal,
  closeGraphModal,
  setGlobalLoading,
  addNotification,
  removeNotification,
  setHideAdminFeatures,
} = uiSlice.actions;

export default uiSlice.reducer;
