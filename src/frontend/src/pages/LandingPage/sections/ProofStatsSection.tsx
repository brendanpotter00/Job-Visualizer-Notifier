import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';
import { SectionIntro } from './SectionIntro';

const HEADING_ID = 'landing-proof-heading';

interface ProofStatsSectionProps {
  content: LandingContent;
}

/**
 * Three numbers, each over the standalone sentence that backs it. The
 * sentences are the quotable claims (brief §10 P1: subject-verb-number, no
 * surrounding context needed), so they are rendered verbatim and never
 * reworded here; the big value above each is only its skim target.
 */
export function ProofStatsSection({ content }: ProofStatsSectionProps) {
  const { eyebrow, heading, stats } = content.proof;

  return (
    <Box component="section" aria-labelledby={HEADING_ID} data-testid="proof-stats">
      <SectionIntro eyebrow={eyebrow} heading={heading} headingId={HEADING_ID} />
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(3, minmax(0, 1fr))' },
          columnGap: { xs: 0, sm: 6 },
          rowGap: { xs: 4, sm: 0 },
        }}
      >
        {stats.map((stat) => (
          <Box
            key={stat.id}
            data-testid={`proof-stat-${stat.id}`}
            sx={{ minWidth: 0, borderTop: '1px solid', borderColor: 'divider', pt: 3 }}
          >
            <Typography
              component="p"
              sx={{
                fontSize: RESPONSIVE.landingProto.statValueFontSize,
                fontWeight: 500,
                letterSpacing: '-0.03em',
                lineHeight: 1,
                mb: 2,
              }}
            >
              {stat.value}
            </Typography>
            <Typography
              component="p"
              sx={{
                fontSize: RESPONSIVE.landingProto.bodyFontSize,
                color: 'text.secondary',
                lineHeight: 1.6,
              }}
            >
              {stat.sentence}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

export default ProofStatsSection;
