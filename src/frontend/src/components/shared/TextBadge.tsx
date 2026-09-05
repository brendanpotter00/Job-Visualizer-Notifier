import Box from '@mui/material/Box';

interface TextBadgeProps {
  /** The word. Typed in sentence case; uppercased in CSS — see the note below. */
  label: string;
  /**
   * Type size in px. The default (11) is the page-heading scale next to an
   * h4/h5. Menu rows and other body-size contexts want it a step smaller.
   *
   * Everything else in the pill is expressed in `em` or derived from this, so
   * the proportions — including the cap-height nudge — hold at any size.
   */
  fontSize?: number;
}

/**
 * Vertical padding, as a share of the type size, so the pill scales with it.
 */
const PAD_Y = '0.18em';
const PAD_X = '0.64em';

/**
 * How far the text is pushed DOWN, on top of the symmetric vertical padding.
 *
 * The label is all caps, so it paints from the cap height to the baseline and
 * puts NO ink in the descender space below it. The line box still reserves that
 * space, and `align-items: center` centres the *box*, so the word lands visibly
 * high in the pill — the classic all-caps chip defect, and the one a reader
 * actually notices.
 *
 * Measured rather than guessed: screenshotting the rendered pill at 10× and
 * taking the ink's bounding box put the word 1.84px high at the 11px scale —
 * ≈ 0.17em, so half of it (0.085em) is the shift that centres the ink. Applied
 * as +nudge on top and −nudge on bottom, which moves the word without changing
 * the pill's height. In `em`, so it survives a change of `fontSize`.
 */
const CAP_HEIGHT_NUDGE = '0.085em';

/**
 * A short word as a chip rather than appended in parentheses to a label.
 *
 * A STATUS MARKER, NOT A CALL TO ACTION. Everything here is chosen to keep it
 * quiet: `text.secondary` inside a hairline `divider` outline, no accent colour,
 * and a type size well under whatever it annotates. The thing it sits beside is
 * what is being read; this is a note attached to it.
 *
 * All three colours are theme tokens (`text.secondary`, `background.default`,
 * `divider`) with nothing hardcoded, so a dark palette would carry it. Worth
 * stating plainly: the app currently ships ONE theme (light, monochrome — see
 * config/theme.ts), so "works in dark mode" is not something that can be
 * observed today, only something the token choice keeps true if a dark palette
 * is ever added.
 *
 * It renders as ordinary text inside its parent's element, so a screen reader
 * reads it as part of the surrounding label — "Add Companies Beta", "Cisco
 * Custom" — rather than skipping it. Deliberately NOT `aria-hidden`, and
 * deliberately not given its own `role`: it is one word of the name, not a
 * separate control.
 */
export function TextBadge({ label, fontSize = 11 }: TextBadgeProps) {
  return (
    <Box
      component="span"
      sx={{
        // `inline-flex` + `flexShrink: 0`: this sits in a flex row beside other
        // text, and the badge should hold its shape rather than get squeezed if
        // the row runs tight.
        display: 'inline-flex',
        alignItems: 'center',
        flexShrink: 0,
        fontSize,
        fontWeight: 700,
        lineHeight: 1.45,
        // Horizontal padding stays symmetric ON PURPOSE. `letter-spacing` adds a
        // trailing gap after the final letter that would normally pull the word
        // left, but measuring it showed the side bearings of "B" and "A" already
        // cancel it out. Subtracting the trailing space from `paddingRight` —
        // the usual fix — would push the word off centre the other way.
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        // See CAP_HEIGHT_NUDGE. The two vertical values still sum to `2 * PAD_Y`,
        // so the pill is exactly as tall as it was — only the word moved.
        paddingTop: `calc(${PAD_Y} + ${CAP_HEIGHT_NUDGE})`,
        paddingBottom: `calc(${PAD_Y} - ${CAP_HEIGHT_NUDGE})`,
        paddingLeft: PAD_X,
        paddingRight: PAD_X,
        // Fully rounded rather than `shape.borderRadius` (8px), which at this
        // height would read as a square with soft corners.
        borderRadius: 999,
        color: 'text.secondary',
        // OPAQUE ground, and that is a contrast fix rather than a preference.
        // The first version used the translucent `action.hover`/`action.selected`
        // overlays, which take their real colour from whatever is behind them.
        // Measured off the rendered pixels, `text.secondary` came out under the
        // 4.5:1 AA floor for text this size on those overlays.
        // `background.default` does not stack, so the badge stays 5.74:1; the
        // `divider` outline is what gives it its shape once the ground stops
        // being a tint.
        bgcolor: 'background.default',
        border: '1px solid',
        borderColor: 'divider',
        whiteSpace: 'nowrap',
      }}
    >
      {/* Sentence case in the source, uppercased in CSS: a screen reader gets
          the word, not the letters it may otherwise spell out. */}
      {label}
    </Box>
  );
}
