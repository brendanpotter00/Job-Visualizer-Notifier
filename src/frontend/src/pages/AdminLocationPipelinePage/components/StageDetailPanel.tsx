import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import type { StageIO, StageMeta } from '../fixtures';

interface StageDetailPanelProps {
  stage: StageMeta;
  io: StageIO;
  isFailed: boolean;
}

const preBase = {
  m: 0,
  p: 1.25,
  borderRadius: 1,
  fontFamily: 'monospace',
  fontSize: 12,
  lineHeight: 1.5,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  overflowX: 'auto',
} as const;

/** Shows the input → output transformation for the active stage. */
export function StageDetailPanel({ stage, io, isFailed }: StageDetailPanelProps) {
  return (
    <Paper variant="outlined" sx={{ p: 0, overflow: 'hidden', height: '100%' }}>
      <Box
        sx={{
          px: 2,
          py: 1.25,
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 1,
          flexWrap: 'wrap',
        }}
      >
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          {stage.title}
        </Typography>
        <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
          {stage.codeRef}
        </Typography>
      </Box>
      <Box sx={{ p: 2 }}>
        <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          In
        </Typography>
        <Box
          component="pre"
          sx={{
            ...preBase,
            bgcolor: 'action.hover',
            border: 1,
            borderColor: 'divider',
            color: 'text.secondary',
          }}
        >
          {io.in ?? '—'}
        </Box>
        <Typography align="center" sx={{ color: 'text.disabled', my: 0.5 }}>
          ↓
        </Typography>
        <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Out
        </Typography>
        <Box
          component="pre"
          sx={{
            ...preBase,
            bgcolor: 'action.hover',
            border: 1,
            borderColor: 'divider',
            borderLeft: 3,
            borderLeftColor: isFailed ? 'error.main' : 'success.main',
            color: isFailed ? 'error.main' : 'text.primary',
          }}
        >
          {io.out}
        </Box>
      </Box>
    </Paper>
  );
}
