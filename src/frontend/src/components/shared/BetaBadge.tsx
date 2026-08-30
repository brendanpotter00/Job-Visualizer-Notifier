import Box from '@mui/material/Box';

/**
 * Metrics per scale. Two call sites at two very different type sizes — a page
 * heading (h4/h5, 20–24px) and a sidebar row (body1, 16px) — so the badge is
 * measured for each rather than one size stretched over both.
 *
 * `nav` is the tight one. The drawer gives a label 151px (240px paper − 40px
 * button padding − 24px icon − 24px icon margin), and "Add Companies" alone is
 * 114px of it. That leaves ~37px for the gap and the whole badge, which is why
 * the nav scale runs 9px type on 3px of side padding — at these numbers the 1px
 * outline is a real part of the budget. Measured in the browser it lands at
 * 150px of 151px; `BetaBadge` below and the drawer both still handle overflow
 * rather than assuming it away.
 */
const SCALES = {
  title: {
    fontSize: 11,
    letterSpacing: '0.08em',
    padY: '2px',
    padX: '7px',
  },
  nav: {
    fontSize: 9,
    letterSpacing: '0.04em',
    padY: '1px',
    padX: '3px',
  },
} as const;

/**
 * How far the text is pushed DOWN, on top of the symmetric vertical padding.
 *
 * "BETA" is all caps, so it paints from the cap height to the baseline and puts
 * NO ink in the descender space below it. The line box still reserves that
 * space, and `align-items: center` centres the *box*, so the word lands visibly
 * high in the pill — the classic all-caps chip defect, and the one a reader
 * actually notices.
 *
 * Measured rather than guessed: screenshotting the rendered pill at 10× and
 * taking the ink's bounding box put the word 1.84px high at the 11px scale and
 * 1.55px high at 9px — both ≈ 0.17em, so half of it (0.085em) is the shift that
 * centres the ink. Applied as +nudge on top and −nudge on bottom, which moves
 * the word without changing the pill's height.
 */
const CAP_HEIGHT_NUDGE = '0.085em';

export interface BetaBadgeProps {
  /**
   * Which scale to render. `'title'` sits beside a page heading, `'nav'` beside
   * a sidebar nav label.
   */
  scale?: keyof typeof SCALES;
}

/**
 * "BETA" as a chip rather than as "(beta)" appended to the label.
 *
 * A STATUS MARKER, NOT A CALL TO ACTION. Everything here is chosen to keep it
 * quiet: `text.secondary` inside a hairline `divider` outline, no accent colour,
 * and a type size well under whatever it annotates. The heading is the thing
 * being read; this is a note attached to it.
 *
 * All three colours are theme tokens (`text.secondary`, `background.default`,
 * `divider`) with nothing hardcoded, so a dark palette would carry it. Worth
 * stating plainly: the app currently ships ONE theme (light, monochrome — see
 * config/theme.ts), so "works in dark mode" is not something that can be
 * observed today, only something the token choice keeps true if a dark palette
 * is ever added.
 *
 * It renders as ordinary text inside its parent's element, so a screen reader
 * reads it as part of the surrounding label — "Add Companies Beta" — rather
 * than skipping it. Deliberately NOT `aria-hidden`, and deliberately not given
 * its own `role`: it is one word of the name, not a separate control.
 */
export function BetaBadge({ scale = 'title' }: BetaBadgeProps) {
  const { fontSize, letterSpacing, padY, padX } = SCALES[scale];

  return (
    <Box
      component="span"
      sx={{
        // `inline-flex` + `flexShrink: 0`: in the sidebar this sits in a flex row
        // next to a label that may ellipsize. The label gives way; the badge does
        // not, because half a clipped pill reads as broken rather than as tight.
        display: 'inline-flex',
        alignItems: 'center',
        flexShrink: 0,
        fontSize,
        fontWeight: 700,
        lineHeight: 1.45,
        // Horizontal padding stays symmetric ON PURPOSE. `letter-spacing` adds a
        // trailing gap after the final "A" that would normally pull the word
        // left, but measuring it showed the side bearings of "B" and "A" already
        // cancel it out (0.2px off centre at the nav scale). Subtracting the
        // trailing space from `paddingRight` — the usual fix — would push the
        // word off centre the other way.
        letterSpacing,
        textTransform: 'uppercase',
        // See CAP_HEIGHT_NUDGE. The two vertical values still sum to `2 * padY`,
        // so the pill is exactly as tall as it was — only the word moved.
        paddingTop: `calc(${padY} + ${CAP_HEIGHT_NUDGE})`,
        paddingBottom: `calc(${padY} - ${CAP_HEIGHT_NUDGE})`,
        paddingLeft: padX,
        paddingRight: padX,
        // Fully rounded rather than `shape.borderRadius` (8px), which at this
        // height would read as a square with soft corners.
        borderRadius: 999,
        color: 'text.secondary',
        // OPAQUE ground, and that is a contrast fix rather than a preference.
        // The first version used the translucent `action.hover`/`action.selected`
        // overlays, which take their real colour from whatever is behind them:
        // in the sidebar that is the drawer's own grey, and on the row for the
        // page you are currently on it is that grey plus the selected-row tint.
        // Measured off the rendered pixels, `text.secondary` on the nav badge
        // came out at 4.39:1 — under the 4.5:1 AA floor for text this size, and
        // 3.75:1 on the selected row. `background.default` does not stack, so
        // the badge is 5.74:1 wherever it is put; the `divider` outline is what
        // gives it its shape once the ground stops being a tint.
        bgcolor: 'background.default',
        border: '1px solid',
        borderColor: 'divider',
        whiteSpace: 'nowrap',
      }}
    >
      {/* "Beta", uppercased in CSS rather than typed as "BETA": a screen reader
          gets the word, not four letters it may spell out. */}
      Beta
    </Box>
  );
}
