import { useState, type MouseEvent } from 'react';
import { Paper, Typography, IconButton, ButtonBase } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { isDismissed, markDismissed } from './dismissalStorage';

export interface NewFeatureCalloutProps {
  storageKey: string;
  expiresAt: Date | string;
  label: string;
  onClick?: () => void;
  placement?: 'desktop-right-mobile-below';
  'data-testid'?: string;
}

function parseExpiry(expiresAt: Date | string): number | null {
  const d = expiresAt instanceof Date ? expiresAt : new Date(expiresAt);
  const t = d.getTime();
  return Number.isFinite(t) ? t : null;
}

export function NewFeatureCallout({
  storageKey,
  expiresAt,
  label,
  onClick,
  placement: _placement = 'desktop-right-mobile-below',
  'data-testid': testId,
}: NewFeatureCalloutProps) {
  // All "should I render" checks live inside the useState initializer so the
  // render body stays pure (React's `react-hooks/purity` rule flags `Date.now()`
  // called during render). The initializer runs once per mount, which is the
  // right granularity: `expiresAt` is stable per mount and the expiry check
  // does not need to refresh on every re-render.
  const [hidden, setHidden] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    const expiryMs = parseExpiry(expiresAt);
    if (expiryMs === null || Date.now() >= expiryMs) return true;
    return isDismissed(storageKey);
  });

  if (hidden) {
    return null;
  }

  const handleDismiss = (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    markDismissed(storageKey);
    setHidden(true);
  };

  const body = (
    <Typography variant="caption" component="span" sx={{ lineHeight: 1, whiteSpace: 'nowrap' }}>
      {label}
    </Typography>
  );

  return (
    <Paper
      elevation={2}
      role="status"
      data-testid={testId}
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.5,
        px: 1,
        py: 0.25,
        borderRadius: '999px',
        bgcolor: 'primary.light',
        color: 'primary.contrastText',
      }}
    >
      {onClick ? (
        <ButtonBase
          onClick={onClick}
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            borderRadius: '999px',
            px: 0.5,
          }}
        >
          {body}
        </ButtonBase>
      ) : (
        body
      )}
      <IconButton
        aria-label="Dismiss"
        size="small"
        onClick={handleDismiss}
        sx={{ color: 'inherit', p: 0.25 }}
      >
        <CloseIcon fontSize="inherit" />
      </IconButton>
    </Paper>
  );
}
