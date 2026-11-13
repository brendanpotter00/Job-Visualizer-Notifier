import { Fragment } from 'react';
import Typography from '@mui/material/Typography';

interface LoadingTextProps {
  text?: string;
}

const DEFAULT_TEXT = 'Loading';

const CYCLE_S = 1.6;

const STEP_S = 0.1;

const WAVELENGTH = Math.round(CYCLE_S / STEP_S);

const LETTER_CLASS = 'LoadingText-letter';
const WORD_CLASS = 'LoadingText-word';

const ROOT_SX = {
  letterSpacing: '0.01em',
  '@keyframes loadingTextBreathe': {
    '0%, 100%': { opacity: 0.25 },
    '50%': { opacity: 1 },
  },
  [`& .${WORD_CLASS}`]: { whiteSpace: 'nowrap' },
  [`& .${LETTER_CLASS}`]: {
    display: 'inline-block',
    animation: `loadingTextBreathe ${CYCLE_S}s ease-in-out infinite`,
    '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
  },
} as const;

function toLabel(text: string | undefined): string {
  const label = (text ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\s*(?:…|\.\.\.)$/u, '');
  return label || DEFAULT_TEXT;
}

function delayFor(index: number): string {
  return `${(((index % WAVELENGTH) - WAVELENGTH) * STEP_S).toFixed(1)}s`;
}

function toWords(label: string): { letters: string[]; start: number }[] {
  let offset = 0;
  return label.split(' ').map((word) => {
    const letters = Array.from(word);
    const start = offset;
    offset += letters.length + 1;
    return { letters, start };
  });
}

export function LoadingText({ text }: LoadingTextProps) {
  const label = toLabel(text);

  return (
    <Typography
      component="span"
      variant="body1"
      color="text.secondary"
      role="progressbar"
      aria-label={label}
      sx={ROOT_SX}
    >
      <span aria-hidden="true">
        {toWords(label).map(({ letters, start }, w) => (
          <Fragment key={start}>
            {w > 0 && ' '}
            <span className={WORD_CLASS}>
              {letters.map((letter, j) => (
                <span
                  key={j}
                  className={LETTER_CLASS}
                  style={{ animationDelay: delayFor(start + j) }}
                >
                  {letter}
                </span>
              ))}
            </span>
          </Fragment>
        ))}
      </span>
    </Typography>
  );
}
