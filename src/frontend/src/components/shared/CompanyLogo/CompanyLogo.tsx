import { useState } from 'react';
import { Box } from '@mui/material';
import ApartmentRoundedIcon from '@mui/icons-material/ApartmentRounded';
import { getCompanyLogoUrl } from '../../../config/companies.ts';

/**
 * Accessible name for a tile we can't name. Used for the `alt`/`aria-label`
 * when the caller gives no `displayName` — deliberately generic, because the
 * only other string available is the raw company id, and for a user-added board
 * that is an opaque internal handle (`u-ajhs85a7y0`), not something to announce.
 */
const UNNAMED_COMPANY_LABEL = 'Company';

interface CompanyLogoProps {
  /** Company id (matches `job.company` / `Company.id`); used to resolve the icon URL. */
  companyId: string;
  /**
   * Display name, used for the `alt`/`aria-label` and the initials fallback.
   *
   * OMIT it when the caller could not resolve a human name for this company.
   * User-added boards are keyed by an opaque `u-<base36>` runtime id, and
   * defaulting the label to that id put a literal "U" tile on every job card of
   * a company the user added themselves. With no name the tile falls back to a
   * neutral company glyph instead, and the id is never rendered or announced.
   */
  displayName?: string;
  /**
   * Whether committed brand art can exist for this id. Icons live at
   * `public/logos/icons/<id>.png` and are committed per first-party company, so
   * a board the user added themselves — keyed by a runtime id — can never have
   * one. Pass `false` there to skip a request that is guaranteed to 404 and go
   * straight to the neutral tile.
   *
   * It also picks the fallback: the initial stands in for art we expected and
   * failed to load, while the glyph stands in for a company we hold no art for.
   * That distinction is why a discovered board shows the generic mark and not
   * the first letter of "www.janestreet.com".
   */
  hasBrandArt?: boolean;
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
 * Square brand icon for a company, rendered inside a rounded tile.
 *
 * The icon art is scaled to fit the tile (`objectFit: 'contain'`, no inset
 * padding); square brand-color assets read as solid tiles, while the tile's
 * `background.paper` shows through any letterboxing for off-ratio or transparent
 * marks and behind the initials fallback. `overflow: 'hidden'` plus `borderRadius`
 * clips the art to the tile's rounded corners.
 *
 * Uses a plain lazy `<img>` so that `loading="lazy"` defers off-screen fetches and
 * the fallback is driven by the rendered element's own `onError`: when the icon is
 * missing or fails to load (e.g. a company added to the backend before its logo
 * file is committed) the tile degrades to the company's first initial instead of
 * showing a broken image. Companies we hold no art for at all skip the request
 * and render a neutral building glyph — see `hasBrandArt`.
 */
export function CompanyLogo({
  companyId,
  displayName,
  hasBrandArt = true,
  size = 28,
  decorative = false,
}: CompanyLogoProps) {
  const [failed, setFailed] = useState(false);
  // Reset the failed state if the instance is reused for a different company
  // (e.g. in a recycled/virtualized list), so a prior load failure doesn't
  // suppress an icon that does exist for the new id. Adjusting state during
  // render (rather than in an effect) avoids an extra cascading re-render.
  const [trackedId, setTrackedId] = useState(companyId);
  if (companyId !== trackedId) {
    setTrackedId(companyId);
    setFailed(false);
  }
  // A whitespace-only name counts as no name: a blank `display_name` is a data
  // gap, and trimming it to "" would render an empty tile with an empty alt.
  const name = displayName?.trim() || undefined;
  const label = name ?? UNNAMED_COMPANY_LABEL;

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

  if (failed || !hasBrandArt) {
    return (
      <Box
        sx={{ ...tileSx, color: 'text.secondary', fontSize: size * 0.45, fontWeight: 600 }}
        role={decorative ? undefined : 'img'}
        aria-label={decorative ? undefined : label}
        aria-hidden={decorative ? true : undefined}
      >
        {hasBrandArt && name ? (
          name.charAt(0).toUpperCase()
        ) : (
          // Quieter than an initial on purpose: this is a placeholder for art we
          // don't have, not content, so it recedes to `text.disabled`.
          <ApartmentRoundedIcon sx={{ fontSize: size * 0.55, color: 'text.disabled' }} />
        )}
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
