import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { installStaleChunkReload } from '../../lib/staleChunkReload';

function fakeWindow(storage: Pick<Storage, 'getItem' | 'setItem'>) {
  const reload = vi.fn();
  const target = Object.assign(new EventTarget(), {
    sessionStorage: storage,
    location: { reload },
  }) as unknown as Window;
  return { target, reload };
}

function memoryStorage(): Pick<Storage, 'getItem' | 'setItem'> {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      values.set(key, value);
    },
  };
}

function failChunkLoad(target: Window) {
  target.dispatchEvent(new Event('vite:preloadError', { cancelable: true }));
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-11-12T12:00:00Z'));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('installStaleChunkReload', () => {
  it('reloads the page when a lazy chunk from an older deploy fails to load', () => {
    const { target, reload } = fakeWindow(memoryStorage());
    installStaleChunkReload(target);
    failChunkLoad(target);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('does not reload again within the cooldown, so a real outage cannot loop', () => {
    const { target, reload } = fakeWindow(memoryStorage());
    installStaleChunkReload(target);
    failChunkLoad(target);
    vi.advanceTimersByTime(5_000);
    failChunkLoad(target);
    expect(reload).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(6_000);
    failChunkLoad(target);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it('leaves the error to the error boundary when sessionStorage is unavailable', () => {
    const { target, reload } = fakeWindow({
      getItem: () => {
        throw new DOMException('blocked', 'SecurityError');
      },
      setItem: () => {},
    });
    installStaleChunkReload(target);
    failChunkLoad(target);
    expect(reload).not.toHaveBeenCalled();
  });

  it('stops listening once uninstalled', () => {
    const { target, reload } = fakeWindow(memoryStorage());
    const uninstall = installStaleChunkReload(target);
    uninstall();
    failChunkLoad(target);
    expect(reload).not.toHaveBeenCalled();
  });
});
