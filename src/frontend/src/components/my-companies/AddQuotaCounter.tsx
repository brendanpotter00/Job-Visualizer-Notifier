import Typography from '@mui/material/Typography';
import { addsRemaining, type AddQuota } from '../../features/userCompanies/userCompaniesApi';

interface AddQuotaCounterProps {
  /** From `GET /api/users/companies`. Absent while it loads, or from an older server. */
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
 * Renders NOTHING when there is no quota on the payload at all — the server sends none
 * to an admin (who is exempt from the cap) and none from a build older than this
 * feature. Neither "there is no cap for you" nor "we don't know" is a number, so there
 * is nothing honest to put on the line.
 *
 * `limit === 0` is NOT that case. Zero is a cap that is in force and allows no adds,
 * so this reads "0 of 0 adds left this month" in the error colour and the submit is
 * disabled — the same treatment as a spent month, because it is the same fact.
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
