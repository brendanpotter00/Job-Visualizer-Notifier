import { Box, Container } from '@mui/material';
import { RESPONSIVE } from '../../../../config/responsive';
import type { LandingPrototypeProps } from '../../types';
import { LandingHeader } from '../../sections/LandingHeader';
import { HeroCopy } from '../../sections/HeroCopy';
import { CTAButtons } from '../../sections/CTAButtons';
import { LogoWall } from '../../sections/LogoWall';
import { FreshJobsTicker } from '../../sections/FreshJobsTicker';
import { FAQSection } from '../../sections/FAQSection';
import { FooterLite } from '../../sections/FooterLite';
import { MiniJobBoard } from './MiniJobBoard';

/**
 * "The Board" — the jobs-forward take (grepjob's structure, fixed: a real
 * product CTA in the hero and the board within one viewport of the fold —
 * brief §11 P2). Hero variant B (anti-noise) since the board itself proves
 * the freshness claim card by card.
 */
export function BoardPrototype({ content, jobs, stats, now }: LandingPrototypeProps) {
  return (
    <Box>
      <LandingHeader content={content} />
      <Container maxWidth="lg">
        {/* Compact hero strip — the board must start within one viewport. */}
        <Box sx={{ pt: { xs: 5, sm: 8 }, pb: { xs: 3, sm: 5 } }}>
          <HeroCopy content={content} variant="antiNoise" />
          <Box sx={{ mt: 3 }}>
            <CTAButtons ctas={content.ctas} size="medium" showSecondary />
          </Box>
        </Box>

        <Box sx={{ pb: { xs: 3, sm: 4 } }}>
          <FreshJobsTicker jobs={jobs} now={now} maxItems={8} />
        </Box>

        <Box sx={{ pb: RESPONSIVE.landingProto.sectionPaddingY }}>
          <MiniJobBoard jobs={jobs} totalOpenJobs={stats.totalOpenJobs} />
        </Box>

        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <LogoWall rows={2} />
        </Box>

        <Box sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
          <FAQSection content={content} />
        </Box>

        <FooterLite content={content} />
      </Container>
    </Box>
  );
}

export default BoardPrototype;
