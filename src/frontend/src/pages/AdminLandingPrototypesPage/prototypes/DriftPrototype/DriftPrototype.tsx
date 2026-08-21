import { lazy, Suspense, useMemo } from 'react';
import { Box, Container, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../../config/responsive';
import type { LandingPrototypeProps } from '../../types';
import { LandingHeader } from '../../sections/LandingHeader';
import { CTAButtons } from '../../sections/CTAButtons';
import { LogoWall } from '../../sections/LogoWall';
import { FAQSection } from '../../sections/FAQSection';
import { FooterLite } from '../../sections/FooterLite';
import { DESKTOP_BODY_COUNT } from '../shared3d/experienceTier';
import { useExperienceTier } from '../shared3d/useExperienceTier';
import { buildParticlesConfig, countJobsPostedToday } from './particlesConfig';

/**
 * Nested lazy INSIDE the already-lazy prototype entry: the tier is resolved
 * before this component ever mounts, so fallback-tier visitors (reduced
 * motion / no WebGL) never download the three scene chunk at all.
 */
const DriftScene = lazy(() => import('./DriftScene'));

/**
 * Static CSS stand-in for the particle field: a barely-there dot lattice via
 * two layered radial gradients. Same ≤10% visual weight, zero JS, zero motion.
 */
const DOT_BACKDROP_SX = {
  position: 'absolute',
  inset: 0,
  backgroundImage:
    'radial-gradient(rgba(120, 120, 120, 0.22) 1.5px, transparent 1.5px), ' +
    'radial-gradient(rgba(120, 120, 120, 0.14) 1px, transparent 1px)',
  backgroundSize: '56px 56px, 34px 34px',
  backgroundPosition: '0 0, 17px 23px',
} as const;

/**
 * "Drift" — the subtle-particles take. The three.js field mounts behind the
 * hero copy (canvas aria-hidden, absolutely positioned) and encodes data:
 * every dot in the near layer is a job posted in the last 24h, with the claim
 * kept in real DOM text. Below the hero this stays Signal's restrained
 * skeleton so Signal↔Drift remains an honest A/B pair. Reduced-motion /
 * no-WebGL tiers get a static CSS gradient-dot backdrop instead.
 */
export function DriftPrototype({ content, jobs, now }: LandingPrototypeProps) {
  const tier = useExperienceTier();
  const config = useMemo(
    () =>
      buildParticlesConfig({
        jobsPostedToday: countJobsPostedToday(jobs, now),
        constrained: tier.bodyCount < DESKTOP_BODY_COUNT,
      }),
    [jobs, now, tier.bodyCount]
  );

  return (
    <Box>
      <LandingHeader content={content} />
      {/* Hero: terse noun phrase over the particle field. */}
      <Box sx={{ position: 'relative', overflow: 'hidden' }}>
        {tier.tier === 'full' ? (
          <Box aria-hidden sx={{ position: 'absolute', inset: 0 }}>
            <Suspense fallback={null}>
              <DriftScene config={config} maxDpr={tier.maxDpr} />
            </Suspense>
          </Box>
        ) : (
          <Box aria-hidden data-testid="drift-dot-backdrop" sx={DOT_BACKDROP_SX} />
        )}
        <Container
          maxWidth="lg"
          sx={{ position: 'relative', py: RESPONSIVE.landingProto.heroPaddingY }}
        >
          <Box sx={{ textAlign: 'center', maxWidth: 780, mx: 'auto' }}>
            <Typography
              variant="h1"
              sx={{
                fontSize: RESPONSIVE.landingProto.heroHeadlineFontSize,
                fontWeight: 600,
                letterSpacing: '-0.02em',
                lineHeight: 1.1,
              }}
            >
              Jobs at the source.
            </Typography>
            <Typography
              sx={{
                fontSize: RESPONSIVE.landingProto.heroSubFontSize,
                color: 'text.secondary',
                mt: 2,
              }}
            >
              {content.heroVariants.source.subheadline}
            </Typography>
          </Box>
          <Box sx={{ mt: 4 }}>
            <CTAButtons ctas={content.ctas} showSecondary />
          </Box>
          <Typography
            variant="caption"
            sx={{ display: 'block', textAlign: 'center', color: 'text.disabled', mt: 6 }}
          >
            Every dot is a job posted today.
          </Typography>
        </Container>
      </Box>

      <Container maxWidth="lg">
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <LogoWall rows={1} perRow={24} />
        </Box>
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <FAQSection content={content} />
        </Box>
        <FooterLite content={content} />
      </Container>
    </Box>
  );
}

export default DriftPrototype;
