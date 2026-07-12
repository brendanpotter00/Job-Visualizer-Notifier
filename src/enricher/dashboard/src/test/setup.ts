// Registers @testing-library/jest-dom matchers (toBeInTheDocument, …) on
// Vitest's expect, and its type augmentation applies project-wide via tsc.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// With globals:false RTL can't self-register its cleanup, so unmount + reset the
// DOM after every test ourselves (else renders leak across tests in a file).
afterEach(cleanup);

// jsdom omits a couple of APIs that MUI touches: x-data-grid observes element
// size (ResizeObserver) and useMediaQuery reads matchMedia. Stub both so panel
// renders don't throw. Direct assignments (not vi.stubGlobal) so they persist
// for the whole file regardless of unstubGlobals.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver =
  globalThis.ResizeObserver ?? (ResizeObserverStub as unknown as typeof ResizeObserver);

if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
