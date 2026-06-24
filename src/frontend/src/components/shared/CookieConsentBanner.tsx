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
        left: 0,
        zIndex: 1400,
        p: { xs: 1.5, sm: 2 },
        pointerEvents: 'none',
      }}
    >
      <Paper
        elevation={4}
        sx={{
          maxWidth: 280,
          p: { xs: 2, sm: 2.5 },
          display: 'flex',
          flexDirection: 'column',
          gap: 1.5,
          pointerEvents: 'auto',
          borderRadius: 2,
          border: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Typography variant="body2" color="text.secondary">
          We use analytics cookies to understand how you use this site. Decline if you prefer.
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button size="small" variant="contained" onClick={handleAccept} fullWidth>
            Accept
          </Button>
          <Button size="small" variant="outlined" onClick={handleDecline} fullWidth>
            Decline
          </Button>
        </Box>
      </Paper>
    </Box>
  );
}
