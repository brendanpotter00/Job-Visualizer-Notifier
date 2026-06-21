import { useState } from 'react';
import { Box } from '@mui/material';
import { getCompanyLogoUrl } from '../../../config/companies.ts';

interface CompanyLogoProps {
  /** Company id (matches `job.company` / `Company.id`); used to resolve the icon URL. */
  companyId: string;
  /** Display name, used for the `alt`/`aria-label` and the initials fallback. */
  companyName?: string;
  /** Square edge length in pixels. */
  size?: number;
  /**
   * Treat the logo as decorative — set this when the company name is already
   * shown as adjacent visible text (e.g. RecentJobCard), so assistive tech
   * doesn't announce the name twice.
   */
  decorative?: boolean;
}

/**
 * Square brand icon for a company, filling a rounded tile edge-to-edge.
 *
 * The icon art fills the tile (no inset padding) so the brand-color icon assets
 * read as solid tiles; the tile's `background.paper` only shows through for a
 * transparent mark or behind the initials fallback. `overflow: 'hidden'` plus
 * `borderRadius` clips the square art to the tile's rounded corners.
 *
 * Uses a plain lazy `<img>` (not MUI `Avatar`) so that `loading="lazy"` actually
 * defers off-screen fetches, and so the fallback is driven by the rendered
 * element's own `onError`: when the icon is missing or fails to load (e.g. a
 * company added to the backend before its logo file is committed) the tile shows
 * the company's first initial instead of a broken image.
 */
export function CompanyLogo({
  companyId,
  companyName,
  size = 28,
  decorative = false,
}: CompanyLogoProps) {
  const [failed, setFailed] = useState(false);
  const label = companyName ?? companyId;
  const initial = label.trim().charAt(0).toUpperCase();

  const tileSx = {
    width: size,
    height: size,
    flexShrink: 0,
    borderRadius: 1,
    border: '1px solid',
    borderColor: 'divider',
    bgcolor: 'background.paper',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  } as const;

  if (failed) {
    return (
      <Box
        sx={{ ...tileSx, color: 'text.secondary', fontSize: size * 0.45, fontWeight: 600 }}
        role={decorative ? undefined : 'img'}
        aria-label={decorative ? undefined : label}
        aria-hidden={decorative ? true : undefined}
      >
        {initial}
      </Box>
    );
  }

  return (
    <Box sx={tileSx}>
      <Box
        component="img"
        src={getCompanyLogoUrl(companyId)}
        alt={decorative ? '' : label}
        loading="lazy"
        onError={() => setFailed(true)}
        sx={{ width: '100%', height: '100%', objectFit: 'contain', p: 0 }}
      />
    </Box>
  );
}
