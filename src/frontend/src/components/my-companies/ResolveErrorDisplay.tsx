import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Typography from '@mui/material/Typography';
import { describeResolveError } from '../../features/userCompanies/resolveErrors';

interface ResolveErrorDisplayProps {
  /** The raw rejection from the resolve mutation. */
  error: unknown;
}

/**
 * Renders a failed resolve. All copy decisions live in `resolveErrors.ts`; this
 * component only lays them out.
 */
export function ResolveErrorDisplay({ error }: ResolveErrorDisplayProps) {
  const { title, detail, reasonCode } = describeResolveError(error);

  return (
    <Alert severity="error" data-testid="resolve-error">
      <AlertTitle>{title}</AlertTitle>
      <Typography variant="body2">{detail}</Typography>
      {reasonCode && (
        // Kept visible (not just in a console log) so a user reporting a
        // problem can quote the exact code from a screenshot.
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: 'block', mt: 1, fontFamily: 'monospace' }}
        >
          {reasonCode}
        </Typography>
      )}
    </Alert>
  );
}
