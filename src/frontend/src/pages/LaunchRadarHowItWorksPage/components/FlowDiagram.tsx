import { useEffect, useRef, type ReactNode } from 'react';
import Box from '@mui/material/Box';
import ButtonBase from '@mui/material/ButtonBase';
import Typography from '@mui/material/Typography';
import { API_STEPS, SCORE_STEP, type StepId } from '../content';
import { STEP_PANEL_ID } from './StepPanel';

const LANE_BORDER = 'grey.400';

interface FlowDiagramProps {
  openStep: StepId | null;
  onSelect: (step: StepId) => void;
}

function Arrow() {
  return (
    <Typography aria-hidden align="center" color="text.secondary" sx={{ lineHeight: 1, py: 0.75 }}>
      ↓
    </Typography>
  );
}

/**
 * The two ways in (the daily Monitor and the one-off backfill) meet at the
 * shared research steps. Every box opens its details in the right-hand panel.
 */
export function FlowDiagram({ openStep, onSelect }: FlowDiagramProps) {
  const buttons = useRef<Partial<Record<StepId, HTMLButtonElement | null>>>({});
  const lastOpen = useRef<StepId | null>(null);

  // When the panel closes, give focus back to the box that opened it, unless the
  // reader has already moved focus somewhere else on the page.
  useEffect(() => {
    const closed = lastOpen.current;
    lastOpen.current = openStep;
    if (openStep !== null || closed === null) return;
    const active = document.activeElement;
    const panel = document.getElementById(STEP_PANEL_ID);
    if (!active || active === document.body || panel?.contains(active)) {
      buttons.current[closed]?.focus({ preventScroll: true });
    }
  }, [openStep]);

  const node = (id: StepId, free = false): ReactNode => {
    const { title, api } = id === 'score' ? SCORE_STEP : API_STEPS[id];
    const isOpen = openStep === id;
    return (
      <ButtonBase
        key={id}
        ref={(el: HTMLButtonElement | null) => {
          buttons.current[id] = el;
        }}
        onClick={() => onSelect(id)}
        aria-expanded={isOpen}
        aria-controls={STEP_PANEL_ID}
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          gap: 0.25,
          width: '100%',
          textAlign: 'left',
          px: 1.75,
          py: 1.5,
          borderRadius: 1,
          border: 1,
          borderStyle: free ? 'dashed' : 'solid',
          borderColor: isOpen ? 'text.primary' : 'divider',
          boxShadow: isOpen ? (theme) => `inset 0 0 0 1px ${theme.palette.text.primary}` : 'none',
          bgcolor: free ? 'background.paper' : 'background.default',
          '&:hover': { borderColor: isOpen ? 'text.primary' : LANE_BORDER },
          '&.Mui-focusVisible': { outline: 2, outlineColor: 'text.primary', outlineOffset: 2 },
        }}
      >
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {api}
        </Typography>
      </ButtonBase>
    );
  };

  const lane = (name: string, dashed: boolean, children: ReactNode) => (
    <Box
      sx={{
        border: 1,
        borderStyle: dashed ? 'dashed' : 'solid',
        borderColor: LANE_BORDER,
        borderRadius: 1,
        p: 1.25,
        bgcolor: dashed ? 'grey.50' : 'background.default',
      }}
    >
      <Typography
        variant="caption"
        component="p"
        color="text.secondary"
        sx={{ fontWeight: 600, mb: 1, mx: 0.25 }}
      >
        {name}
      </Typography>
      {children}
    </Box>
  );

  return (
    <Box>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1.5 }}>
        {lane('Daily Claude Code', false, node('monitor'))}
        {lane(
          'Backfill',
          true,
          <>
            {node('backfillFind')}
            <Arrow />
            {node('backfillEnrich')}
          </>
        )}
      </Box>
      {/* A bracket from the middle of each lane down to the shared steps. */}
      <Box
        aria-hidden
        sx={{
          display: { xs: 'none', sm: 'block' },
          height: 16,
          mx: '25%',
          border: 1,
          borderTop: 0,
          borderColor: LANE_BORDER,
          borderRadius: '0 0 6px 6px',
        }}
      />
      <Arrow />
      {node('website')}
      <Arrow />
      <Typography
        variant="caption"
        component="p"
        align="center"
        color="text.secondary"
        sx={{ mb: 0.75 }}
      >
        At the same time
      </Typography>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' },
          gap: 1.25,
        }}
      >
        {node('leaders')}
        {node('company')}
        {node('team')}
      </Box>
      <Arrow />
      {node('leaderResearch')}
      <Arrow />
      {node('score', true)}
    </Box>
  );
}
