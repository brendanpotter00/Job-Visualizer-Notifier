import { useState, useEffect } from 'react';
import Container from '@mui/material/Container';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Avatar from '@mui/material/Avatar';
import Alert from '@mui/material/Alert';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { setHideAdminFeatures, setDemoModeEnabled } from '../../features/ui/uiSlice';
import { useAuth } from '../../features/auth/useAuth';
import { useCurrentUser } from '../../features/auth/useCurrentUser';
import { updateCurrentUser } from '../../features/auth/authService';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';

export function AccountPage() {
  const { isAuthenticated, isLoading: authLoading, login, getToken } = useAuth();
  const { user, setUser, loading, error, reload: loadProfile } = useCurrentUser();
  const dispatch = useAppDispatch();
  const hideAdminFeatures = useAppSelector((state) => state.ui.hideAdminFeatures);
  const demoModeEnabled = useAppSelector((state) => state.ui.demoModeEnabled);

  const [displayName, setDisplayName] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const userDisplayName = user?.displayName;
  useEffect(() => {
    setDisplayName(userDisplayName ?? '');
  }, [userDisplayName]);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    try {
      const token = await getToken();
      const updatedUser = await updateCurrentUser(token, {
        displayName: displayName.trim() || null,
      });
      setUser(updatedUser);
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(extractErrorMessage(err, 'Failed to save changes'));
    } finally {
      setIsSaving(false);
    }
  };

  if (authLoading) {
    return <LoadingState fullPage />;
  }

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ py: 4 }}>
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="h5" gutterBottom>
            Account
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
            Sign in to view your account.
          </Typography>
          <Button variant="contained" onClick={login}>
            Sign In
          </Button>
        </Paper>
      </Container>
    );
  }

  if (loading) {
    return <LoadingState fullPage />;
  }

  if (error) {
    return (
      <Container maxWidth="sm" sx={{ py: 4 }}>
        <ErrorState inline message={error} onRetry={loadProfile} />
      </Container>
    );
  }

  if (!user) return null;

  const isDirty = displayName !== (user.displayName ?? '');
  const fullName = [user.givenName, user.familyName].filter(Boolean).join(' ');
  const initials = [user.givenName?.[0], user.familyName?.[0]].filter(Boolean).join('');
  const avatarSize = { width: 80, height: 80, mb: 2 };

  return (
    <Container maxWidth="sm" sx={{ py: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Account
      </Typography>

      <Paper sx={{ p: 4 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', mb: 3 }}>
          {user.pictureUrl ? (
            <Avatar src={user.pictureUrl} alt={fullName || user.email} sx={avatarSize} />
          ) : (
            <Avatar sx={{ ...avatarSize, fontSize: '2rem' }}>
              {initials || user.email[0]?.toUpperCase()}
            </Avatar>
          )}
          <Typography variant="body2" color="text.secondary">
            {user.email}
          </Typography>
        </Box>

        {fullName && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="caption" color="text.secondary">
              Name
            </Typography>
            <Typography variant="body1">{fullName}</Typography>
          </Box>
        )}

        <TextField
          label="Display Name"
          value={displayName}
          onChange={(e) => {
            setDisplayName(e.target.value);
            setSaveSuccess(false);
          }}
          fullWidth
          size="small"
          sx={{ mb: 3 }}
          slotProps={{ htmlInput: { maxLength: 100 } }}
        />

        {saveSuccess && (
          <Alert severity="success" sx={{ mb: 2 }}>
            Changes saved.
          </Alert>
        )}

        {saveError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {saveError}
          </Alert>
        )}

        <Button variant="contained" onClick={handleSave} disabled={!isDirty || isSaving} fullWidth>
          {isSaving ? 'Saving...' : 'Save Changes'}
        </Button>
      </Paper>

      {user.isAdmin && (
        <>
          <Paper sx={{ p: 4, mt: 3 }}>
            <FormControlLabel
              control={
                <Switch
                  checked={hideAdminFeatures}
                  onChange={(e) => dispatch(setHideAdminFeatures(e.target.checked))}
                  slotProps={{ input: { 'aria-label': 'Hide all admin features' } }}
                />
              }
              label="Hide all admin features"
            />
            <Typography variant="caption" color="text.secondary" display="block">
              Demo only — hides the Admin section in the sidebar for this session. Resets when you
              refresh the page.
            </Typography>
          </Paper>

          <Paper sx={{ p: 4, mt: 3 }}>
            <FormControlLabel
              control={
                <Switch
                  checked={demoModeEnabled}
                  onChange={(e) => dispatch(setDemoModeEnabled(e.target.checked))}
                  slotProps={{ input: { 'aria-label': 'Enable demo mode' } }}
                />
              }
              label="Demo mode"
            />
            <Typography variant="caption" color="text.secondary" display="block">
              Demo only — replaces the Recent Job Postings list with ~100 sample
              software-engineering roles from top companies. Resets when you refresh the page.
            </Typography>
          </Paper>
        </>
      )}
    </Container>
  );
}
