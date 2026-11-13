import { lazy, Suspense, useMemo, type ReactNode } from 'react';
import { Box, Container } from '@mui/material';
import { RESPONSIVE } from '../../../../config/responsive';
import { COMPANIES } from '../../../../config/companies';
import type { LandingPrototypeProps } from '../../types';
import { LandingHeader } from '../../sections/LandingHeader';
import { HeroCopy } from '../../sections/HeroCopy';
import { heroRiseIn, HERO_RISE_STAGGER_MS } from '../../sections/heroRiseIn';
import { CTAButtons } from '../../sections/CTAButtons';
import { FreshJobsTriptych } from '../../sections/FreshJobsTriptych';
import { LinkedInComparisonSection } from '../../sections/LinkedInComparisonSection';
import { CompanyCategoriesSection } from '../../sections/CompanyCategoriesSection';
import { FeatureMatrixSection } from '../../sections/FeatureMatrixSection';
import { FAQSection } from '../../sections/FAQSection';
import { ClosingCtaSection } from '../../sections/ClosingCtaSection';
import { useExperienceTier } from '../shared3d/useExperienceTier';
import { useAfterFirstPaint } from '../shared3d/useAfterFirstPaint';
import { selectLogoRoster } from '../shared3d/logoRoster';
import { LogoGridFallback } from '../shared3d/LogoGridFallback';

/**
 * Lazy: the tier is resolved
 * before this component ever mounts, so fallback-tier visitors (reduced
 * motion / no WebGL) never download the three/rapier scene chunk at all.
 */
const GravityScene = lazy(() => import('./GravityScene'));

/** Arbitrary, stable seed so every visit piles up the same logos. */
const ROSTER_SEED = 20260809;

const HERO_HEADING_ID = 'landing-hero-heading';

function SectionBand({ children }: { children: ReactNode }) {
  return <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>{children}</Box>;
}

/**
 * "Gravity" — falling company logos with physics. The hero copy/CTA live on a
 * DOM layer the canvas can never occlude (canvas is aria-hidden and absolutely
 * positioned behind; the copy layer is pointer-events transparent except on
 * CTAs so the canvas still receives pointer moves). The settled pile IS the
 * logo wall — there is deliberately no second DOM logo section below it.
 * Phones get the same pile with the camera pulled back (`tier.compact`), so the
 * tiles render at the static grid's size and settle under the CTAs.
 * Reduced-motion / no-WebGL tiers render the pre-settled LogoGridFallback grid
 * instead.
 *
 * Page order below the hero: live proof (three real cards) → the LinkedIn
 * comparison → the curated companies → the feature matrix → FAQ → the
 * closing line. (The "how it works" steps and the "by the numbers" proof
 * strip that sat between the comparison and the companies were both cut on
 * 2026-11-12, owner-directed.) Every section opens with the same
 * short heading (`SectionIntro`), and the one decorative hero layer that
 * used to sit behind the copy (a mock posting-cadence line) is gone: the pile
 * is the hero's only picture.
 *
 * This is the landing page's whole body — it kept the `GravityPrototype` name
 * and its `prototypes/` home through the 2026-09-03 consolidation because the
 * name still describes what it is (the gravity scene), and renaming it would
 * have churned every import for no reader gain.
 */
export function GravityPrototype({ content, jobs, now }: LandingPrototypeProps) {
  const tier = useExperienceTier();
  const sceneReady = useAfterFirstPaint();
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
      <Box component="main">
        <Box
          component="section"
          aria-labelledby={HERO_HEADING_ID}
          sx={{ position: 'relative', overflow: 'hidden' }}
        >
          {tier.tier === 'full' && sceneReady && (
            <Box aria-hidden sx={{ position: 'absolute', inset: 0 }}>
              <Suspense fallback={null}>
                <GravityScene
                  key={tier.compact ? 'compact' : 'default'}
                  roster={roster}
                  maxDpr={tier.maxDpr}
                  compact={tier.compact}
                />
              </Suspense>
            </Box>
          )}
          <Container
            maxWidth="lg"
            sx={{
              position: 'relative',
              py: RESPONSIVE.landingProto.heroPaddingY,
              pointerEvents: 'none',
            }}
          >
            <HeroCopy hero={content.hero} headingId={HERO_HEADING_ID} />
            <Box sx={{ mt: 5, pointerEvents: 'auto', ...heroRiseIn(HERO_RISE_STAGGER_MS) }}>
              <CTAButtons ctas={content.ctas} showSecondary />
            </Box>
            {tier.tier === 'fallback' ? (
              <Box sx={{ mt: 6, pointerEvents: 'auto' }}>
                <LogoGridFallback roster={roster} />
              </Box>
            ) : (
              <Box sx={{ mt: 6, height: RESPONSIVE.landingProto.heroSceneHeight }} />
            )}
          </Container>
        </Box>

        <Container maxWidth="lg">
          <SectionBand>
            <FreshJobsTriptych jobs={jobs} now={now} intro={content.freshJobs} />
          </SectionBand>
          <SectionBand>
            <LinkedInComparisonSection content={content} />
          </SectionBand>
          <SectionBand>
            <CompanyCategoriesSection content={content} />
          </SectionBand>
          <SectionBand>
            <FeatureMatrixSection content={content} />
          </SectionBand>
          <SectionBand>
            <FAQSection content={content} />
          </SectionBand>
          <SectionBand>
            <ClosingCtaSection content={content} />
          </SectionBand>
        </Container>
      </Box>
    </Box>
  );
}
