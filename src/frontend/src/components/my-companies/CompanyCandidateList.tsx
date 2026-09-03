import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import useMediaQuery from '@mui/material/useMediaQuery';
import { RESPONSIVE } from '../../config/responsive';
import type { SearchCompanyCandidate } from '../../features/userCompanies/userCompaniesApi';

/**
 * Hard ceiling on rendered rows.
 *
 * The server already caps its response at five (`_MAX_SHOWN_CANDIDATES`) because
 * it probes each one live, so this can only bite if that cap changes or a
 * response is hand-crafted. It is here anyway: the repo rule is that no list
 * renders unbounded, and a cap that depends on a constant in another service is
 * not a cap. Also the reason to bound it is human, not just technical — past a
 * handful, "which of these is my employer?" stops being a question anyone reads.
 */
const MAX_RENDERED = 5;

/**
 * The one sentence that makes the rows worth reading, said wherever rows are
 * visible — at the top in the question state, inside the disclosure in the
 * demoted one. It is the same warning either way, so it is written once.
 */
const CHECK_THE_NAME =
  'Check the name and the number of open jobs before you track one — search can ' +
  'return a real board that belongs to a different company.';

interface CompanyCandidateListProps {
  /** What the user typed, echoed so the question names its own subject. */
  query: string;
  candidates: SearchCompanyCandidate[];
  /** Track one. Called with the board URL, which is what the add endpoint takes. */
  onPick: (url: string) => void;
  /** An add is in flight — every button is inert while one is. */
  busy: boolean;
  /**
   * NOTHING the server sent back was `autoAddable` — these boards are the ones the
   * name gate already REJECTED, and the careers page above them is the answer.
   *
   * Set it and the list stops being the question: no heading that presupposes one of
   * these is right, no live region (the answer above owns that), rows folded away
   * behind a disclosure, and a secondary button on each when they are unfolded. See
   * the component doc for why they are folded rather than dropped.
   */
  demoted?: boolean;
}

/**
 * The candidates a name search found, as a QUESTION rather than an answer.
 *
 * THIS COMPONENT IS THE MITIGATION. The name path's worst failure is not missing
 * a board, it is silently tracking a board that belongs to somebody else:
 * searching "Databricks" returned Guidehouse's Workday board at rank 1 with 794
 * live jobs. It resolves, it probes green, it returns real listings — every
 * automated check we own says yes. The only thing that catches it is a person
 * reading "Guidehouse · 794 jobs" under a search for Databricks.
 *
 * So the board's own token and its live job count are rendered for every row, at
 * full readable size, and neither is ever collapsed behind a link or a tooltip.
 * A row is not decoration around a URL; the identity IS the content. That holds in
 * the demoted state too — folding the LIST behind one press is not the same as
 * shrinking the identity inside a row, and the rows a reader opens are the same
 * rows at the same size.
 *
 * The two-press flow this introduces is deliberate and is NOT a re-run of the
 * preview-then-confirm step that `ResolveUrlForm` deleted. That one made you
 * confirm a URL you had just typed yourself — it asked a question you had
 * already answered. This asks a question you have not: you typed a name, and
 * which board that means is exactly the thing you have not yet said.
 *
 * ── WHY `demoted` EXISTS ─────────────────────────────────────────────────────
 * Typing "meta" returned five real AI-company boards (anthropic, cohere,
 * gleanwork, headway, gc-ai) and not one of them was Meta. The server got this
 * right — every one was `autoAddable: false`, nothing was added, and a second
 * search found `metacareers.com`. The PAGE got it wrong: five big cards with five
 * black "Track this one" buttons, and the correct answer in caption-grey at the
 * bottom. The rejects were the loudest thing on screen.
 *
 * They are folded rather than deleted because the gate is occasionally too strict —
 * measured, it suppressed exactly one right answer across the whole evaluation
 * (Poke, whose board token is `interaction`), and a fold keeps that recoverable in
 * two presses. What it must never do again is offer a rejected board a one-press
 * "Track this one" as a peer of the real answer, so the fold is shut by default and
 * the button inside it is secondary and says "anyway".
 */
export function CompanyCandidateList({
  query,
  candidates,
  onPick,
  busy,
  demoted = false,
}: CompanyCandidateListProps) {
  const [open, setOpen] = useState(false);
  // `timeout={0}` rather than the `@media (prefers-reduced-motion: reduce)` block
  // the narration panel uses: `Collapse` writes its duration as an INLINE style,
  // which no stylesheet rule can outrank. Same promise, enforced from JS because
  // this is the one animation on the page that CSS cannot switch off.
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)');

  // Declared after the hooks, which must run on every render: a search can come
  // back with no boards at all, and this component draws nothing for that.
  if (candidates.length === 0) return null;

  const shown = candidates.slice(0, MAX_RENDERED);
  const rows = shown.map((found) => (
    <CandidateRow
      key={`${found.candidate.ats}:${found.candidate.boardToken}:${found.candidate.sourceUrl}`}
      found={found}
      onPick={onPick}
      busy={busy}
      demoted={demoted}
    />
  ));

  if (!demoted) {
    return (
      // The list appears asynchronously, after a search the user cannot see the
      // progress of. Without a live region a screen-reader user gets no signal that
      // the answer arrived — the page simply, silently, grew a question.
      <Stack spacing={1.5} role="region" aria-live="polite" aria-label="Job boards found">
        <Typography variant="subtitle1" component="h2">
          {candidates.length === 1
            ? `Is this the board for “${query}”?`
            : `Which board is “${query}”?`}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {CHECK_THE_NAME}
        </Typography>

        {rows}
      </Stack>
    );
  }

  return (
    // Still a named region, but NOT a live one. `CareersPageAnswer` above is the
    // news in this state, and it carries the `aria-live` — two polite regions
    // firing on the same render would talk over each other, and the one that
    // would win here is the list of boards we have already ruled out.
    <Box role="region" aria-label="Other job boards found" data-testid="unconfirmed-boards">
      <Link
        component="button"
        type="button"
        variant="body2"
        underline="hover"
        color="text.secondary"
        onClick={() => setOpen((isOpen) => !isOpen)}
        // `aria-expanded` alone, matching `DiscoveryNetworkLog`: the disclosure
        // pattern does not require `aria-controls`, and `unmountOnExit` means it
        // would point at nothing for as long as the fold is shut.
        aria-expanded={open}
        data-testid="unconfirmed-boards-toggle"
        sx={{ display: 'block', textAlign: 'left', py: 0.5 }}
      >
        <Box component="span" aria-hidden sx={{ mr: 0.75 }}>
          {open ? '▾' : '▸'}
        </Box>
        {/* The count is what we will actually RENDER, never what came back: saying
            "8" and then drawing five is the same class of lie as the inverted
            hierarchy this state exists to fix. The wording never calls them an
            answer — it says out loud that none of them was confirmed. */}
        {open
          ? 'Hide these boards'
          : shown.length === 1
            ? `Show 1 other board we found (not confirmed as “${query}”)`
            : `Show ${shown.length} other boards we found (none confirmed as “${query}”)`}
      </Link>

      {/* `unmountOnExit`: a fold the reader has not opened is nothing, not five
          hidden cards with five focusable buttons in the tab order. */}
      <Collapse in={open} unmountOnExit timeout={reduceMotion ? 0 : undefined}>
        <Stack spacing={1.5} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {CHECK_THE_NAME}
          </Typography>
          {rows}
        </Stack>
      </Collapse>
    </Box>
  );
}

interface CandidateRowProps {
  found: SearchCompanyCandidate;
  onPick: (url: string) => void;
  busy: boolean;
  demoted: boolean;
}

/**
 * One board, identity first. Identical in both states by construction — the only
 * thing `demoted` changes is the WEIGHT of the button, never what the row says
 * about which company this is.
 */
function CandidateRow({ found, onPick, busy, demoted }: CandidateRowProps) {
  const { ats, boardToken, sourceUrl } = found.candidate;
  return (
    <Paper variant="outlined" sx={{ p: RESPONSIVE.spacing.paperPadding }}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1.5}
        alignItems={{ xs: 'stretch', sm: 'center' }}
        justifyContent="space-between"
      >
        <Box sx={{ minWidth: 0 }}>
          {/* The board token is the identity, so it is the loudest thing
              in the row — not the ATS name, and not the URL. */}
          <Typography variant="subtitle2" sx={{ wordBreak: 'break-word' }}>
            {boardToken}
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
            <Chip label={ats} size="small" />
            <Typography variant="body2" color="text.secondary">
              {found.probe.ok
                ? `${found.probe.jobCount.toLocaleString()} open jobs`
                : 'could not read this board'}
            </Typography>
          </Stack>
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ display: 'block', mt: 0.5, wordBreak: 'break-all' }}
          >
            {sourceUrl}
          </Typography>
        </Box>
        <Button
          // Filled ONLY where this board is a plausible answer. In the demoted
          // state the filled button belongs to the careers page above, and a
          // rejected board that still wore one would be the whole bug again.
          variant={demoted ? 'outlined' : 'contained'}
          size="small"
          disabled={busy}
          onClick={() => onPick(sourceUrl)}
          // EVERY ROW'S BUTTON READS "Track this one", so without this they
          // share one accessible name and a screen-reader user choosing
          // between boards hears the same label for all of them — on the
          // one screen whose entire job is telling boards apart. The
          // visible label stays short; the announced one carries the
          // identity. Matches `MyCompaniesList`'s `Rename ${name}` pattern.
          aria-label={`Track ${boardToken} on ${ats}`}
          sx={{ flexShrink: 0 }}
        >
          {/* "anyway" is the honest word for it: we said we could not confirm
              this board, and the reader is overruling us — which is exactly
              what the Poke case needs to stay possible. */}
          {demoted ? 'Track this one anyway' : 'Track this one'}
        </Button>
      </Stack>
    </Paper>
  );
}
