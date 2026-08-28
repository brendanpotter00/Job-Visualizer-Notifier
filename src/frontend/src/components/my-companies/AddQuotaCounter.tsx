import Typography from '@mui/material/Typography';
import { addsRemaining, type AddQuota } from '../../features/userCompanies/userCompaniesApi';

interface AddQuotaCounterProps {
  /** From `GET /api/users/companies`. Absent while it loads, or when uncapped. */
  quota: AddQuota | null | undefined;
}

/**
 * "17 of 20 adds left this month." — the entire explanation of the monthly cap.
 *
 * ONE LINE UNDER THE PAGE TITLE, and deliberately not an alert, a banner, or a
 * warning that appears when the number gets low. A counter that is always there is
 * a fact the reader can check whenever they care; a notice that shows up at 3 left
 * is an interruption that has to be dismissed, and it teaches nothing the counter
 * did not already say. At zero this line reads "0 of 20 adds left this month" and
 * the submit is disabled — those two together are the whole explanation, which is
 * why there is no extra copy for the exhausted state.
 *
 * Renders NOTHING when there is no cap to report: no quota on the payload (a server
 * older than this feature), or `limit === 0` (the cap is switched off). A counter
 * saying "unlimited" would be a line of chrome about a rule that is not in force.
 */
export function AddQuotaCounter({ quota }: AddQuotaCounterProps) {
  const remaining = addsRemaining(quota);
  if (remaining === null || !quota) return null;

  return (
    <Typography
      variant="body2"
      color={remaining === 0 ? 'error.main' : 'text.secondary'}
      data-testid="add-quota-counter"
      sx={{ mb: 2 }}
    >
      {remaining} of {quota.limit} adds left this month
    </Typography>
  );
}
