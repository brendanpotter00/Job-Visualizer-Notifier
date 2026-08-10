import { Accordion, AccordionDetails, AccordionSummary, Box, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';

interface FAQSectionProps {
  content: LandingContent;
}

/**
 * FAQ as collapsed accordions (brief §10 P2): questions phrased the way people
 * ask answer engines, answer-first bodies. All entries start CLOSED so the
 * section reads as a quiet list instead of a wall of prose.
 *
 * AEO invariant: the answers must stay in the DOM while collapsed — crawlers
 * that never execute JS (and quotability) depend on the text being present, not
 * behind a click. MUI's `Collapse` keeps its children mounted by default (it
 * only collapses height/visibility), so this holds as long as nobody adds
 * `unmountOnExit` / `keepMounted={false}` to the transition slot. Covered by
 * FAQSection.test.tsx ("keeps every answer in the DOM while collapsed").
 *
 * Styling stays monochrome: no elevation, no paper tint, hairline dividers, and
 * the expand chevron inherits the text color rather than MUI's grey
 * `action.active`.
 */
export function FAQSection({ content }: FAQSectionProps) {
  return (
    <Box sx={{ maxWidth: 720, mx: 'auto' }}>
      <Typography
        variant="h2"
        sx={{
          fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
          fontWeight: 600,
          mb: RESPONSIVE.landingProto.sectionTitleMarginBottom,
        }}
      >
        Frequently asked questions
      </Typography>
      {/* Top hairline; each row draws its own bottom rule so the list closes. */}
      <Box sx={{ borderTop: '1px solid', borderColor: 'divider' }}>
        {content.faq.map((entry) => (
          <Accordion
            key={entry.question}
            disableGutters
            elevation={0}
            square
            sx={{
              bgcolor: 'transparent',
              borderBottom: '1px solid',
              borderColor: 'divider',
              // MUI's stacked-accordion divider artifact; the hairline above
              // already separates rows.
              '&::before': { display: 'none' },
            }}
          >
            <AccordionSummary
              expandIcon={<ExpandMoreIcon fontSize="small" />}
              sx={{
                px: 0,
                // Taller rows: the questions are the skimmable surface, so each
                // one gets its own band of air instead of MUI's 48px default.
                py: RESPONSIVE.landingProto.faqRowPaddingY,
                // Chevron follows the black-on-white text instead of MUI's grey.
                '& .MuiAccordionSummary-expandIconWrapper': { color: 'inherit' },
              }}
            >
              {/* MUI already wraps the summary in an <h3> (Accordion's heading
                  slot), so the question renders as a span inside that heading. */}
              <Typography
                component="span"
                sx={{ fontSize: RESPONSIVE.landingProto.blockTitleFontSize, fontWeight: 600 }}
              >
                {entry.question}
              </Typography>
            </AccordionSummary>
            <AccordionDetails sx={{ px: 0, pt: 0, pb: 4 }}>
              {/* Answers wrap a little short of the row rules (~65ch) so the
                  prose keeps a comfortable measure even though the questions
                  and their hairlines run the full block width. */}
              <Typography
                variant="body2"
                sx={{
                  color: 'text.secondary',
                  fontSize: RESPONSIVE.landingProto.bodyFontSize,
                  lineHeight: 1.7,
                  maxWidth: 640,
                }}
              >
                {entry.answer}
              </Typography>
            </AccordionDetails>
          </Accordion>
        ))}
      </Box>
    </Box>
  );
}
