import Box from '@mui/material/Box';
import { alpha, useTheme } from '@mui/material/styles';
import { motion, useReducedMotion } from 'framer-motion';

interface FlowConnectorProps {
  /** Whether this segment has been traversed (renders green). */
  lit: boolean;
  /** Whether a spark should travel across this segment right now. */
  flowing: boolean;
  /** Changes on each advance so the spark animation re-triggers. */
  flowKey: number;
}

/** The animated link between two stage nodes. */
export function FlowConnector({ lit, flowing, flowKey }: FlowConnectorProps) {
  const theme = useTheme();
  const reduce = useReducedMotion();

  return (
    <Box sx={{ flex: '0 0 26px', alignSelf: 'center', position: 'relative', height: 3, mt: 0.5 }}>
      <Box
        sx={{
          position: 'absolute',
          inset: 0,
          borderRadius: 1,
          bgcolor: lit ? 'success.main' : 'divider',
          transition: theme.transitions.create('background-color'),
        }}
      />
      {flowing && !reduce && (
        <motion.span
          key={flowKey}
          initial={{ left: '0%', opacity: 1 }}
          animate={{ left: '100%', opacity: 0 }}
          transition={{ duration: 0.6, ease: 'easeInOut' }}
          style={{
            position: 'absolute',
            top: '50%',
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: theme.palette.primary.main,
            transform: 'translate(-50%, -50%)',
            boxShadow: `0 0 0 4px ${alpha(theme.palette.primary.main, 0.15)}`,
          }}
        />
      )}
    </Box>
  );
}
