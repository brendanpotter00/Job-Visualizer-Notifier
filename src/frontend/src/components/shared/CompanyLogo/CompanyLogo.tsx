import { Avatar } from '@mui/material';
import { getCompanyLogoUrl } from '../../../config/companies.ts';

interface CompanyLogoProps {
  /** Company id (matches `job.company` / `Company.id`); used to resolve the icon URL. */
  companyId: string;
  /** Display name, used for the `alt` text and the initials fallback. */
  companyName?: string;
  /** Square edge length in pixels. */
  size?: number;
}

/**
 * Square brand icon for a company, rendered on a subtle tile.
 *
 * Wraps MUI's `Avatar`: when the logo image is missing or fails to load (e.g. a
 * company added to the backend before its logo file is committed), `Avatar`
 * automatically renders the `children` instead — here the company's first
 * initial — so callers get a meaningful fallback rather than a broken image.
 */
export function CompanyLogo({ companyId, companyName, size = 28 }: CompanyLogoProps) {
  const label = companyName ?? companyId;
  const initial = label.trim().charAt(0).toUpperCase();

  return (
    <Avatar
      src={getCompanyLogoUrl(companyId)}
      alt={label}
      variant="rounded"
      slotProps={{ img: { loading: 'lazy' } }}
      sx={{
        width: size,
        height: size,
        flexShrink: 0,
        bgcolor: 'background.paper',
        color: 'text.secondary',
        border: '1px solid',
        borderColor: 'divider',
        fontSize: size * 0.45,
        fontWeight: 600,
        '& .MuiAvatar-img': { objectFit: 'contain', p: '12%' },
      }}
    >
      {initial}
    </Avatar>
  );
}
