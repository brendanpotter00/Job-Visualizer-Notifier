import { Box, Divider, Grid, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';
import { SectionIntro } from './SectionIntro';

const HEADING_ID = 'landing-how-it-works-heading';

interface HowItWorksSectionProps {
  content: LandingContent;
}

/**
 * "How it works" + the apply-early beat, merged into ONE quiet section.
 *
 * This is the page's tame stretch. The hero is a physics simulation and the
 * triptych above flips cards on a timer, so everything here is deliberately
 * static text: three numbered steps on one horizontal line (stacking below
 * `sm`), then a single rule and one emphasized sentence. No cards, no borders
 * around steps, no icons, no motion.
 *
 * Step order is the mechanism in causal order (watch, label, filter) and it
 * ends on the reader's own action. The middle step is where AI-powered labeling
 * enters the landing page: as the reason filters are trustworthy, never as an
 * "AI" badge.
 *
 * The closer is the one emotional line on the page, the why behind all of the
 * above. It wears the quotable treatment (hairline rule + `quotableFontSize`)
 * because it is written to be lifted whole.
 */
export function HowItWorksSection({ content }: HowItWorksSectionProps) {
  const { eyebrow, heading, steps, closer } = content.howItWorks;

  return (
    <Box component="section" aria-labelledby={HEADING_ID} data-testid="how-it-works">
      <SectionIntro eyebrow={eyebrow} heading={heading} headingId={HEADING_ID} />

      <Grid container spacing={RESPONSIVE.landingProto.stepsGridSpacing}>
        {steps.map((step, index) => (
          // `minWidth: 0` so a long line wraps instead of widening the track
          // past the viewport at 390px.
          <Grid key={step.id} size={{ xs: 12, sm: 4 }} sx={{ minWidth: 0 }}>
            <Typography
              component="p"
              variant="caption"
              // Ordinal, not content: derived from position so reordering the
              // steps in content.ts can never leave a stale number behind.
              sx={{
                display: 'block',
                color: 'text.disabled',
                fontVariantNumeric: 'tabular-nums',
                letterSpacing: '0.08em',
                mb: 1.5,
              }}
            >
              {String(index + 1).padStart(2, '0')}
            </Typography>
            <Typography
              component="h3"
              sx={{
                fontSize: RESPONSIVE.landingProto.blockTitleFontSize,
                fontWeight: 500,
                mb: 1,
              }}
            >
              {step.label}
            </Typography>
            <Typography
              variant="body2"
              sx={{
                color: 'text.secondary',
                fontSize: RESPONSIVE.landingProto.bodyFontSize,
                lineHeight: 1.7,
              }}
            >
              {step.line}
            </Typography>
          </Grid>
        ))}
      </Grid>

      {/* Capped well short of the lg container so it reads as a pull-quote at
          a comfortable measure (~60ch) rather than a full-width paragraph; the
          single hairline above it is the section's only rule. */}
      <Box sx={{ mt: RESPONSIVE.landingProto.sectionBlockGapY, maxWidth: 620 }}>
        <Divider sx={{ mb: 4 }} />
        <Typography
          sx={{
            fontSize: RESPONSIVE.landingProto.quotableFontSize,
            fontWeight: 500,
            lineHeight: 1.6,
          }}
        >
          {closer.line}
        </Typography>
      </Box>
    </Box>
  );
}

export default HowItWorksSection;
