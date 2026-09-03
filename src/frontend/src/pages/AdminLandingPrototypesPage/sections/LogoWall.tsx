import { useMemo } from 'react';
import { Box } from '@mui/material';
import { COMPANIES, getCompanyById } from '../../../config/companies';
import { CompanyLogo } from '../../../components/shared/CompanyLogo/CompanyLogo';
import { RESPONSIVE } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { usePrefersReducedMotion } from '../usePrefersReducedMotion';

interface LogoWallProps {
  /** Company ids to show; defaults to a spread across the full registry. */
  companyIds?: readonly string[];
  rows?: number;
  /** Seconds for one full marquee loop (per row). */
  durationSec?: number;
  /** Cap on tiles per row (perf: every tile is an <img>). */
  perRow?: number;
}

/**
 * The shifting company-logo marquee (interview Q1 "curated companies" proof).
 * Rows drift in alternating directions, pause on hover, and collapse to a
 * static wrapped grid under prefers-reduced-motion. Row content is duplicated
 * once so translateX(-50%) loops seamlessly.
 */
export function LogoWall({ companyIds, rows = 2, durationSec = 55, perRow = 18 }: LogoWallProps) {
  const isMobile = useIsMobile();
  const reducedMotion = usePrefersReducedMotion();
  const tileSize = isMobile
    ? RESPONSIVE.landingProto.logoTileSize.compact
    : RESPONSIVE.landingProto.logoTileSize.default;

  const rowIds = useMemo(() => {
    const ids = companyIds ?? COMPANIES.map((c) => c.id);
    const out: string[][] = [];
    for (let r = 0; r < rows; r += 1) {
      // Deal the ids round-robin so each row differs without any randomness.
      out.push(ids.filter((_, i) => i % rows === r).slice(0, perRow));
    }
    return out.filter((row) => row.length > 0);
  }, [companyIds, rows, perRow]);

  if (reducedMotion) {
    return (
      <Box
        aria-label="Companies tracked by onesecondswe"
        sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5, justifyContent: 'center' }}
      >
        {rowIds.flat().map((id) => (
          <CompanyLogo
            key={id}
            companyId={id}
            displayName={getCompanyById(id)?.name ?? id}
            size={tileSize}
          />
        ))}
      </Box>
    );
  }

  return (
    <Box
      aria-label="Companies tracked by onesecondswe"
      sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, overflow: 'hidden' }}
    >
      {rowIds.map((ids, rowIndex) => (
        <Box key={ids[0]} sx={{ overflow: 'hidden' }}>
          <Box
            sx={{
              display: 'flex',
              gap: 1.5,
              width: 'max-content',
              animation: `landing-logo-marquee ${durationSec + rowIndex * 7}s linear infinite`,
              animationDirection: rowIndex % 2 === 1 ? 'reverse' : 'normal',
              '@keyframes landing-logo-marquee': {
                from: { transform: 'translateX(0)' },
                to: { transform: 'translateX(-50%)' },
              },
              '&:hover': { animationPlayState: 'paused' },
              // Belt-and-suspenders with the hook: the CSS query also covers
              // the case where the preference flips after mount.
              '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
            }}
          >
            {[...ids, ...ids].map((id, i) => (
              <CompanyLogo
                key={`${id}-${i}`}
                companyId={id}
                displayName={getCompanyById(id)?.name ?? id}
                size={tileSize}
                decorative={i >= ids.length}
              />
            ))}
          </Box>
        </Box>
      ))}
    </Box>
  );
}
