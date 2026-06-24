import { useState } from 'react';
import { Box, Button, Paper, Typography } from '@mui/material';
import { POSTHOG_CONFIG } from '../../config/posthog';
import {
  acceptTracking,
  declineTracking,
  getConsentStatus,
  type ConsentStatus,
} from '../../lib/posthogConsent';

export function CookieConsentBanner() {
  const [status, setStatus] = useState<ConsentStatus>(getConsentStatus);

  if (!POSTHOG_CONFIG.isEnabled || status !== 'pending') return null;

  const handleAccept = () => {
    acceptTracking();
    setStatus('granted');
  };

  const handleDecline = () => {
    declineTracking();
    setStatus('denied');
  };

  return (
    <Box
      sx={{
        position: 'fixed',
        bottom: 0,
        right: 0,
        zIndex: 1400,
        p: { xs: 1.5, sm: 2 },
        pointerEvents: 'none',
      }}
    >
      <Paper
        elevation={4}
        sx={{
          maxWidth: 320,
          p: { xs: 2, sm: 2.5 },
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: 2,
          pointerEvents: 'auto',
          borderRadius: 2,
          border: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          We use analytics cookies to understand how you use this site. Decline if you prefer.
        </Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, flexShrink: 0 }}>
          <Button size="small" variant="contained" onClick={handleAccept}>
            Accept
          </Button>
          <Button size="small" variant="outlined" onClick={handleDecline}>
            Decline
          </Button>
        </Box>
      </Paper>
    </Box>
  );
}
