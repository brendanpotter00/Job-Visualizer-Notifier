import {
  Dialog,
  DialogTitle,
  DialogContent,
  IconButton,
  Typography,
  Box,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { format } from 'date-fns';
import { useMemo } from 'react';
import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { closeGraphModal } from '../../../features/ui/uiSlice';
import { JobList } from '../../companies-page/JobList/JobList.tsx';
import { SignInOverlay } from '../../shared/SignInOverlay.tsx';
import { selectCurrentCompanyJobsRtk } from '../../../features/jobs/jobsSelectors';
import { useAuth } from '../../../features/auth/useAuth.ts';
import { SIGN_IN_OVERLAY_CONFIG } from '../../../constants/ui.ts';

/**
 * Modal displaying jobs from a clicked time bucket.
 *
 * When the user is signed out, the list is capped at
 * SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT and a SignInOverlay is rendered
 * inside the dialog. MUI Dialog uses a `Paper` surface, so the overlay uses
 * the `'paper'` background variant to match.
 */
export function BucketJobsModal() {
  const dispatch = useAppDispatch();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));

  const { open, bucketStart, bucketEnd, filteredJobIds } = useAppSelector(
    (state) => state.ui.graphModal
  );
  const allJobs = useAppSelector(selectCurrentCompanyJobsRtk);
  const { isAuthenticated, isEnabled } = useAuth();

  const handleClose = () => {
    dispatch(closeGraphModal());
  };

  // Filter jobs to only those in this bucket (memoized to prevent unnecessary filtering)
  const bucketJobs = useMemo(
    () => allJobs.filter((job) => filteredJobIds?.includes(job.id)),
    [allJobs, filteredJobIds]
  );

  const isSignedOut = isEnabled && !isAuthenticated;
  const visibleJobs = isSignedOut
    ? bucketJobs.slice(0, SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT)
    : bucketJobs;
  const showSignInOverlay =
    isSignedOut && bucketJobs.length > SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT;

  // Don't render if modal is not open or data is missing
  if (!open || !bucketStart || !bucketEnd) {
    return null;
  }

  const startDate = new Date(bucketStart);
  const endDate = new Date(bucketEnd);

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullScreen={isMobile}
      maxWidth="md"
      fullWidth
      aria-labelledby="bucket-modal-title"
    >
      <DialogTitle id="bucket-modal-title">
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Box>
            <Typography variant="h6" component="div">
              Jobs Posted
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {format(startDate, 'MMM d, yyyy HH:mm')} - {format(endDate, 'HH:mm')}
            </Typography>
          </Box>
          <IconButton aria-label="close" onClick={handleClose} sx={{ color: 'text.secondary' }}>
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>
      <DialogContent>
        <Box
          sx={{
            position: 'relative',
            ...(showSignInOverlay && { overflow: 'hidden' }),
          }}
        >
          <JobList jobs={visibleJobs} isLoading={false} />
          {showSignInOverlay && <SignInOverlay background="paper" page="bucket_modal" />}
        </Box>
      </DialogContent>
    </Dialog>
  );
}
