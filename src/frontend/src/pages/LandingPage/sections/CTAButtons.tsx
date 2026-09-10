import { Box, Button } from '@mui/material';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import { Link as RouterLink } from 'react-router-dom';
import type { LandingContent } from '../content';

interface CTAButtonsProps {
  ctas: LandingContent['ctas'];
  /**
   * Renders "Create free account" as a quiet text button beside the contained
   * primary. The hero and the closer both carry the pair: signing up is the
   * conversion, so it stays one click away at both ends of the page, but it
   * never competes with "Browse jobs" for the eye.
   */
  showSecondary?: boolean;
  size?: 'medium' | 'large';
  align?: 'left' | 'center';
}

/**
 * The page's two calls to action. One filled pill with an arrow, one plain
 * text link: the same pair, in the same order, everywhere they appear.
 */
export function CTAButtons({
  ctas,
  showSecondary = false,
  size = 'large',
  align = 'left',
}: CTAButtonsProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        justifyContent: align === 'center' ? 'center' : 'flex-start',
        flexWrap: 'wrap',
      }}
    >
      <Button
        component={RouterLink}
        to={ctas.primary.to}
        variant="contained"
        size={size}
        endIcon={<ArrowForwardIcon />}
        sx={{ borderRadius: 999, px: 3 }}
      >
        {ctas.primary.label}
      </Button>
      {showSecondary && (
        <Button
          component={RouterLink}
          to={ctas.secondary.to}
          variant="text"
          size={size}
          sx={{ borderRadius: 999, px: 2, color: 'text.primary' }}
        >
          {ctas.secondary.label}
        </Button>
      )}
    </Box>
  );
}
