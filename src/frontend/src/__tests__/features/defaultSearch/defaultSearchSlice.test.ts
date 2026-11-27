import { describe, it, expect } from 'vitest';
import reducer, {
  resetDefaultSearch,
  saveFailed,
  saveStarted,
  saveSucceeded,
  type DefaultSearchState,
} from '../../../features/defaultSearch/defaultSearchSlice';

const initial: DefaultSearchState = { saving: false, result: null };

describe('defaultSearchSlice', () => {
  it('starts idle', () => {
    expect(reducer(undefined, { type: '@@init' })).toEqual(initial);
  });

  it('saveStarted marks saving and clears the last result', () => {
    const before: DefaultSearchState = { saving: false, result: { kind: 'saved', key: 'k' } };
    expect(reducer(before, saveStarted())).toEqual({ saving: true, result: null });
  });

  it('saveSucceeded records the saved key', () => {
    expect(reducer({ saving: true, result: null }, saveSucceeded('k1'))).toEqual({
      saving: false,
      result: { kind: 'saved', key: 'k1' },
    });
  });

  it('saveFailed records the key and the message', () => {
    expect(
      reducer({ saving: true, result: null }, saveFailed({ key: 'k2', message: 'Nope.' }))
    ).toEqual({ saving: false, result: { kind: 'error', key: 'k2', message: 'Nope.' } });
  });

  it('resetDefaultSearch goes back to idle', () => {
    expect(
      reducer({ saving: true, result: { kind: 'saved', key: 'k' } }, resetDefaultSearch())
    ).toEqual(initial);
  });
});
