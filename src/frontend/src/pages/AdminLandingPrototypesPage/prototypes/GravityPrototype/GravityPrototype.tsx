import { lazy, Suspense, useMemo } from 'react';
import { Box, Container } from '@mui/material';
import { RESPONSIVE } from '../../../../config/responsive';
import { COMPANIES } from '../../../../config/companies';
import type { LandingPrototypeProps } from '../../types';
import { LandingHeader } from '../../sections/LandingHeader';
import { HeroCopy } from '../../sections/HeroCopy';
import { CTAButtons } from '../../sections/CTAButtons';
import { FreshJobsTriptych } from '../../sections/FreshJobsTriptych';
import { HeroTrendline } from '../../sections/HeroTrendline';
import { HowItWorksSection } from '../../sections/HowItWorksSection';
import { CompanyCategoriesSection } from '../../sections/CompanyCategoriesSection';
import { FeatureMatrixSection } from '../../sections/FeatureMatrixSection';
import { FAQSection } from '../../sections/FAQSection';
import { FooterLite } from '../../sections/FooterLite';
import { DESKTOP_BODY_COUNT } from '../shared3d/experienceTier';
import { useExperienceTier } from '../shared3d/useExperienceTier';
import { selectLogoRoster } from '../shared3d/logoRoster';
import { LogoGridFallback } from '../shared3d/LogoGridFallback';

/**
 * Nested lazy INSIDE the already-lazy prototype entry: the tier is resolved
 * before this component ever mounts, so fallback-tier visitors (reduced
 * motion / no WebGL) never download the three/rapier scene chunk at all.
 */
const GravityScene = lazy(() => import('./GravityScene'));

/** Arbitrary, stable seed so every visit piles up the same logos. */
const ROSTER_SEED = 20260809;

/**
 * "Gravity" — falling company logos with physics. The hero copy/CTA live on a
 * DOM layer the canvas can never occlude (canvas is aria-hidden and absolutely
 * positioned behind; the copy layer is pointer-events transparent except on
 * CTAs so the canvas still receives pointer moves). The settled pile doubles
 * as the logo wall — deliberately no LogoWall section below. Reduced-motion /
 * no-WebGL tiers render the pre-settled LogoGridFallback grid instead.
 *
 * Carries hero variant B (anti-noise): the pile of company logos already says
 * "straight from the source", so the headline spends its words on the reposts
 * problem instead.
 */
export function GravityPrototype({ content, jobs, now }: LandingPrototypeProps) {
  const tier = useExperienceTier();
  const roster = useMemo(
    () => selectLogoRoster(COMPANIES, tier.bodyCount, ROSTER_SEED),
    [tier.bodyCount]
  );

  return (
    <Box>
      {/* Above the hero, not inside it: the hero wrapper clips (`overflow:
          hidden`) for the canvas, and a sticky child of a clipped box scrolls
          away with that box. Keeping the bar outside also starts the canvas
          below it, so falling tiles never cross the links. */}
      <LandingHeader content={content} />
      {/* Hero region: DOM copy over the physics canvas. */}
      <Box sx={{ position: 'relative', overflow: 'hidden' }}>
        {/* Furthest-back layer: faint mock posting-cadence line. The canvas
            clears to transparent, so the line reads through it while tiles
            still paint on top. */}
        <HeroTrendline />
        {tier.tier === 'full' && (
          <Box aria-hidden sx={{ position: 'absolute', inset: 0 }}>
            <Suspense fallback={null}>
              <GravityScene
                roster={roster}
                maxDpr={tier.maxDpr}
                showShadows={tier.bodyCount === DESKTOP_BODY_COUNT}
              />
            </Suspense>
          </Box>
        )}
        <Container
          maxWidth="lg"
          sx={{
            position: 'relative',
            py: RESPONSIVE.landingProto.heroPaddingY,
            // The copy floats over the canvas; only interactive elements
            // capture the pointer so the physics keeps feeling the cursor.
            pointerEvents: 'none',
          }}
        >
          <HeroCopy content={content} variant="antiNoise" />
          <Box sx={{ mt: 4, pointerEvents: 'auto' }}>
            <CTAButtons ctas={content.ctas} showSecondary />
          </Box>
          {tier.tier === 'fallback' ? (
            <Box sx={{ mt: 6, pointerEvents: 'auto' }}>
              <LogoGridFallback roster={roster} />
            </Box>
          ) : (
            // Reserved vertical room where the pile settles in the canvas.
            <Box sx={{ mt: 6, height: RESPONSIVE.landingProto.heroSceneHeight }} />
          )}
        </Container>
      </Box>

      {/* Vertical rhythm: every section wrapper carries the same `py`, so the
          air BETWEEN two sections is double the token (80px on a phone, 160px
          on desktop). That doubling is the point — the text sections below are
          quiet blocks that need to float in their own space rather than stack. */}
      <Container maxWidth="lg">
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <FreshJobsTriptych jobs={jobs} now={now} />
        </Box>
        {/* Two flat text sections bracket the categories grid: after the
            flipping triptych the eye needs somewhere still to land, and again
            before the FAQ. Both are static by design. */}
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <HowItWorksSection content={content} />
        </Box>
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <CompanyCategoriesSection />
        </Box>
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <FeatureMatrixSection content={content} />
        </Box>
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <FAQSection content={content} />
        </Box>
        <FooterLite content={content} />
      </Container>
    </Box>
  );
}

export default GravityPrototype;
