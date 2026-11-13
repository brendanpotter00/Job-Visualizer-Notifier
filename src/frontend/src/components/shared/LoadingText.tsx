import { Fragment } from 'react';
import Typography from '@mui/material/Typography';

interface LoadingTextProps {
  /**
   * What is loading, e.g. "Loading feedback". Defaults to "Loading". A trailing
   * "…" or "..." is dropped: the animation already says "in progress".
   */
  text?: string;
}

/** Shown when the caller passes no text (or only an ellipsis). */
const DEFAULT_TEXT = 'Loading';

/** One full breath (dim → bright → dim), in seconds. */
const CYCLE_S = 1.6;

/** How far each character lags the one before it, in seconds. */
const STEP_S = 0.1;

/**
 * Characters per wavelength. After this many characters the lag has gone round one
 * full cycle, so character 16 is exactly in phase with character 0 again.
 *
 * That is why the stagger is capped with `% WAVELENGTH` and not a smaller number: the
 * cap changes nothing once the wave is running (the phases are identical to an
 * uncapped `i * STEP_S`), it only stops a long caption's tail from sitting still for
 * seconds before its turn comes. A smaller cap would put a visible seam in the wave.
 */
const WAVELENGTH = Math.round(CYCLE_S / STEP_S);

const LETTER_CLASS = 'LoadingText-letter';
const WORD_CLASS = 'LoadingText-word';

const ROOT_SX = {
  letterSpacing: '0.01em',
  '@keyframes loadingTextBreathe': {
    '0%, 100%': { opacity: 0.25 },
    '50%': { opacity: 1 },
  },
  // Keep each word on one line. Every inline-block is a line-break opportunity, so
  // without this a long caption on a phone could wrap mid-word. The spaces between
  // words are ordinary text, so the caption still wraps there.
  [`& .${WORD_CLASS}`]: { whiteSpace: 'nowrap' },
  [`& .${LETTER_CLASS}`]: {
    display: 'inline-block',
    animation: `loadingTextBreathe ${CYCLE_S}s ease-in-out infinite`,
    // Static and at full opacity: the text still says what is happening.
    '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
  },
} as const;

/** Collapse whitespace and drop a trailing ellipsis. */
function toLabel(text: string | undefined): string {
  const label = (text ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\s*(?:…|\.\.\.)$/u, '');
  return label || DEFAULT_TEXT;
}

/**
 * The delay for the character at `index` (spaces count, so the rhythm follows the
 * text's width).
 *
 * NEGATIVE, so every letter is already mid-cycle on the first frame. A positive delay
 * leaves each letter at full opacity until its turn and then drops it to the dim end,
 * which reads as a flicker sweeping across the word on mount. The phases are the same
 * either way.
 */
function delayFor(index: number): string {
  return `${(((index % WAVELENGTH) - WAVELENGTH) * STEP_S).toFixed(1)}s`;
}

/** Split into words, each with the index of its first character in the full label. */
function toWords(label: string): { letters: string[]; start: number }[] {
  let offset = 0;
  return label.split(' ').map((word) => {
    const letters = Array.from(word);
    const start = offset;
    offset += letters.length + 1;
    return { letters, start };
  });
}

/**
 * Loading text whose letters breathe in a left-to-right wave — the app's loading
 * indicator (there is no spinner).
 *
 * Exposed to assistive tech as one indeterminate `progressbar` named by the whole
 * text, so a screen reader hears "Loading feedback" once. The letters themselves are
 * `aria-hidden`.
 */
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
