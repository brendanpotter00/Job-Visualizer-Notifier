import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';

interface FAQSectionProps {
  content: LandingContent;
}

/**
 * FAQ as plain, crawlable DOM text (brief §10 P2): question headings phrased
 * the way people ask answer engines, answer-first bodies. No accordion — the
 * text must exist in the DOM for crawlers and quotability, not behind a click.
 */
export function FAQSection({ content }: FAQSectionProps) {
  return (
    <Box sx={{ maxWidth: 720, mx: 'auto' }}>
      <Typography
        variant="h2"
        sx={{ fontSize: RESPONSIVE.landingProto.sectionTitleFontSize, fontWeight: 600, mb: 3 }}
      >
        Frequently asked questions
      </Typography>
      {content.faq.map((entry) => (
        <Box key={entry.question} sx={{ mb: 3 }}>
          <Typography variant="h3" sx={{ fontSize: '1rem', fontWeight: 600, mb: 0.75 }}>
            {entry.question}
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary', lineHeight: 1.6 }}>
            {entry.answer}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}
