import { useState, useEffect } from 'react';
import { Fab, Zoom } from '@mui/material';
import { KeyboardArrowUp } from '@mui/icons-material';
import { INFINITE_SCROLL_CONFIG } from '../../constants/infiniteScrollConstants';
import { ARIA_LABELS } from '../../constants/messageConstants';

/**
 * Floating Action Button that appears after scrolling down
 * Scrolls smoothly back to top when clicked
 */
export function BackToTopButton() {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    let timeoutId: NodeJS.Timeout;

    const handleScroll = () => {
      // Debounce scroll events
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        const shouldShow = window.scrollY > INFINITE_SCROLL_CONFIG.BACK_TO_TOP_THRESHOLD;
        setIsVisible(shouldShow);
      }, INFINITE_SCROLL_CONFIG.SCROLL_DEBOUNCE_MS);
    };

    // Add scroll listener
    window.addEventListener('scroll', handleScroll, { passive: true });

    // Check initial scroll position
    handleScroll();

    // Cleanup
    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener('scroll', handleScroll);
    };
  }, []);

  const scrollToTop = () => {
    window.scrollTo({
      top: 0,
      behavior: 'smooth',
    });
  };

  return (
    <Zoom in={isVisible}>
      <Fab
        color="primary"
        size="medium"
        aria-label={ARIA_LABELS.SCROLL_TO_TOP}
        onClick={scrollToTop}
        sx={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          zIndex: 1000,
        }}
      >
        <KeyboardArrowUp />
      </Fab>
    </Zoom>
  );
}
