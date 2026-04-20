import { useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  IconButton,
  Stack,
  Typography,
} from '@mui/material';
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

export interface FeatureVoteCardProps {
  feature: FeatureListItem;
}

export function FeatureVoteCard({ feature }: FeatureVoteCardProps) {
  const { isAuthenticated } = useAuth();
  const [modalOpen, setModalOpen] = useState(false);

  const [upvote, { isLoading: isAdding }] = useUpvoteFeatureMutation();
  const [removeUpvote, { isLoading: isRemoving }] = useRemoveUpvoteMutation();

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
        logger.error(
          `[FeatureVoteCard] ${action} failed for feature=${feature.id}:`,
          e
        );
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
        <CardContent>
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
