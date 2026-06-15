import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { alpha, useTheme } from '@mui/material/styles';
import { motion, useReducedMotion } from 'framer-motion';
import type { StageMeta } from '../fixtures';

export type NodeState = 'idle' | 'active' | 'done' | 'failed' | 'skipped';

interface StageNodeProps {
  meta: StageMeta;
  index: number;
  state: NodeState;
}

/**
 * A single pipeline stage box. framer-motion drives the scale/opacity motion;
 * all visual styling (border, fill, type) comes from MUI + the app theme.
 */
export function StageNode({ meta, index, state }: StageNodeProps) {
  const theme = useTheme();
  const reduce = useReducedMotion();

  const palette = {
    idle: { border: theme.palette.divider, bg: theme.palette.background.paper },
    active: { border: theme.palette.primary.main, bg: theme.palette.background.default },
    done: { border: theme.palette.success.main, bg: alpha(theme.palette.success.main, 0.08) },
    failed: { border: theme.palette.error.main, bg: alpha(theme.palette.error.main, 0.08) },
    skipped: { border: theme.palette.divider, bg: theme.palette.background.paper },
  }[state];

  const emphasised = state === 'active' || state === 'failed';

  const badgeBg =
    state === 'active'
      ? theme.palette.primary.main
      : state === 'done'
        ? theme.palette.success.main
        : theme.palette.background.default;
  const badgeColor =
    state === 'active'
      ? theme.palette.primary.contrastText
      : state === 'done'
        ? theme.palette.success.contrastText
        : theme.palette.text.secondary;

  return (
    <motion.div
      style={{ flex: '1 1 0', minWidth: 0 }}
      animate={{
        scale: reduce ? 1 : emphasised ? 1.04 : 1,
        opacity: state === 'skipped' ? 0.45 : 1,
      }}
      transition={{ type: 'spring', stiffness: 320, damping: 24 }}
    >
      <Paper
        variant="outlined"
        sx={{
          position: 'relative',
          minHeight: 84,
          px: 1,
          py: 1.25,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 0.25,
          textAlign: 'center',
          borderColor: palette.border,
          borderWidth: emphasised ? 2 : 1,
          bgcolor: palette.bg,
          boxShadow: emphasised ? 3 : 0,
          transition: theme.transitions.create(['border-color', 'background-color', 'box-shadow']),
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            top: -11,
            width: 22,
            height: 22,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            fontWeight: 700,
            border: '1.5px solid',
            borderColor: palette.border,
            bgcolor: badgeBg,
            color: badgeColor,
          }}
        >
          {index + 1}
        </Box>
        <Typography
          variant="caption"
          sx={{
            fontWeight: 700,
            lineHeight: 1.15,
            color: state === 'skipped' ? 'text.disabled' : 'text.primary',
          }}
        >
          {meta.title}
        </Typography>
        <Typography
          variant="caption"
          sx={{ fontSize: 10.5, color: 'text.secondary', fontFamily: 'monospace', lineHeight: 1.2 }}
        >
          {meta.subtitle}
        </Typography>
      </Paper>
    </motion.div>
  );
}
