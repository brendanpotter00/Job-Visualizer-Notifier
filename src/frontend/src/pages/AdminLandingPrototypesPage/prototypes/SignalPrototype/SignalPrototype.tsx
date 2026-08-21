import type { ReactNode } from 'react';
import { Box, Container, Divider, Grid, Typography } from '@mui/material';
import { motion } from 'framer-motion';
import { RESPONSIVE } from '../../../../config/responsive';
import { usePrefersReducedMotion } from '../../usePrefersReducedMotion';
import type { LandingPrototypeProps } from '../../types';
import { LandingHeader } from '../../sections/LandingHeader';
import { HeroCopy } from '../../sections/HeroCopy';
import { CTAButtons } from '../../sections/CTAButtons';
import { LogoWall } from '../../sections/LogoWall';
import { RotatingJobCard } from '../../sections/RotatingJobCard';
import { FAQSection } from '../../sections/FAQSection';
import { FooterLite } from '../../sections/FooterLite';

/**
 * "Signal" — the clean, cursor-inspired minimal take (brief §11 P1): Linear's
 * tight skeleton, hero variant A (source-led), the browse/create-account CTA
 * pair, restrained framer-motion reveals, proof closing the page. Monochrome
 * light throughout.
 */
export function SignalPrototype({ content, jobs, now }: LandingPrototypeProps) {
  return (
    <Box>
      <LandingHeader content={content} />
      <Container maxWidth="lg">
        {/* Hero — the LCP element is this DOM text, by design. */}
        <Box sx={{ py: RESPONSIVE.landingProto.heroPaddingY }}>
          <HeroCopy content={content} variant="source" showBroadSupportLine />
          <Box sx={{ mt: 4 }}>
            <CTAButtons ctas={content.ctas} showSecondary />
          </Box>
        </Box>

        <Box sx={{ pb: RESPONSIVE.landingProto.sectionPaddingY }}>
          <LogoWall rows={1} perRow={24} />
        </Box>

        <Reveal>
          <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
            <RotatingJobCard jobs={jobs} now={now} />
          </Box>
        </Reveal>

        <Reveal>
          <Grid container spacing={{ xs: 2, sm: 4 }} sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
            {(['straight_from_source', 'no_reposts', 'curated_companies'] as const).map((id) => (
              <Grid key={id} size={{ xs: 12, sm: 4 }}>
                <Typography variant="h3" sx={{ fontSize: '1.0625rem', fontWeight: 600, mb: 1 }}>
                  {content.claims[id].heading}
                </Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary', lineHeight: 1.6 }}>
                  {content.claims[id].body}
                </Typography>
              </Grid>
            ))}
          </Grid>
        </Reveal>

        <Reveal>
          <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY, maxWidth: 720, mx: 'auto' }}>
            <Typography
              variant="h2"
              sx={{
                fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
                fontWeight: 600,
                mb: 1.5,
              }}
            >
              {content.claims.apply_early_rolling.heading}
            </Typography>
            <Typography sx={{ color: 'text.secondary', lineHeight: 1.7 }}>
              {content.supportingBeat}
            </Typography>
            <Typography variant="body2" sx={{ color: 'text.secondary', mt: 2, lineHeight: 1.6 }}>
              {content.comparison}
            </Typography>
          </Box>
        </Reveal>

        {/* Quotable block (brief §10 P1): liftable subject-verb-number sentences. */}
        <Reveal>
          <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY, maxWidth: 720, mx: 'auto' }}>
            <Divider sx={{ mb: 3 }} />
            {content.quotableClaims.map((claim) => (
              <Typography
                key={claim}
                sx={{
                  fontSize: RESPONSIVE.landingProto.quotableFontSize,
                  fontWeight: 500,
                  lineHeight: 1.6,
                  mb: 2,
                }}
              >
                {claim}
              </Typography>
            ))}
            <Divider sx={{ mt: 1 }} />
          </Box>
        </Reveal>

        <Reveal>
          <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
            <FAQSection content={content} />
          </Box>
        </Reveal>

        {/* Closing proof + CTA (brief §11 — proof ends the page). */}
        <Reveal>
          <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY, textAlign: 'center' }}>
            <Typography
              variant="h2"
              sx={{ fontSize: RESPONSIVE.landingProto.sectionTitleFontSize, fontWeight: 600, mb: 3 }}
            >
              {content.footer.tagline}
            </Typography>
            <CTAButtons ctas={content.ctas} showSecondary />
          </Box>
        </Reveal>

        <FooterLite content={content} />
      </Container>
    </Box>
  );
}

/** Staggered fade-rise on scroll into view; renders plain under reduced motion. */
function Reveal({ children }: { children: ReactNode }) {
  const reducedMotion = usePrefersReducedMotion();
  if (reducedMotion) return <>{children}</>;
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{ duration: 0.45, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  );
}

export default SignalPrototype;
