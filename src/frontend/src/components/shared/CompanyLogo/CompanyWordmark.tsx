import { useState } from 'react';
import { Box, Typography } from '@mui/material';
import { getCompanyWordmarkUrl } from '../../../config/companies.ts';

interface CompanyWordmarkProps {
  /** Company id (matches `Company.id`); used to resolve the wordmark URL. */
  companyId: string;
  /** Display name, used for the `alt`/heading name and the text fallback. */
  displayName: string;
  /** Rendered wordmark height in pixels. */
  height?: number;
}

/**
 * Company brand wordmark, used as the heading of a curated company card.
 *
 * Renders the wide brand wordmark (which already contains the company name) as
 * the card's `<h3>`. The heading's accessible name comes from the image `alt`,
 * so the company name is still exposed to assistive tech — and the directory's
 * name-based search keeps working because it filters the data, not the DOM.
 *
 * When the wordmark image is missing or fails to load (e.g. a company added to
 * the backend before its wordmark file is committed) it falls back to the plain
 * text name, so the card never shows a broken image.
 */
export function CompanyWordmark({ companyId, displayName, height = 32 }: CompanyWordmarkProps) {
  const [failed, setFailed] = useState(false);

  return (
    <Typography
      variant="h6"
      component="h3"
      sx={{ display: 'flex', alignItems: 'center', minHeight: height + 8, mb: 1 }}
    >
      {failed ? (
        displayName
      ) : (
        <Box
          component="img"
          src={getCompanyWordmarkUrl(companyId)}
          alt={displayName}
          loading="lazy"
          onError={() => setFailed(true)}
          sx={{
            height,
            width: 'auto',
            maxWidth: '100%',
            objectFit: 'contain',
            objectPosition: 'left center',
          }}
        />
      )}
    </Typography>
  );
}
