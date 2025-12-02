import { useEffect, useRef } from 'react';

/**
 * Options for the useInfiniteScroll hook
 */
export interface UseInfiniteScrollOptions {
  /**
   * Whether there are more items to load
   */
  hasMore: boolean;

  /**
   * Whether a load operation is currently in progress
   */
  isLoadingMore: boolean;

  /**
   * Callback to trigger when sentinel becomes visible
   */
  onLoadMore: () => void;

  /**
   * Root margin for IntersectionObserver (default: '200px')
   * Positive values trigger loading before element becomes visible
   */
  rootMargin?: string;

  /**
   * Threshold for IntersectionObserver (default: 0.1)
   * 0.1 = trigger when 10% of element is visible
   */
  threshold?: number;
}

/**
 * Return value from useInfiniteScroll hook
 */
export interface UseInfiniteScrollReturn {
  /**
   * Ref to attach to the sentinel element
   */
  sentinelRef: React.RefObject<HTMLDivElement | null>;
}

/**
 * Custom hook for implementing infinite scrolling using IntersectionObserver
 *
 * This hook manages an IntersectionObserver that watches a sentinel element.
 * When the sentinel becomes visible (with optional prefetch margin), it triggers
 * the onLoadMore callback to load the next batch of items.
 *
 * @param options - Configuration options for infinite scrolling
 * @returns Object containing sentinelRef to attach to the sentinel element
 *
 * @example
 * ```tsx
 * const { sentinelRef } = useInfiniteScroll({
 *   hasMore: displayedCount < totalCount,
 *   isLoadingMore,
 *   onLoadMore: () => loadNextBatch(),
 *   rootMargin: '200px',
 *   threshold: 0.1,
 * });
 *
 * return (
 *   <>
 *     {items.map(item => <Item key={item.id} {...item} />)}
 *     {hasMore && <div ref={sentinelRef} />}
 *   </>
 * );
 * ```
 */
export function useInfiniteScroll(options: UseInfiniteScrollOptions): UseInfiniteScrollReturn {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const { hasMore, isLoadingMore, onLoadMore, rootMargin = '200px', threshold = 0.1 } = options;

  useEffect(() => {
    const sentinel = sentinelRef.current;

    // Don't observe if:
    // - No sentinel element exists
    // - No more items to load
    // - Currently loading
    if (!sentinel || !hasMore || isLoadingMore) {
      return;
    }

    // Create IntersectionObserver to watch sentinel
    const observer = new IntersectionObserver(
      (entries) => {
        // entries[0] is our sentinel element
        if (entries[0].isIntersecting) {
          onLoadMore();
        }
      },
      {
        rootMargin,
        threshold,
      }
    );

    // Start observing
    observer.observe(sentinel);

    // Cleanup: disconnect observer when component unmounts or dependencies change
    return () => {
      observer.disconnect();
    };
  }, [hasMore, isLoadingMore, onLoadMore, rootMargin, threshold]);

  return { sentinelRef };
}
