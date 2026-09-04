import { Box, Divider, Grid, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';

interface HowItWorksSectionProps {
  content: LandingContent;
}

/**
 * "How it works" + the apply-early beat, merged into ONE quiet section.
 *
 * This is the page's tame stretch. The Gravity hero is a physics simulation and
 * the triptych above flips cards on a timer, so everything here is deliberately
 * static text: three numbered steps on one horizontal line (stacking below
 * `sm`), then a single rule and one emphasized sentence pair. No cards, no
 * borders around steps, no icons, no motion.
 *
 * Step order is the mechanism in causal order (monitor, label, filter) and it
 * ends on the reader's own action. The middle step is where AI-powered labeling
 * enters the landing page: as the reason filters are trustworthy, never as an
 * "AI" badge. A fourth "timestamp first sight" step was dropped as redundant
 * (2026-08-09) because the hero already owns the freshness story.
 *
 * The closing beat reuses `claims.apply_early_rolling.body` verbatim rather than
 * introducing a second phrasing of the same claim, and wears the quotable
 * treatment (hairline rule + `quotableFontSize`) that the since-deleted Signal
 * prototype established for a liftable sentence — the one styling convention
 * worth keeping from it.
 */
export function HowItWorksSection({ content }: HowItWorksSectionProps) {
  const { heading, steps } = content.howItWorks;

  return (
    <Box component="section" data-testid="how-it-works">
      <Typography
        component="h2"
        sx={{
          fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
          fontWeight: 600,
          mb: RESPONSIVE.landingProto.sectionTitleMarginBottom,
        }}
      >
        {heading}
      </Typography>

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
                fontWeight: 600,
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

      {/* The one emotional line on the page: why any of the above matters.
          Capped well short of the lg container so it reads as a pull-quote at a
          comfortable measure (~60ch) rather than a full-width paragraph; the
          single hairline above it is the section's only rule. */}
      <Box sx={{ mt: RESPONSIVE.landingProto.sectionBlockGapY, maxWidth: 620 }}>
        <Divider sx={{ mb: 4 }} />
        <Typography
          sx={{
            fontSize: RESPONSIVE.landingProto.quotableFontSize,
            fontWeight: 500,
            lineHeight: 1.7,
          }}
        >
          {content.claims.apply_early_rolling.body}
        </Typography>
      </Box>
    </Box>
  );
}

export default HowItWorksSection;
