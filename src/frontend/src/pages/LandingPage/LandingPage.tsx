import { Box } from '@mui/material';
import { LANDING_CONTENT } from './content';
import { LandingSeo } from './seo/LandingSeo';
import { GravityPrototype } from './prototypes/GravityPrototype/GravityPrototype';

/**
 * The marketing landing page (docs/implementations/landingPagePrototypes/PLAN.md).
 * Mounted OUTSIDE RootLayout so it renders full-bleed like a real landing page
 * rather than inside the app's drawer/appbar chrome.
 *
 * This was a four-tab prototype workspace until the 2026-09-03 consolidation;
 * the tab strip, the registry and the three losing designs are gone, and what
 * is left is a shell whose whole job is the document
 * head (`LandingSeo`, rendered here so the title, canonical and JSON-LD exist
 * before the lazy scene loads).
 *
 * The 100dvh column with the inner scroller is load-bearing, not leftover
 * framing: `LandingHeader` is `position: sticky` against the nearest scrolling
 * ancestor, and its scroll-state IntersectionObserver deliberately passes no
 * `root` so it is clipped by that same overflow ancestor. Flattening this to a
 * document-level scroll is a real change to how the header behaves, so it is
 * left for a later iteration pass rather than smuggled into a restyle.
 */
export function LandingPage() {
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
      <LandingSeo content={LANDING_CONTENT} />
      <Box sx={{ flex: 1, overflowY: 'auto' }}>
        <GravityPrototype content={LANDING_CONTENT} />
      </Box>
    </Box>
  );
}
