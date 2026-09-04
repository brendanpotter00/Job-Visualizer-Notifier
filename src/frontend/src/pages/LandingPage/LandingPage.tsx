import { lazy, Suspense } from 'react';
import { Box } from '@mui/material';
import { useSearchParams } from 'react-router-dom';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { LANDING_CONTENT } from './content';
import { MOCK_JOBS, MOCK_JOBS_SPARSE, MOCK_NOW } from './mockData';

/**
 * The landing scene, still behind React.lazy. The boundary is no longer about
 * picking one of four designs — it is the ONLY thing keeping three/rapier out
 * of the main bundle, so it must not be flattened into a static import even
 * though there is now exactly one thing behind it. (The scene itself is lazy
 * again one level down, so a reduced-motion visitor never fetches it at all.)
 * React.lazy needs a default export, which is why GravityPrototype exports both
 * named and default.
 */
const GravityPrototype = lazy(() => import('./prototypes/GravityPrototype/GravityPrototype'));

/**
 * The marketing landing page (docs/implementations/landingPagePrototypes/PLAN.md).
 * Mounted OUTSIDE RootLayout so it renders full-bleed like a real landing page
 * rather than inside the app's drawer/appbar chrome.
 *
 * This was a four-tab prototype workspace until the 2026-09-03 consolidation;
 * the tab strip, the registry and the three losing designs are gone, and what
 * is left is a shell whose whole job is the lazy boundary and the fixture
 * toggle.
 *
 * URL contract: `?data=sparse` swaps in the weekend-reality fixture. It
 * survived the consolidation because the sparse case is the one that breaks
 * layouts, and flipping it by URL beats editing mock data to see it.
 *
 * The 100dvh column with the inner scroller is load-bearing, not leftover
 * framing: `LandingHeader` is `position: sticky` against the nearest scrolling
 * ancestor, and its scroll-state IntersectionObserver deliberately passes no
 * `root` so it is clipped by that same overflow ancestor. Flattening this to a
 * document-level scroll is a real change to how the header behaves, so it is
 * left for the post-merge iteration pass rather than smuggled into a deletion.
 */
export function LandingPage() {
  const [searchParams] = useSearchParams();
  const sparse = searchParams.get('data') === 'sparse';

  return (
    <Box
      sx={{
        height: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        bgcolor: 'background.default',
      }}
    >
      <Box sx={{ flex: 1, overflowY: 'auto' }}>
        <Suspense fallback={<LoadingState size={60} minHeight={400} caption="Loading…" />}>
          <GravityPrototype
            content={LANDING_CONTENT}
            jobs={sparse ? MOCK_JOBS_SPARSE : MOCK_JOBS}
            sparse={sparse}
            now={MOCK_NOW}
          />
        </Suspense>
      </Box>
    </Box>
  );
}

export default LandingPage;
