import { useCallback, useState, type ReactNode } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';
import type { StepId } from './content';
import { CostBreakdown } from './components/CostBreakdown';
import { FlowDiagram } from './components/FlowDiagram';
import { StepPanel } from './components/StepPanel';

const BEFORE = [
  'I scroll X or LinkedIn and spot an interesting company.',
  'I open its website on my phone or laptop.',
  "Later, I can't remember which tab it was in, so the company never gets added.",
];

const AFTER = [
  'New funding rounds and launches arrive every morning.',
  'Each one is a card, already researched.',
  'Each card has a talent score and a VC score.',
  'I save or archive it in one click.',
];

function GoalCard({ title, items }: { title: string; items: string[] }) {
  return (
    <Box sx={{ bgcolor: 'background.paper', borderRadius: 1, px: 2, py: 1.75 }}>
      <Typography variant="subtitle2" component="h2" color="text.secondary" sx={{ mb: 0.5 }}>
        {title}
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.25, typography: 'body2' }}>
        {items.map((item) => (
          <Box component="li" key={item} sx={{ mt: 0.5 }}>
            {item}
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function Section({
  title,
  defaultExpanded = false,
  children,
}: {
  title: string;
  defaultExpanded?: boolean;
  children: ReactNode;
}) {
  return (
    <Accordion
      variant="outlined"
      disableGutters
      defaultExpanded={defaultExpanded}
      sx={{
        mb: 1,
        borderRadius: 1,
        bgcolor: 'background.default',
        '&::before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography component="h2" variant="body1" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      </AccordionSummary>
      <AccordionDetails>{children}</AccordionDetails>
    </Accordion>
  );
}

/**
 * /launch-radar/how-it-works: how the Launch Radar loop finds, researches and
 * scores startups with the Parallel API. Public (not admin-gated) and static:
 * every value on it is a constant from ./content.
 */
export function LaunchRadarHowItWorksPage() {
  const [openStep, setOpenStep] = useState<StepId | null>(null);
  const toggleStep = useCallback(
    (step: StepId) => setOpenStep((current) => (current === step ? null : step)),
    []
  );
  const closeStep = useCallback(() => setOpenStep(null), []);

  return (
    <Container maxWidth="md" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      {/* The only link to this page is under the Launch Radar title, so back goes there. */}
      <Button
        component={RouterLink}
        to={ROUTES.ADMIN_LAUNCH_RADAR}
        size="small"
        startIcon={<ArrowBackIcon />}
        sx={{ ml: -1, mb: 1 }}
      >
        Launch Radar
      </Button>
      <Typography
        variant="h3"
        component="h1"
        sx={{ fontSize: RESPONSIVE.fontSize.pageTitle, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        How Launch Radar works
      </Typography>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
          gap: 1.5,
          mb: RESPONSIVE.spacing.sectionMarginB,
        }}
      >
        <GoalCard title="Before" items={BEFORE} />
        <GoalCard title="After" items={AFTER} />
      </Box>

      <Section title="How it works" defaultExpanded>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Click a box to see its details.
        </Typography>
        <FlowDiagram openStep={openStep} onSelect={toggleStep} />
      </Section>

      <Section title="Cost">
        <CostBreakdown />
      </Section>

      <StepPanel step={openStep} onClose={closeStep} />
    </Container>
  );
}
