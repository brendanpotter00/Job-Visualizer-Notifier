import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useAfterFirstPaint } from '../../../../pages/LandingPage/prototypes/shared3d/useAfterFirstPaint';

const STUBBED = [
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'requestIdleCallback',
  'cancelIdleCallback',
] as const;

let originals: Map<string, PropertyDescriptor | undefined>;
let frames: Map<number, FrameRequestCallback>;
let idles: Map<number, () => void>;
let nextId: number;

function setOnWindow(name: (typeof STUBBED)[number], value: unknown) {
  Object.defineProperty(window, name, { configurable: true, writable: true, value });
}

function stubScheduling({ idle }: { idle: boolean }) {
  setOnWindow('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = nextId++;
    frames.set(id, callback);
    return id;
  });
  setOnWindow('cancelAnimationFrame', (id: number) => frames.delete(id));
  setOnWindow(
    'requestIdleCallback',
    idle
      ? (callback: () => void) => {
          const id = nextId++;
          idles.set(id, callback);
          return id;
        }
      : undefined
  );
  setOnWindow('cancelIdleCallback', idle ? (id: number) => idles.delete(id) : undefined);
}

function paintFrame() {
  const pending = [...frames.values()];
  frames.clear();
  act(() => pending.forEach((callback) => callback(0)));
}

function goIdle() {
  const pending = [...idles.values()];
  idles.clear();
  act(() => pending.forEach((callback) => callback()));
}

function runTasks() {
  act(() => vi.runOnlyPendingTimers());
}

beforeEach(() => {
  originals = new Map(STUBBED.map((name) => [name, Object.getOwnPropertyDescriptor(window, name)]));
  frames = new Map();
  idles = new Map();
  nextId = 1;
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
  vi.useRealTimers();
  for (const [name, descriptor] of originals) {
    if (descriptor) Object.defineProperty(window, name, descriptor);
    else Reflect.deleteProperty(window, name);
  }
});

describe('useAfterFirstPaint', () => {
  it('turns true only after a frame has painted and the browser has gone idle', () => {
    stubScheduling({ idle: true });
    const { result } = renderHook(() => useAfterFirstPaint());
    expect(result.current).toBe(false);

    paintFrame();
    runTasks();
    expect(result.current).toBe(false);
    expect(idles.size).toBe(1);

    goIdle();
    expect(result.current).toBe(true);
  });

  it('falls back to frame + task where requestIdleCallback does not exist', () => {
    stubScheduling({ idle: false });
    const { result } = renderHook(() => useAfterFirstPaint());

    paintFrame();
    expect(result.current).toBe(false);
    runTasks();
    expect(result.current).toBe(true);
  });

  it('cancels the pending frame when unmounted before the first paint', () => {
    stubScheduling({ idle: true });
    const { unmount } = renderHook(() => useAfterFirstPaint());
    expect(frames.size).toBe(1);
    unmount();
    expect(frames.size).toBe(0);
  });

  it('cancels the pending idle callback when unmounted while waiting for idle', () => {
    stubScheduling({ idle: true });
    const { unmount } = renderHook(() => useAfterFirstPaint());
    paintFrame();
    runTasks();
    expect(idles.size).toBe(1);
    unmount();
    expect(idles.size).toBe(0);
  });
});
