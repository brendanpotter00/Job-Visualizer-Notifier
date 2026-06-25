import {
  Dialog,
  DialogTitle,
  DialogContent,
  IconButton,
  Typography,
  Box,
  List,
  ListItem,
  ListItemText,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { format } from 'date-fns';
import { useGetUserVisitsQuery, type AdminUserRow } from '../../../features/admin/adminApi';
import { LoadingState } from '../../../components/shared/LoadingIndicator';
import { ErrorState } from '../../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../../lib/errors';

interface UserVisitsModalProps {
  /** The user whose visit history to show. */
  user: AdminUserRow;
  /** Close handler — the parent unmounts the modal. */
  onClose: () => void;
}

/**
 * Lists a single user's individual visit timestamps, most-recent first.
 *
 * Mounted conditionally by `UserRosterTable` only when a Visits cell is
 * clicked, so the `useGetUserVisitsQuery` fetch fires exactly once per open
 * and RTK Query caches the result per `userId`.
 *
 * The list can be SHORTER than `visitCount`: per-visit history only began when
 * the backend started logging individual visits, so pre-launch visits beyond
 * the single seeded `last_visit_at` have no timestamp row. The modal surfaces
 * that count-vs-history gap with a caption rather than hiding it.
 */
export function UserVisitsModal({ user, onClose }: UserVisitsModalProps) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
  const { data, isLoading, error } = useGetUserVisitsQuery({ userId: user.id });

  const historyCount = data?.visits.length ?? 0;
  // Fall back to the row's own visitCount until the fetch resolves so the
  // title shows the right total immediately.
  const totalCount = data?.totalVisitCount ?? user.visitCount;
  const hasGap = !isLoading && !error && historyCount < totalCount;

  return (
    <Dialog
      open
      onClose={onClose}
      fullScreen={isMobile}
      maxWidth="sm"
      fullWidth
      aria-labelledby="user-visits-modal-title"
    >
      <DialogTitle id="user-visits-modal-title">
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Box>
            <Typography variant="h6" component="div">
              Visit history
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {user.displayName ?? user.email} · {totalCount.toLocaleString()} total
            </Typography>
          </Box>
          <IconButton aria-label="close" onClick={onClose} sx={{ color: 'text.secondary' }}>
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>
      <DialogContent>
        {isLoading ? (
          <LoadingState minHeight={160} caption="Loading visit history…" />
        ) : error ? (
          <ErrorState inline message={extractErrorMessage(error, 'Failed to load visit history')} />
        ) : historyCount === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
            No individual visit timestamps recorded yet. Per-visit history began when this feature
            shipped; earlier visits are counted in the total but have no recorded timestamp.
          </Typography>
        ) : (
          <>
            {hasGap && (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: 'block', mb: 1 }}
              >
                Showing {historyCount.toLocaleString()} of {totalCount.toLocaleString()} visits.
                Visits before this feature shipped have no recorded timestamp
                {data?.truncated ? ' (and the list is capped at the 500 most recent)' : ''}.
              </Typography>
            )}
            <List dense disablePadding>
              {data!.visits.map((iso, i) => (
                <ListItem key={`${iso}-${i}`} divider>
                  <ListItemText primary={format(new Date(iso), 'MMM d, yyyy h:mm:ss a')} />
                </ListItem>
              ))}
            </List>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
