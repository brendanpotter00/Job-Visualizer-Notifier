import { Box } from '@mui/material';
import { RESPONSIVE } from '../../../../config/responsive';
import { useIsMobile } from '../../../../hooks/useIsMobile';
import type { LogoRosterEntry } from './logoRoster';

interface LogoGridFallbackProps {
  roster: readonly LogoRosterEntry[];
}

/**
 * DOM stand-in for the Gravity physics pile: the reduced-motion / no-WebGL
 * tier renders this pre-settled grid instead, so the "curated companies" proof
 * survives without downloading a byte of three/rapier. Slight static rotations
 * via nth-child selectors sell the "settled pile" without any animation.
 * MUST NOT import three or @react-three/* — it ships in the eager page chunk.
 */
export function LogoGridFallback({ roster }: LogoGridFallbackProps) {
  const isMobile = useIsMobile();
  const tileSize = isMobile
    ? RESPONSIVE.landingProto.logoTileSize.compact
    : RESPONSIVE.landingProto.logoTileSize.default;

  return (
    <Box
      aria-label="Companies tracked by onesecondswe"
      sx={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fill, minmax(${tileSize + 12}px, 1fr))`,
        gap: 1.5,
        justifyItems: 'center',
        '& img': {
          width: tileSize,
          height: tileSize,
          borderRadius: 1.5,
          objectFit: 'contain',
        },
        // The "pre-settled pile": alternating slight static tilts, no motion.
        '& img:nth-of-type(3n)': { transform: 'rotate(-5deg)' },
        '& img:nth-of-type(3n + 1)': { transform: 'rotate(3deg)' },
        '& img:nth-of-type(4n)': { transform: 'rotate(7deg)' },
      }}
    >
      {roster.map((entry) => (
        <img
          key={entry.companyId}
          src={entry.logoUrl}
          alt={entry.companyId}
          loading="lazy"
          onError={(event) => {
            // Logo files are committed per registry id but not guaranteed
            // (see getCompanyLogoUrl) — hide the tile instead of a broken icon.
            event.currentTarget.style.display = 'none';
          }}
        />
      ))}
    </Box>
  );
}
