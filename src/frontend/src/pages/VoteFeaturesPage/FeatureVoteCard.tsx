import { useState } from 'react';
import { Box, Card, CardContent, Chip, IconButton, Stack, Typography } from '@mui/material';
import { keyframes } from '@mui/material/styles';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import type { FeatureListItem } from '../../features/features/featuresApi';
import {
  useUpvoteFeatureMutation,
  useRemoveUpvoteMutation,
} from '../../features/features/featuresApi';
import { useAuth } from '../../features/auth/useAuth';
import { SignInPromptModal } from '../../components/shared/SignInPrompt';
import { SIGN_IN_MODAL_MESSAGES } from '../../constants/messages';
import { logger } from '../../lib/logger';
import { RESPONSIVE } from '../../config/responsive';

// Live "we're listening" pulse — same cadence/colour as the recording dot in
// GlobalAppBar so the shipped signal feels consistent across the app. Disabled
// under prefers-reduced-motion.
const liveBlink = keyframes`
  0%, 55% { opacity: 1; }
  60%, 100% { opacity: 0.25; }
`;

export interface FeatureVoteCardProps {
  feature: FeatureListItem;
  /**
   * Render the shipped/completed variant: a "Shipped" badge + live green dot,
   * a read-only vote count, and no upvote control. Used by the completed
   * section of the voting page.
   */
  readOnly?: boolean;
}

export function FeatureVoteCard({ feature, readOnly = false }: FeatureVoteCardProps) {
  const { isAuthenticated } = useAuth();
  const [modalOpen, setModalOpen] = useState(false);

  const [upvote, { isLoading: isAdding }] = useUpvoteFeatureMutation();
  const [removeUpvote, { isLoading: isRemoving }] = useRemoveUpvoteMutation();

  if (readOnly) {
    return (
      <Card variant="outlined">
        <CardContent
          sx={{
            p: RESPONSIVE.spacing.cardPadding,
            '&:last-child': { pb: RESPONSIVE.spacing.cardPaddingBottom },
          }}
        >
          <Stack direction="row" spacing={2} alignItems="flex-start">
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                minWidth: 48,
              }}
            >
              <Typography
                variant="body2"
                sx={{ color: 'text.secondary', fontWeight: 600 }}
                aria-label={`${feature.upvoteCount} upvotes`}
              >
                {feature.upvoteCount}
              </Typography>
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Stack
                direction="row"
                spacing={1}
                alignItems="center"
                flexWrap="wrap"
                sx={{ mb: 0.5 }}
              >
                <Typography variant="h6" component="h3">
                  {feature.title}
                </Typography>
                <Box
                  component="span"
                  sx={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                >
                  <Chip label="Shipped" size="small" color="success" />
                  <Box
                    component="span"
                    aria-hidden
                    data-testid="live-dot"
                    sx={{
                      width: '7px',
                      height: '7px',
                      borderRadius: '50%',
                      background: '#2F8F3F',
                      boxShadow: '0 0 8px rgba(47,143,63,0.6)',
                      display: 'inline-block',
                      animation: `${liveBlink} 2.2s ease-in-out infinite`,
                      '@media (prefers-reduced-motion: reduce)': {
                        animation: 'none',
                      },
                    }}
                  />
                </Box>
              </Stack>
              <Typography variant="body2" color="text.secondary">
                {feature.description}
              </Typography>
            </Box>
          </Stack>
        </CardContent>
      </Card>
    );
  }

  const isInFlight = isAdding || isRemoving;

  const handleClick = () => {
    if (!isAuthenticated) {
      setModalOpen(true);
      return;
    }
    // featuresApi handles the optimistic update + rollback on failure; the
    // awaited `.unwrap()` call is purely for observability so the rejection
    // reason is surfaced to the console instead of being swallowed silently.
    const action = feature.hasUpvoted ? 'remove-upvote' : 'upvote';
    const trigger = feature.hasUpvoted ? removeUpvote : upvote;
    trigger(feature.id)
      .unwrap()
      .catch((e: unknown) => {
        logger.error(`[FeatureVoteCard] ${action} failed for feature=${feature.id}:`, e);
      });
  };

  const arrowColor = feature.hasUpvoted ? 'primary.main' : 'text.secondary';
  const countColor = feature.hasUpvoted ? 'primary.main' : 'text.secondary';
  const ariaLabel = feature.hasUpvoted
    ? `Remove upvote from ${feature.title}`
    : `Upvote ${feature.title}`;

  return (
    <>
      <Card variant="outlined">
        <CardContent
          sx={{
            p: RESPONSIVE.spacing.cardPadding,
            '&:last-child': { pb: RESPONSIVE.spacing.cardPaddingBottom },
          }}
        >
          <Stack direction="row" spacing={2} alignItems="flex-start">
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                minWidth: 48,
              }}
            >
              <IconButton
                onClick={handleClick}
                disabled={isInFlight}
                aria-label={ariaLabel}
                aria-pressed={feature.hasUpvoted}
                size="small"
                sx={{ color: arrowColor }}
              >
                <KeyboardArrowUpIcon />
              </IconButton>
              <Typography
                variant="body2"
                sx={{ color: countColor, fontWeight: 600 }}
                aria-label={`${feature.upvoteCount} upvotes`}
              >
                {feature.upvoteCount}
              </Typography>
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="h6" component="h3" gutterBottom>
                {feature.title}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {feature.description}
              </Typography>
            </Box>
          </Stack>
        </CardContent>
      </Card>
      <SignInPromptModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={SIGN_IN_MODAL_MESSAGES.TITLE}
        subtitle={SIGN_IN_MODAL_MESSAGES.SUBTITLE}
        buttonText={SIGN_IN_MODAL_MESSAGES.BUTTON_TEXT}
      />
    </>
  );
}
