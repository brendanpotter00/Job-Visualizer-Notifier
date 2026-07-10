import { Card, CardContent, Typography, Chip, Stack, Link, Box, Button } from '@mui/material';
import { OpenInNew } from '@mui/icons-material';
import type { Job } from '../../../types';
import { useJobMetadata } from './useJobMetadata.ts';
import { JobChipsSection } from './JobChipsSection.tsx';
import { CARD_HOVER_SX, CARD_VARIANT } from './jobCardStyles.ts';
import { CompanyLogo } from '../CompanyLogo/CompanyLogo.tsx';
import { getCompanyById } from '../../../config/companies.ts';
import { RESPONSIVE } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';

interface JobListingCardProps {
  job: Job;
}

/**
 * Unified job posting card used by both the company hiring-trend page and the
 * Recent Jobs page, so the two lists render identical cards.
 *
 * Layout: a 44px company logo spans the two-line [company name, job title]
 * header block on the left, with a black rounded "Apply" button in the top
 * right. The whole card is clickable (opens the posting in a new tab); the
 * Apply button and the LinkedIn recruiter link stop propagation so they don't
 * double-trigger the card click. Company name and the recruiter LinkedIn URL
 * are resolved from the company config via `job.company`.
 */
export function JobListingCard({ job }: JobListingCardProps) {
  const { postedAgo } = useJobMetadata(job.createdAt);
  const isMobile = useIsMobile();
  const company = getCompanyById(job.company);
  const companyName = company?.name ?? job.company;
  const recruiterLinkedInUrl = company?.recruiterLinkedInUrl;

  const openJob = () => {
    window.open(job.url, '_blank', 'noopener,noreferrer');
  };
  const stop = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <Card
      variant={CARD_VARIANT}
      sx={{ mb: RESPONSIVE.spacing.cardMarginB, cursor: 'pointer', ...CARD_HOVER_SX }}
      onClick={openJob}
    >
      <CardContent
        sx={{
          p: RESPONSIVE.spacing.cardPadding,
          '&:last-child': { pb: RESPONSIVE.spacing.cardPaddingBottom },
          // Shrink every chip (location, employment-type, dept/remote) on mobile
          // only. Gated on isMobile so desktop keeps MUI's defaults untouched:
          // MUI's small-chip label padding is variant-dependent, so restating a
          // single sm value would regress some variant — we override nothing on
          // desktop instead. height is a sizing prop (px); label padding is a
          // string px to avoid the spacing-system x8 multiply.
          ...(isMobile && {
            '& .MuiChip-root': { height: RESPONSIVE.jobCard.chipHeight },
            '& .MuiChip-label': {
              fontSize: RESPONSIVE.jobCard.chipFontSize,
              paddingLeft: RESPONSIVE.jobCard.chipLabelPaddingX,
              paddingRight: RESPONSIVE.jobCard.chipLabelPaddingX,
            },
          }),
        }}
      >
        <Stack spacing={RESPONSIVE.spacing.cardStackSpacing}>
          {/* Header: logo spanning company name + title, Apply button top-right */}
          <Stack
            direction="row"
            spacing={1.5}
            justifyContent="space-between"
            alignItems="flex-start"
          >
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
              <CompanyLogo
                companyId={job.company}
                displayName={companyName}
                size={isMobile ? RESPONSIVE.logoSize.compact : RESPONSIVE.logoSize.default}
                decorative
              />
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="subtitle2" color="text.secondary" fontWeight="bold">
                  {companyName}
                </Typography>
                <Typography variant="h6" component="h3" sx={{ fontSize: RESPONSIVE.fontSize.cardTitle }}>
                  {job.title}
                </Typography>
              </Box>
            </Stack>
            <Button
              component="a"
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={stop}
              variant="contained"
              size="small"
              sx={{
                flexShrink: 0,
                borderRadius: 2,
                textTransform: 'none',
                // Shrink the Apply button on mobile only (it otherwise forces the
                // header to the theme's 44px button floor). Gated on isMobile so
                // desktop keeps MUI's small-button defaults byte-for-byte. Kept
                // >= 36px to stay an easy tap target. py/px are string px.
                ...(isMobile && {
                  minHeight: RESPONSIVE.jobCard.applyMinHeight,
                  fontSize: RESPONSIVE.jobCard.applyFontSize,
                  py: RESPONSIVE.jobCard.applyPaddingY,
                  px: RESPONSIVE.jobCard.applyPaddingX,
                }),
                bgcolor: 'common.black',
                color: 'common.white',
                '&:hover': { bgcolor: 'grey.900' },
              }}
            >
              Apply
            </Button>
          </Stack>

          {/* Location + employment-type chips */}
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {job.locations && job.locations.length > 0
              ? job.locations.map((loc) => (
                  <Chip
                    key={loc.canonicalName}
                    label={loc.canonicalName}
                    size="small"
                    variant="outlined"
                  />
                ))
              : job.location && <Chip label={job.location} size="small" variant="outlined" />}
            {job.employmentType && (
              <Chip label={job.employmentType} size="small" variant="outlined" />
            )}
          </Stack>

          <JobChipsSection
            department={job.department}
            isRemote={job.isRemote}
            category={job.category}
            level={job.level}
            enrichmentTags={job.enrichmentTags}
          />

          {/* LinkedIn recruiter link */}
          {recruiterLinkedInUrl && (
            <Link
              href={recruiterLinkedInUrl}
              target="_blank"
              rel="noopener noreferrer"
              variant="caption"
              color="primary"
              underline="hover"
              onClick={stop}
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 0.5,
                cursor: 'pointer',
              }}
            >
              Find recruiter and hiring manager posts on LinkedIn
              <OpenInNew sx={{ fontSize: '0.875rem' }} />
            </Link>
          )}

          {/* Posted date */}
          <Typography variant="caption" color="text.secondary">
            Posted {postedAgo}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  );
}
