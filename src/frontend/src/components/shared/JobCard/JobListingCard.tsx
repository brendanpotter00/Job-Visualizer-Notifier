import { Card, CardContent, Typography, Chip, Stack, Link, Button } from '@mui/material';
import { OpenInNew } from '@mui/icons-material';
import type { Job } from '../../../types';
import { useJobMetadata } from './useJobMetadata.ts';
import { JobChipsSection } from './JobChipsSection.tsx';
import { CompanyJobHeader } from './CompanyJobHeader.tsx';
import { CARD_HOVER_SX, CARD_VARIANT } from './jobCardStyles.ts';
import { getCompanyById } from '../../../config/companies.ts';
import { RESPONSIVE } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';

interface JobListingCardProps {
  job: Job;
}

/**
 * Whether the location chips already say the job is remote, in which case the
 * standalone "Remote" chip is dropped.
 *
 * `isRemote` and the location tags are independent fields, so a remote job
 * routinely carries a `kind: 'remote'` canonical tag ("Remote (US)") as well.
 * That double-billing was invisible while the two chips sat in different rows;
 * side by side it reads as a rendering bug ("Remote (US)" "Remote"), and ~450
 * open jobs are in that state today — 11 of them with a canonical tag labelled
 * exactly "Remote".
 *
 * The raw-string branch mirrors the chip fallback below: when there are no
 * canonical tags we render `job.location` verbatim, so a scraped
 * "Remote - Worldwide" is the same duplicate with no `kind` to test.
 */
function locationAlreadySaysRemote(job: Job): boolean {
  if (job.locations && job.locations.length > 0) {
    return job.locations.some((loc) => loc.kind === 'remote');
  }
  return /remote/i.test(job.location ?? '');
}

/**
 * Unified job posting card used by both the company hiring-trend page and the
 * Recent Jobs page, so the two lists render identical cards.
 *
 * Layout: a 44px company logo spans the two-line [company name, job title]
 * header block on the left, with a black rounded "Apply" button in the top
 * right. The whole card is clickable (opens the posting in a new tab); the
 * Apply button and the LinkedIn recruiter link stop propagation so they don't
 * double-trigger the card click.
 *
 * The logo + name half of the header lives in `CompanyJobHeader`, which resolves
 * `job.company` across BOTH id namespaces (the compile-time list and the
 * signed-in user's own boards). The recruiter LinkedIn URL stays a static-list
 * lookup: it is hand-curated per first-party company and a user-added board
 * never has one.
 */
export function JobListingCard({ job }: JobListingCardProps) {
  // "Posted X ago" is keyed off `firstSeenAt` (when WE first saw the listing), so
  // the label matches the recency sort/time-window/enricher-claim ordering. Using
  // the ATS posted date (`createdAt` = postedOn || firstSeenAt) instead made the
  // top-ranked recent-page cards read "Posted 3 months ago" on reposted listings
  // whose postedOn is stale — inconsistent with why they rank first.
  const { postedAgo } = useJobMetadata(job.firstSeenAt);
  const isMobile = useIsMobile();
  const recruiterLinkedInUrl = getCompanyById(job.company)?.recruiterLinkedInUrl;

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
          // Shrink every chip (location, employment-type, remote/enrichment) on mobile
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
            <CompanyJobHeader
              companyId={job.company}
              title={job.title}
              logoSize={isMobile ? RESPONSIVE.logoSize.compact : RESPONSIVE.logoSize.default}
            />
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

          {/* Location + Remote + employment-type chips. Remote sits next to the
              location chips (not with the enrichment chips below) because it
              answers the same question they do: where is this job? */}
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
            {job.isRemote && !locationAlreadySaysRemote(job) && (
              <Chip label="Remote" size="small" color="primary" variant="outlined" />
            )}
            {job.employmentType && (
              <Chip label={job.employmentType} size="small" variant="outlined" />
            )}
          </Stack>

          <JobChipsSection category={job.category} level={job.level} />

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
              DM the hiring team on LinkedIn
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
