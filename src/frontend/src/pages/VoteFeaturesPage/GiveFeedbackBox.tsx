import { useState } from 'react';
import { Alert, Box, Button, Link, Paper, TextField, Typography } from '@mui/material';
import {
  useSubmitFeedbackMutation,
  FEEDBACK_MAX_LENGTH,
} from '../../features/feedback/feedbackApi';
import { extractErrorMessage } from '../../lib/errors';

const FEEDBACK_EMAIL = 'brendanpotter00@gmail.com';

/**
 * Full-width feedback card shown at the top of the Give Feedback page. Writes a
 * free-form message to the backend ``feedback`` table via POST /api/feedback.
 * Anonymous submissions are allowed (the token is optional) — signed-out users
 * are recorded with a null user on the backend.
 */
export function GiveFeedbackBox() {
  const [message, setMessage] = useState('');
  const [success, setSuccess] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [submitFeedback, { isLoading }] = useSubmitFeedbackMutation();

  const trimmed = message.trim();
  const tooLong = message.length > FEEDBACK_MAX_LENGTH;
  const canSubmit = trimmed.length > 0 && !tooLong && !isLoading;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSuccess(false);
    setErrorMsg(null);
    try {
      await submitFeedback({ message: trimmed }).unwrap();
      setMessage(''); // clear on success
      setSuccess(true);
    } catch (err) {
      // Preserve the typed text on failure so the user can retry.
      setErrorMsg(extractErrorMessage(err, 'Failed to send feedback'));
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" component="h2" gutterBottom>
        Give Feedback
      </Typography>

      <TextField
        label="Your feedback"
        value={message}
        onChange={(e) => {
          setMessage(e.target.value);
          setSuccess(false);
          setErrorMsg(null);
        }}
        multiline
        minRows={3}
        fullWidth
        error={tooLong}
        helperText={
          tooLong
            ? `Feedback must be ${FEEDBACK_MAX_LENGTH.toLocaleString()} characters or fewer.`
            : `${message.length}/${FEEDBACK_MAX_LENGTH}`
        }
        slotProps={{
          htmlInput: { maxLength: FEEDBACK_MAX_LENGTH, 'aria-label': 'Your feedback' },
        }}
        sx={{ mb: 1 }}
      />

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        You can also email me at{' '}
        <Link href={`mailto:${FEEDBACK_EMAIL}`}>{FEEDBACK_EMAIL}</Link>
      </Typography>

      {success && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Thanks! Your feedback was sent.
        </Alert>
      )}
      {errorMsg && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {errorMsg}
        </Alert>
      )}

      <Box>
        <Button variant="contained" onClick={handleSubmit} disabled={!canSubmit}>
          {isLoading ? 'Sending...' : 'Send'}
        </Button>
      </Box>
    </Paper>
  );
}
