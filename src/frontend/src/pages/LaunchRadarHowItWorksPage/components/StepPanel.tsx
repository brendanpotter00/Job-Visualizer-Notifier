import { useEffect, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Drawer from '@mui/material/Drawer';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../../config/responsive';
import { API_STEPS, SCORE_STEP, stepTitle, type StepFact, type StepId } from '../content';
import { RequestBody } from './RequestBody';
import { ScoringDetails } from './ScoringDetails';

export const STEP_PANEL_ID = 'launch-radar-step-panel';

/** API, setting, cost and latency, one per row. */
function StepFacts({ facts }: { facts: StepFact[] }) {
  return (
    <Box
      component="dl"
      sx={{
        display: 'grid',
        gridTemplateColumns: 'max-content 1fr',
        columnGap: 3,
        rowGap: 0.75,
        m: 0,
        mb: 2.5,
      }}
    >
      {facts.map((fact) => (
        <Box key={fact.label} sx={{ display: 'contents' }}>
          <Typography component="dt" variant="body2" color="text.secondary">
            {fact.label}
          </Typography>
          <Typography component="dd" variant="body2" sx={{ m: 0, fontWeight: 600 }}>
            {fact.value}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

interface StepPanelProps {
  step: StepId | null;
  onClose: () => void;
}

/**
 * The details of one diagram box, in a panel on the right. It does not cover
 * the page with a backdrop, so the reader can click the next box straight away.
 * Escape closes it.
 */
export function StepPanel({ step, onClose }: StepPanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  // Keep drawing the last step while the panel slides out, so it does not empty first.
  const [shown, setShown] = useState<StepId | null>(step);
  if (step !== null && step !== shown) setShown(step);

  useEffect(() => {
    if (step === null) return;
    closeRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [step, onClose]);

  return (
    <Drawer
      variant="persistent"
      anchor="right"
      open={step !== null}
      slotProps={{
        paper: {
          id: STEP_PANEL_ID,
          component: 'aside',
          'aria-labelledby': `${STEP_PANEL_ID}-title`,
          sx: {
            // Above the app bar (drawer + 1), so the panel's title and Close stay visible.
            zIndex: (theme) => theme.zIndex.drawer + 2,
            // Block, not the Drawer's flex column: in a flex column the scrolling
            // table wrappers shrink to nothing and the rows paint over the notes.
            display: 'block',
            width: RESPONSIVE.launchRadarHowItWorks.panelWidth,
            p: RESPONSIVE.launchRadarHowItWorks.panelPadding,
            bgcolor: 'background.default',
            boxShadow: 8,
          },
        },
      }}
    >
      {shown !== null && (
        <>
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              gap: 2,
              mb: 2,
            }}
          >
            <Typography id={`${STEP_PANEL_ID}-title`} variant="h6" component="h2">
              {stepTitle(shown)}
            </Typography>
            <Button ref={closeRef} variant="outlined" size="small" onClick={onClose}>
              Close
            </Button>
          </Box>
          {shown === 'score' ? (
            <>
              <StepFacts facts={SCORE_STEP.facts} />
              <ScoringDetails />
            </>
          ) : (
            <>
              <StepFacts facts={API_STEPS[shown].facts} />
              <Typography
                variant="subtitle2"
                component="h3"
                color="text.secondary"
                sx={{ mb: 0.75 }}
              >
                Request body
              </Typography>
              <RequestBody value={API_STEPS[shown].request} />
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
