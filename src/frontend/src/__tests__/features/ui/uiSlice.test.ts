import { describe, it, expect } from 'vitest';
import uiReducer, { setHideAdminFeatures } from '../../../features/ui/uiSlice';

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
