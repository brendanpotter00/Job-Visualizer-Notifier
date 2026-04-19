import { Box, Typography, Button, Paper, Alert } from '@mui/material';
import { ErrorOutline, Refresh } from '@mui/icons-material';

/**
 * Props for {@link ErrorDisplay}. Modeled as a discriminated union so the
 * `inline` variant (renders an MUI `Alert`) cannot receive `title` or
 * `description` — those props would be silently dropped by the inline render
 * path. TypeScript rejects the invalid combination at the call site.
 */
export type ErrorDisplayProps =
  | {
      /** Render as an inline `Alert` (no title, no description). */
      inline: true;
      /** Error message to display. */
      message: string;
      /** Optional retry callback. */
      onRetry?: () => void;
    }
  | {
      /** Render as the full-card variant. `inline` may be omitted or `false`. */
      inline?: false;
      /** Error message to display. */
      message: string;
      /** Optional title (defaults to "Error"). Card variant only. */
      title?: string;
      /** Optional subtitle/description. Card variant only. */
      description?: string;
      /** Optional retry callback. */
      onRetry?: () => void;
    };

/**
 * Reusable error display component.
 * Shows error messages with optional retry functionality.
 */
export function ErrorDisplay(props: ErrorDisplayProps) {
  if (props.inline) {
    const { message, onRetry } = props;
    return (
      <Alert
        severity="error"
        action={
          onRetry ? (
            <Button color="inherit" size="small" onClick={onRetry} startIcon={<Refresh />}>
              Retry
            </Button>
          ) : undefined
        }
      >
        {message}
      </Alert>
    );
  }

  const { message, title = 'Error', description, onRetry } = props;

  return (
    <Paper
      sx={{
        p: { xs: 3, sm: 4 },
        textAlign: 'center',
        bgcolor: 'background.paper',
      }}
    >
      <ErrorOutline sx={{ fontSize: 48, color: 'error.main', mb: 2 }} />
      <Typography variant="h5" gutterBottom>
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {description}
        </Typography>
      )}
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        {message}
      </Typography>
      {onRetry && (
        <Button variant="contained" onClick={onRetry} startIcon={<Refresh />}>
          Try Again
        </Button>
      )}
    </Paper>
  );
}

/**
 * Network error display with specific messaging
 */
export function NetworkErrorDisplay({ onRetry }: { onRetry?: () => void }) {
  return (
    <ErrorDisplay
      title="Network Error"
      message="Unable to connect to the server. Please check your internet connection and try again."
      description="This may be a temporary issue. The server might be down or your connection might be unstable."
      onRetry={onRetry}
    />
  );
}

/**
 * Empty state display (not an error, but similar pattern)
 */
export function EmptyStateDisplay({
  title = 'No Results',
  message = 'No data to display',
  icon,
}: {
  title?: string;
  message?: string;
  icon?: React.ReactNode;
}) {
  return (
    <Box
      sx={{
        textAlign: 'center',
        py: 6,
      }}
    >
      {icon || <ErrorOutline sx={{ fontSize: 48, color: 'text.disabled', mb: 2 }} />}
      <Typography variant="h6" color="text.secondary" gutterBottom>
        {title}
      </Typography>
      <Typography variant="body2" color="text.disabled">
        {message}
      </Typography>
    </Box>
  );
}

/**
 * Named alias of {@link ErrorDisplay}. Prefer `ErrorState` at call sites for
 * symmetry with `LoadingState` / `EmptyState`.
 */
export { ErrorDisplay as ErrorState };

/**
 * Named alias of {@link EmptyStateDisplay}. Prefer `EmptyState` at call sites for
 * symmetry with `LoadingState` / `ErrorState`.
 */
export { EmptyStateDisplay as EmptyState };
