import { describe, it, expect, vi } from 'vitest';
import {
  detectWebGLSupport,
  probeWebGLSupport,
} from '../../../../pages/AdminLandingPrototypesPage/prototypes/shared3d/detectWebGL';

function fakeCanvas(getContext: (id: string) => unknown): HTMLCanvasElement {
  return { getContext } as unknown as HTMLCanvasElement;
}

describe('probeWebGLSupport', () => {
  it('true when webgl2 is available', () => {
    expect(probeWebGLSupport(() => fakeCanvas((id) => (id === 'webgl2' ? {} : null)))).toBe(true);
  });

  it('falls back to webgl1 when webgl2 is unavailable', () => {
    const getContext = vi.fn((id: string) => (id === 'webgl' ? {} : null));
    expect(probeWebGLSupport(() => fakeCanvas(getContext))).toBe(true);
    expect(getContext).toHaveBeenCalledWith('webgl2');
    expect(getContext).toHaveBeenCalledWith('webgl');
  });

  it('false when no GL context exists', () => {
    expect(probeWebGLSupport(() => fakeCanvas(() => null))).toBe(false);
  });

  it('false when getContext throws', () => {
    expect(
      probeWebGLSupport(() =>
        fakeCanvas(() => {
          throw new Error('blocked');
        })
      )
    ).toBe(false);
  });

  it('false when canvas creation itself throws', () => {
    expect(
      probeWebGLSupport(() => {
        throw new Error('no document');
      })
    ).toBe(false);
  });
});

describe('detectWebGLSupport', () => {
  it('is false in jsdom (no GL contexts) — tests land on the fallback tier', () => {
    expect(detectWebGLSupport()).toBe(false);
  });

  it('is false without a document (SSR-style environments)', () => {
    vi.stubGlobal('document', undefined);
    try {
      expect(detectWebGLSupport()).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
