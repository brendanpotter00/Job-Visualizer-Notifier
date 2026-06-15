import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { AnimatePresence, motion } from 'framer-motion';
import type { DbRows } from '../fixtures';

const TABLES: { key: keyof DbRows; caption: string }[] = [
  { key: 'locations', caption: 'locations' },
  { key: 'locationAliases', caption: 'location_aliases' },
  { key: 'aliasLocations', caption: 'alias_locations' },
  { key: 'jobLocations', caption: 'job_locations' },
];

interface DataTablesPanelProps {
  rows: DbRows;
  /** Rows only show on a successful persist. */
  visible: boolean;
  statusLabel: string;
  statusColor: 'default' | 'success' | 'error' | 'warning';
}

/** The four normalization tables, filling with rows as the example persists. */
export function DataTablesPanel({ rows, visible, statusLabel, statusColor }: DataTablesPanelProps) {
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
        }}
      >
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          Database (fills on persist)
        </Typography>
        <Chip
          size="small"
          label={statusLabel}
          color={statusColor === 'default' ? undefined : statusColor}
          variant={statusColor === 'default' ? 'outlined' : 'filled'}
        />
      </Box>
      <Box
        sx={{
          p: 2,
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
          gap: 1.5,
        }}
      >
        {TABLES.map(({ key, caption }) => {
          const items = visible ? rows[key] : [];
          return (
            <Box
              key={key}
              sx={{ border: 1, borderColor: 'divider', borderRadius: 1, overflow: 'hidden' }}
            >
              <Box
                sx={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  px: 1,
                  py: 0.5,
                  bgcolor: 'action.hover',
                  borderBottom: 1,
                  borderColor: 'divider',
                }}
              >
                <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
                  {caption}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ fontFamily: 'monospace', color: 'text.secondary' }}
                >
                  {items.length}
                </Typography>
              </Box>
              <Box sx={{ minHeight: 28 }}>
                {items.length === 0 ? (
                  <Box sx={{ px: 1, py: 0.5 }}>
                    <Typography
                      variant="caption"
                      sx={{ color: 'text.disabled', fontStyle: 'italic' }}
                    >
                      empty
                    </Typography>
                  </Box>
                ) : (
                  <AnimatePresence>
                    {items.map((row, idx) => (
                      <motion.div
                        key={row}
                        initial={{ opacity: 0, y: -6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        transition={{ delay: idx * 0.08 }}
                      >
                        <Box
                          sx={{
                            px: 1,
                            py: 0.5,
                            borderTop: idx === 0 ? 0 : 1,
                            borderColor: 'divider',
                          }}
                        >
                          <Typography
                            variant="caption"
                            sx={{
                              fontFamily: 'monospace',
                              color: 'text.secondary',
                              fontSize: 10.5,
                            }}
                          >
                            {row}
                          </Typography>
                        </Box>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                )}
              </Box>
            </Box>
          );
        })}
      </Box>
    </Paper>
  );
}
