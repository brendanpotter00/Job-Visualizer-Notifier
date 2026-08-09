import { Box, Container, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../../config/responsive';
import type { LandingPrototypeProps } from '../../types';
import { CTAButtons } from '../../sections/CTAButtons';
import { LiveActivityStats } from '../../sections/LiveActivityStats';
import { LogoWall } from '../../sections/LogoWall';
import { FAQSection } from '../../sections/FAQSection';
import { FooterLite } from '../../sections/FooterLite';

/**
 * "Drift" — the subtle-particles take. STUB: the three.js particle field is
 * designed separately and mounts behind the hero copy; particles must encode
 * data ("every dot is a job posted today" — brief §11 P4), monochrome gray,
 * ≤10% visual weight. Below the hero this is deliberately Signal's restrained
 * skeleton so Signal↔Drift is an honest A/B pair. The hero here is the terse
 * 2–4-word variant the teardown recommends pairing with a background visual.
 */
export function DriftPrototype({ content, jobs, stats, now }: LandingPrototypeProps) {
  return (
    <Box>
      {/* Hero: terse noun phrase over the (future) particle field. */}
      <Box sx={{ position: 'relative', overflow: 'hidden' }}>
        <Container maxWidth="lg" sx={{ py: RESPONSIVE.landingProto.heroPaddingY }}>
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
            <CTAButtons ctas={content.ctas} />
          </Box>
          <Typography
            variant="caption"
            sx={{ display: 'block', textAlign: 'center', color: 'text.disabled', mt: 6 }}
          >
            Particle field placeholder — every dot will be a job posted today
          </Typography>
        </Container>
      </Box>

      <Container maxWidth="lg">
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <LiveActivityStats jobs={jobs} stats={stats} now={now} />
        </Box>
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
