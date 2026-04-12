import { useState, useEffect, useCallback } from 'react';
import Container from '@mui/material/Container';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Avatar from '@mui/material/Avatar';
import Alert from '@mui/material/Alert';
import CircularProgress from '@mui/material/CircularProgress';
import { useAuth } from '../../features/auth/useAuth';
import { fetchCurrentUser, updateCurrentUser, type User } from '../../features/auth/authService';

export function AccountPage() {
  const { isAuthenticated, isLoading: authLoading, login, getToken } = useAuth();

  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const fetchedUser = await fetchCurrentUser(token);
      setUser(fetchedUser);
      setDisplayName(fetchedUser.displayName ?? '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load profile');
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    if (isAuthenticated) {
      loadProfile();
    }
  }, [isAuthenticated, loadProfile]);

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
      setDisplayName(updatedUser.displayName ?? '');
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save changes');
    } finally {
      setIsSaving(false);
    }
  };

  if (authLoading) {
    return (
      <Container maxWidth="sm" sx={{ py: 4, textAlign: 'center' }}>
        <CircularProgress />
      </Container>
    );
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
    return (
      <Container maxWidth="sm" sx={{ py: 4, textAlign: 'center' }}>
        <CircularProgress />
      </Container>
    );
  }

  if (error) {
    return (
      <Container maxWidth="sm" sx={{ py: 4 }}>
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
        <Button variant="outlined" onClick={loadProfile}>
          Retry
        </Button>
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

        <Button
          variant="contained"
          onClick={handleSave}
          disabled={!isDirty || isSaving}
          fullWidth
        >
          {isSaving ? 'Saving...' : 'Save Changes'}
        </Button>
      </Paper>
    </Container>
  );
}
