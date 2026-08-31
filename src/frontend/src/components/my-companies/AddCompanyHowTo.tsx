import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { visuallyHidden } from '@mui/utils';

/**
 * ── THE VIDEO SLOT ────────────────────────────────────────────────────────────
 *
 * TO ADD THE VIDEO, CHANGE THIS ONE LINE. Drop the file in `src/frontend/public/`
 * and set this to its path (`'/how-it-works.mp4'`), or paste an absolute CDN URL.
 * Nothing else in this file, in `MyCompaniesList` or on the page has to move: the
 * three steps are laid out the same way with a video and without one.
 *
 * It is `null` today because there IS no video yet, and while it is null this
 * component renders NOTHING in that space — no figure, no grey 16:9 rectangle, no
 * "coming soon". A placeholder shipped to users is worse than the gap: it is a
 * promise the page cannot keep, and it costs 200px of the first screen to make it.
 *
 * ONE THING TO DO WHEN THE VIDEO LANDS, and it is not in this file: the field
 * helper in `ResolveUrlForm` carries the "not LinkedIn or Indeed" clause ONLY
 * because the video does not exist to say it. That clause is marked in place and
 * can go the day this stops being null.
 */
export const HOW_IT_WORKS_VIDEO_SRC: string | null = null;

/**
 * What the video shows, for anyone who cannot watch it. Written now so that
 * turning the slot on stays a one-line change.
 */
const HOW_IT_WORKS_VIDEO_LABEL =
  "How to reach a company's own careers page from a job you found elsewhere, and copy that link.";

/**
 * NO SUBTEXT, NO HEADING, NO CAPTION — three labels and nothing else.
 *
 * Every step used to carry a sentence under it explaining itself. The owner cut all
 * three: "we don't need all this subtext". What is left has to survive on its own, so
 * step 3 says "in the box above" rather than a direction word that would point the
 * wrong way at one of the two widths this renders at.
 */
const STEPS = ['Open their careers page', 'Copy the link', 'Paste it in the box above'] as const;

interface AddCompanyHowToProps {
  /**
   * A line only a screen reader gets, read before the steps.
   *
   * The empty-list render passes "No companies yet". Cutting the VISIBLE heading (the
   * design calls for three labels and nothing else) left a screen-reader user hearing
   * "Companies you're tracking" followed by three instructions and never being told the
   * list was empty. This restores that one fact and draws nothing.
   */
  srOnlyLine?: string;
  /**
   * Override the module-level slot. Exists so a test can render BOTH compositions —
   * with a video and without — rather than only the one today's config produces.
   */
  videoSrc?: string | null;
}

/**
 * "How it works": three numbered steps, centred, with the video slot under them.
 *
 * ONE COMPONENT, TWO TRIGGERS. It is the whole empty state for a user tracking
 * nothing (`MyCompaniesList`), and it is what the persistent "How it works" link on
 * the page re-opens for a user who already has companies. Trimming one and not the
 * other would ship two versions of the same screen.
 *
 * WHY THE LIST IS CENTRED AS A BLOCK RATHER THAN ROW BY ROW. The number sits to the
 * LEFT of its label, and the block is centred. Centring each ROW on its own axis gives
 * three rows of different widths, three different left edges, and digits that no longer
 * line up — worse than either instruction alone. So on a phone the `<ol>` is
 * `width: max-content` with auto margins (the block is centred, the rows inside it are
 * left-aligned, the numbers share one left edge) and from `sm` up each row is centred
 * inside its own third of a 3-column grid, where there is only one row to line up with.
 */
export function AddCompanyHowTo({
  srOnlyLine,
  videoSrc = HOW_IT_WORKS_VIDEO_SRC,
}: AddCompanyHowToProps) {
  return (
    <Box sx={{ textAlign: 'center', pt: 2.5, pb: 0.5 }} data-testid="add-company-how-to">
      {srOnlyLine ? (
        <Typography component="p" sx={visuallyHidden}>
          {srOnlyLine}
        </Typography>
      ) : null}

      {/* `role="list"` is NOT redundant. Safari and iOS VoiceOver silently drop the list
          role from any list carrying `list-style: none`, so without it this announces as
          three loose paragraphs and the numbering — which lives in `aria-hidden` glyphs —
          disappears with it. The cost of the explicit role is that "ordered" is flattened
          to "list", which no screen reader announces anyway; position ("1 of 3") survives. */}
      <Box
        component="ol"
        role="list"
        sx={{
          listStyle: 'none',
          m: '0 auto',
          p: 0,
          display: 'grid',
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(3, minmax(0, 1fr))' },
          // Measured at 390px and 900px on the approved design rather than taken from a
          // `RESPONSIVE` token: these are the geometry of one three-step list, not a
          // sizing pair any other screen would reuse.
          gap: { xs: 1.5, sm: 3 },
          // The centring rule above, in two values.
          width: { xs: 'max-content', sm: 'auto' },
          maxWidth: '100%',
          textAlign: 'left',
          justifyItems: { sm: 'center' },
        }}
      >
        {STEPS.map((label, index) => (
          <Box
            component="li"
            key={label}
            sx={{ display: 'flex', alignItems: 'center', gap: 1.25, minWidth: 0 }}
          >
            {/* `aria-hidden` so nobody hears "1, 1. Open their careers page" — the list
                already announces position. */}
            <Box
              component="span"
              aria-hidden
              sx={{
                flex: '0 0 26px',
                width: 26,
                height: 26,
                borderRadius: '50%',
                // grey.200, not grey.100: this renders on the page's white background in
                // the empty state AND on the form's `background.paper` (#f5f5f5) when the
                // link re-opens it, and #f5f5f5 on #f5f5f5 is not a chip.
                bgcolor: 'grey.200',
                color: 'text.primary',
                fontSize: '0.8125rem',
                fontWeight: 700,
                lineHeight: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {index + 1}
            </Box>
            <Typography
              component="p"
              sx={{ m: 0, fontSize: '0.9375rem', fontWeight: 600, lineHeight: 1.5 }}
            >
              {label}
            </Typography>
          </Box>
        ))}
      </Box>

      {/* The slot. Nothing is drawn while there is no video — see the constant above. */}
      {videoSrc ? (
        <Box component="figure" sx={{ m: '22px auto 0', maxWidth: 520 }}>
          <Box
            component="video"
            src={videoSrc}
            controls
            playsInline
            preload="metadata"
            aria-label={HOW_IT_WORKS_VIDEO_LABEL}
            data-testid="add-company-how-to-video"
            sx={{
              display: 'block',
              width: '100%',
              aspectRatio: '16 / 9',
              borderRadius: 1,
              bgcolor: 'grey.200',
            }}
          />
        </Box>
      ) : null}
    </Box>
  );
}
