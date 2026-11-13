import Box from '@mui/material/Box';
import { keyframes } from '@mui/material/styles';

const recBlink = keyframes`
  0%, 55% { opacity: 1; }
  60%, 100% { opacity: 0.25; }
`;

interface OneSecondMarkProps {
  fontSize?: number | string | Record<string, number | string>;
}

export function OneSecondMark({ fontSize = '22px' }: OneSecondMarkProps) {
  return (
    <Box
      component="span"
      aria-hidden
      data-testid="one-second-mark"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        fontSize,
        fontFamily:
          '"Infra Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        fontWeight: 700,
        letterSpacing: '-0.03em',
        lineHeight: 1,
      }}
    >
      <span>1s</span>
      <Box
        component="span"
        sx={{
          width: '7px',
          height: '7px',
          borderRadius: '50%',
          background: '#2F8F3F',
          boxShadow: '0 0 8px rgba(47,143,63,0.6)',
          display: 'inline-block',
          animation: `${recBlink} 2.2s ease-in-out infinite`,
          '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }}
      />
    </Box>
  );
}
