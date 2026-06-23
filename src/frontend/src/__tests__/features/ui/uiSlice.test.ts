import { describe, it, expect } from 'vitest';
import uiReducer, { setHideAdminFeatures, setDemoModeEnabled } from '../../../features/ui/uiSlice';

describe('uiSlice — hideAdminFeatures (demo-only, ephemeral)', () => {
  it('defaults hideAdminFeatures to false', () => {
    const state = uiReducer(undefined, { type: '@@INIT' });
    expect(state.hideAdminFeatures).toBe(false);
  });

  it('setHideAdminFeatures toggles the flag on and off', () => {
    const enabled = uiReducer(undefined, setHideAdminFeatures(true));
    expect(enabled.hideAdminFeatures).toBe(true);

    const disabled = uiReducer(enabled, setHideAdminFeatures(false));
    expect(disabled.hideAdminFeatures).toBe(false);
  });
});

describe('uiSlice — demoModeEnabled (demo-only, ephemeral)', () => {
  it('defaults demoModeEnabled to false', () => {
    const state = uiReducer(undefined, { type: '@@INIT' });
    expect(state.demoModeEnabled).toBe(false);
  });

  it('setDemoModeEnabled toggles the flag on and off', () => {
    const enabled = uiReducer(undefined, setDemoModeEnabled(true));
    expect(enabled.demoModeEnabled).toBe(true);

    const disabled = uiReducer(enabled, setDemoModeEnabled(false));
    expect(disabled.demoModeEnabled).toBe(false);
  });
});
