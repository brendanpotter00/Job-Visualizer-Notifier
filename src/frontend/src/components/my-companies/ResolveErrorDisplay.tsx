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
 *
 * Title + one plain sentence, and nothing else. The raw `reasonCode` used to be
 * printed underneath in monospace so a screenshot could be quoted back at us — but
 * every code we recognise is already spelled out in the sentence above it, and the
 * ones we do not recognise carry `(code: …)` inside that sentence from
 * `describeResolveError`. So the line only ever repeated the message in machine
 * language, on a page whose problem was that it says everything twice.
 */
export function ResolveErrorDisplay({ error }: ResolveErrorDisplayProps) {
  const { title, detail } = describeResolveError(error);

  return (
    <Alert severity="error" data-testid="resolve-error">
      <AlertTitle>{title}</AlertTitle>
      <Typography variant="body2">{detail}</Typography>
    </Alert>
  );
}
