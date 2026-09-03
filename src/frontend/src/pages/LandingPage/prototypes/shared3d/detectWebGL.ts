/**
 * WebGL capability probe for the 3D prototypes' degradation ladder.
 *
 * Split into a pure-ish core (`probeWebGLSupport`, canvas factory injected so
 * tests can exercise every branch) and the browser entry point
 * (`detectWebGLSupport`) that prototype entries call once per mount. In jsdom
 * `getContext` returns null for GL contexts, so tests naturally land on the
 * fallback tier unless they mock this module.
 */

export function probeWebGLSupport(createCanvas: () => HTMLCanvasElement): boolean {
  try {
    const canvas = createCanvas();
    return canvas.getContext('webgl2') !== null || canvas.getContext('webgl') !== null;
  } catch {
    // Some hardened/headless environments throw from getContext outright.
    return false;
  }
}

export function detectWebGLSupport(): boolean {
  if (typeof document === 'undefined') return false;
  return probeWebGLSupport(() => document.createElement('canvas'));
}
