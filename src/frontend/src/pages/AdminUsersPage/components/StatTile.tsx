import Box from '@mui/material/Box';
import { OPS, SX } from '../adminUsersTheme';

interface StatTileProps {
  /** Tiny uppercase caption above the value */
  label: string;
  /** Primary stat (string or number — pre-formatted) */
  value: React.ReactNode;
  /** Optional secondary line under the value */
  meta?: React.ReactNode;
  /** Optional ASCII rule decoration on the corners ("┌─ TOTAL USERS ─┐") */
  withCorners?: boolean;
  /** Optional element rendered in the lower-right of the tile (sparkline, etc.) */
  decoration?: React.ReactNode;
}

export function StatTile({ label, value, meta, withCorners = true, decoration }: StatTileProps) {
  return (
    <Box
      sx={{
        ...SX.surface,
        position: 'relative',
        px: 2.5,
        py: 2.5,
        minHeight: 132,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
        {withCorners && (
          <Box component="span" sx={{ ...SX.dimMono, color: OPS.textDim }}>
            ┌─
          </Box>
        )}
        <Box component="span" sx={SX.caption}>
          {label}
        </Box>
        {withCorners && (
          <Box
            component="span"
            sx={{
              ...SX.dimMono,
              color: OPS.textDim,
              flexGrow: 1,
              borderBottom: `1px dashed ${OPS.border}`,
              transform: 'translateY(-4px)',
            }}
          />
        )}
        {withCorners && (
          <Box component="span" sx={{ ...SX.dimMono, color: OPS.textDim }}>
            ─┐
          </Box>
        )}
      </Box>

      <Box
        sx={{
          fontFamily: OPS.mono,
          fontSize: { xs: 36, sm: 44, md: 52 },
          fontWeight: 500,
          lineHeight: 1.05,
          color: OPS.textPrimary,
          letterSpacing: '-0.02em',
        }}
      >
        {value}
      </Box>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 2 }}>
        <Box sx={SX.dimMono}>{meta}</Box>
        {decoration}
      </Box>
    </Box>
  );
}
