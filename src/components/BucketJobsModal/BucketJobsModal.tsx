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
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { closeGraphModal } from '../../features/ui/uiSlice';
import { JobList } from '../JobList/JobList';
import { selectCurrentCompanyJobs } from '../../features/jobs/jobsSelectors';

/**
 * Modal displaying jobs from a clicked time bucket
 */
export function BucketJobsModal() {
  const dispatch = useAppDispatch();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));

  const { open, bucketStart, bucketEnd, filteredJobIds } = useAppSelector(
    (state) => state.ui.graphModal
  );
  const allJobs = useAppSelector(selectCurrentCompanyJobs);

  const handleClose = () => {
    dispatch(closeGraphModal());
  };

  // Don't render if modal is not open or data is missing
  if (!open || !bucketStart || !bucketEnd) {
    return null;
  }

  // Filter jobs to only those in this bucket
  const bucketJobs = allJobs.filter((job) => filteredJobIds?.includes(job.id));

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
        <JobList jobs={bucketJobs} isLoading={false} />
      </DialogContent>
    </Dialog>
  );
}
