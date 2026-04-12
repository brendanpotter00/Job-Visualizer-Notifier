import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { DS_FONT_FAMILY } from '../designTokens';

interface ColorSwatchProps {
  name: string;
  hex: string;
  description: string;
}

/**
 * Returns light or dark text color based on relative luminance of the background.
 * For rgba/non-hex strings, defaults to dark text.
 */
function getTextColorForBackground(color: string): string {
  if (!color.startsWith('#') || color.length < 7) {
    return '#26251e';
  }
  const r = parseInt(color.slice(1, 3), 16) / 255;
  const g = parseInt(color.slice(3, 5), 16) / 255;
  const b = parseInt(color.slice(5, 7), 16) / 255;
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return luminance < 0.5 ? '#ffffff' : '#26251e';
}

export function ColorSwatch({ name, hex, description }: ColorSwatchProps) {
  return (
    <Box
      sx={{
        borderRadius: '8px',
        overflow: 'hidden',
        border: '1px solid rgba(38, 37, 30, 0.1)',
      }}
    >
      <Box
        sx={{
          backgroundColor: hex,
          height: 80,
          display: 'flex',
          alignItems: 'flex-end',
          p: 1,
        }}
      >
        <Typography
          sx={{
            fontFamily: DS_FONT_FAMILY.mono,
            fontSize: '0.75rem',
            color: getTextColorForBackground(hex),
            opacity: 0.8,
          }}
        >
          {hex}
        </Typography>
      </Box>
      <Box sx={{ p: 1.5, backgroundColor: '#ffffff' }}>
        <Typography
          sx={{
            fontSize: '0.875rem',
            fontWeight: 600,
            color: '#26251e',
            lineHeight: 1.3,
          }}
        >
          {name}
        </Typography>
        <Typography
          sx={{
            fontSize: '0.75rem',
            color: 'rgba(38, 37, 30, 0.55)',
            lineHeight: 1.4,
            mt: 0.25,
          }}
        >
          {description}
        </Typography>
      </Box>
    </Box>
  );
}
