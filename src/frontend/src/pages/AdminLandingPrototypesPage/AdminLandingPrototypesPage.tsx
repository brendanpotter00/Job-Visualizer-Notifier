import { Suspense } from 'react';
import { Box } from '@mui/material';
import { useSearchParams } from 'react-router-dom';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { LANDING_CONTENT } from './content';
import { MOCK_JOBS, MOCK_JOBS_SPARSE, MOCK_NOW, MOCK_STATS } from './mockData';
import { PrototypeTabStrip } from './PrototypeTabStrip';
import { PROTOTYPES } from './prototypes/registry';
import { isPrototypeId, PROTOTYPE_IDS, type PrototypeId } from './types';

/**
 * Admin-gated workspace for comparing landing-page prototypes side by side
 * (docs/implementations/landingPagePrototypes/PLAN.md). Mounted OUTSIDE
 * RootLayout so each prototype previews full-bleed like a real landing page.
 *
 * URL contract: `?proto=<id>` selects the tab (deep-linkable; invalid values
 * fall back to the first tab) and `?data=sparse` swaps in the weekend-reality
 * fixture. Only the ACTIVE prototype mounts — a hard invariant once the 3D
 * tabs land (exactly one WebGL canvas may exist at a time).
 */
export function AdminLandingPrototypesPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const protoParam = searchParams.get('proto');
  const activeId: PrototypeId = isPrototypeId(protoParam) ? protoParam : PROTOTYPE_IDS[0];
  const sparse = searchParams.get('data') === 'sparse';

  const active = PROTOTYPES.find((proto) => proto.id === activeId) ?? PROTOTYPES[0];
  const ActiveComponent = active.Component;

  const handleTabChange = (id: PrototypeId) => {
    // Functional update preserves `?data=`; replace avoids back-button spam
    // while flipping between tabs.
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('proto', id);
        return next;
      },
      { replace: true }
    );
  };

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
      <PrototypeTabStrip activeId={activeId} onChange={handleTabChange} />
      {/* Keyed by tab so switching resets scroll to the top of the prototype. */}
      <Box key={activeId} sx={{ flex: 1, overflowY: 'auto' }}>
        <Suspense
          fallback={<LoadingState size={60} minHeight={400} caption="Loading prototype…" />}
        >
          <ActiveComponent
            content={LANDING_CONTENT}
            jobs={sparse ? MOCK_JOBS_SPARSE : MOCK_JOBS}
            stats={MOCK_STATS}
            sparse={sparse}
            now={MOCK_NOW}
          />
        </Suspense>
      </Box>
    </Box>
  );
}
