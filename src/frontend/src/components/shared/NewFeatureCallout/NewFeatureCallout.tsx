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
  const expiryMs = parseExpiry(expiresAt);
  const alreadyExpired =
    typeof window === 'undefined' || expiryMs === null || Date.now() >= expiryMs;

  // Seed from storage lazily so the very first render already reflects the
  // persisted dismissal. When the callout is already expired we skip the
  // storage read entirely (the expired-path test spies on getItem).
  const [dismissed, setDismissed] = useState<boolean>(() =>
    alreadyExpired ? false : isDismissed(storageKey)
  );

  if (alreadyExpired || dismissed) {
    return null;
  }

  const handleDismiss = (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    markDismissed(storageKey);
    setDismissed(true);
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
