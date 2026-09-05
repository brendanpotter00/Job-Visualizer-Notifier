import { Box, Button } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { LandingContent } from '../content';

interface CTAButtonsProps {
  ctas: LandingContent['ctas'];
  /**
   * Renders "Create free account" as an outlined (monochrome black-on-white)
   * button beside the contained primary. Heroes and closers both carry the
   * pair: signing up is the conversion, so it stays one click away everywhere.
   */
  showSecondary?: boolean;
  size?: 'medium' | 'large';
  align?: 'left' | 'center';
}

export function CTAButtons({
  ctas,
  showSecondary = false,
  size = 'large',
  align = 'center',
}: CTAButtonsProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        gap: 1.5,
        justifyContent: align === 'center' ? 'center' : 'flex-start',
        flexWrap: 'wrap',
      }}
    >
      <Button component={RouterLink} to={ctas.primary.to} variant="contained" size={size}>
        {ctas.primary.label}
      </Button>
      {showSecondary && (
        <Button component={RouterLink} to={ctas.secondary.to} variant="outlined" size={size}>
          {ctas.secondary.label}
        </Button>
      )}
    </Box>
  );
}
