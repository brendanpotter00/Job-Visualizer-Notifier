import { Box, Container, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../../config/responsive';
import type { LandingPrototypeProps } from '../../types';
import { HeroCopy } from '../../sections/HeroCopy';
import { CTAButtons } from '../../sections/CTAButtons';
import { LiveActivityStats } from '../../sections/LiveActivityStats';
import { FreshJobsTicker } from '../../sections/FreshJobsTicker';
import { FAQSection } from '../../sections/FAQSection';
import { FooterLite } from '../../sections/FooterLite';

/**
 * "Gravity" — falling company logos with physics. STUB: the three.js/rapier
 * scene is designed separately and replaces the placeholder panel below; the
 * rest of the page (hero copy layer, sections) is final composition. Contract
 * for the scene work: hero text/CTA stay on a DOM layer the physics can never
 * occlude; the settled pile doubles as the logo wall (no grid repeat below);
 * reduced-motion/no-WebGL renders a static pre-settled DOM grid instead
 * (brief §11 P3).
 */
export function GravityPrototype({ content, jobs, stats, now }: LandingPrototypeProps) {
  return (
    <Box>
      {/* Hero region: DOM copy over the (future) physics canvas. */}
      <Box sx={{ position: 'relative', overflow: 'hidden' }}>
        <Container maxWidth="lg" sx={{ py: RESPONSIVE.landingProto.heroPaddingY }}>
          <HeroCopy content={content} variant="source" />
          <Box sx={{ mt: 4 }}>
            <CTAButtons ctas={content.ctas} />
          </Box>
          <Box
            aria-hidden
            sx={{
              mt: 6,
              height: { xs: 200, sm: 280 },
              border: '1px dashed',
              borderColor: 'divider',
              borderRadius: 2,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Typography variant="body2" sx={{ color: 'text.disabled' }}>
              3D scene placeholder — company logos fall, tumble, and settle here
            </Typography>
          </Box>
        </Container>
      </Box>

      <Container maxWidth="lg">
        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <LiveActivityStats jobs={jobs} stats={stats} now={now} />
          <Box sx={{ mt: 5 }}>
            <FreshJobsTicker jobs={jobs} now={now} />
          </Box>
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
