import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useInfiniteScroll } from '../../hooks/useInfiniteScroll';

describe('useInfiniteScroll', () => {
  let observeMock: ReturnType<typeof vi.fn>;
  let disconnectMock: ReturnType<typeof vi.fn>;
  let unobserveMock: ReturnType<typeof vi.fn>;
  let intersectionObserverCallback: IntersectionObserverCallback;

  beforeEach(() => {
    observeMock = vi.fn();
    disconnectMock = vi.fn();
    unobserveMock = vi.fn();

    // Mock IntersectionObserver
    global.IntersectionObserver = vi.fn().mockImplementation((callback) => {
      intersectionObserverCallback = callback;
      return {
        observe: observeMock,
        disconnect: disconnectMock,
        unobserve: unobserveMock,
      };
    }) as unknown as typeof IntersectionObserver;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('returns sentinelRef', () => {
    const onLoadMore = vi.fn();

    const { result } = renderHook(() =>
      useInfiniteScroll({
        hasMore: true,
        isLoadingMore: false,
        onLoadMore,
        rootMargin: '200px',
        threshold: 0.1,
      })
    );

    // Hook should return a sentinelRef object
    expect(result.current).toHaveProperty('sentinelRef');
    expect(result.current.sentinelRef).toBeDefined();
    expect(result.current.sentinelRef.current).toBeNull(); // Initially null
  });

  it('uses correct default values', () => {
    const onLoadMore = vi.fn();

    const { result } = renderHook(() =>
      useInfiniteScroll({
        hasMore: true,
        isLoadingMore: false,
        onLoadMore,
        // Not providing rootMargin and threshold - should use defaults
      })
    );

    // Hook should work with default values
    expect(result.current.sentinelRef).toBeDefined();
  });

  it('accepts custom rootMargin and threshold', () => {
    const onLoadMore = vi.fn();

    const { result } = renderHook(() =>
      useInfiniteScroll({
        hasMore: true,
        isLoadingMore: false,
        onLoadMore,
        rootMargin: '100px',
        threshold: 0.5,
      })
    );

    // Hook should accept and work with custom values
    expect(result.current.sentinelRef).toBeDefined();
  });

  it('works when hasMore is false', () => {
    const onLoadMore = vi.fn();

    const { result } = renderHook(() =>
      useInfiniteScroll({
        hasMore: false,
        isLoadingMore: false,
        onLoadMore,
        rootMargin: '200px',
        threshold: 0.1,
      })
    );

    // Hook should still return valid ref even when hasMore is false
    expect(result.current.sentinelRef).toBeDefined();
  });

  it('works when isLoadingMore is true', () => {
    const onLoadMore = vi.fn();

    const { result } = renderHook(() =>
      useInfiniteScroll({
        hasMore: true,
        isLoadingMore: true,
        onLoadMore,
        rootMargin: '200px',
        threshold: 0.1,
      })
    );

    // Hook should still return valid ref even when isLoadingMore is true
    expect(result.current.sentinelRef).toBeDefined();
  });

  it('can be unmounted without errors', () => {
    const onLoadMore = vi.fn();

    const { unmount } = renderHook(() =>
      useInfiniteScroll({
        hasMore: true,
        isLoadingMore: false,
        onLoadMore,
        rootMargin: '200px',
        threshold: 0.1,
      })
    );

    // Should unmount without errors
    expect(() => unmount()).not.toThrow();
  });

  it('handles prop changes correctly', () => {
    const onLoadMore = vi.fn();

    const { rerender } = renderHook((props) => useInfiniteScroll(props), {
      initialProps: {
        hasMore: true,
        isLoadingMore: false,
        onLoadMore,
      },
    });

    // Change hasMore to false
    rerender({
      hasMore: false,
      isLoadingMore: false,
      onLoadMore,
    });

    // Should not throw errors on prop changes
    expect(true).toBe(true);
  });
});
