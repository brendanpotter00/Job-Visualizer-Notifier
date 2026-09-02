import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
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

interface CompanyCandidateListProps {
  /** What the user typed, echoed so the question names its own subject. */
  query: string;
  candidates: SearchCompanyCandidate[];
  /** Track one. Called with the board URL, which is what the add endpoint takes. */
  onPick: (url: string) => void;
  /** An add is in flight — every button is inert while one is. */
  busy: boolean;
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
 * A row is not decoration around a URL; the identity IS the content.
 *
 * The two-press flow this introduces is deliberate and is NOT a re-run of the
 * preview-then-confirm step that `ResolveUrlForm` deleted. That one made you
 * confirm a URL you had just typed yourself — it asked a question you had
 * already answered. This asks a question you have not: you typed a name, and
 * which board that means is exactly the thing you have not yet said.
 */
export function CompanyCandidateList({
  query,
  candidates,
  onPick,
  busy,
}: CompanyCandidateListProps) {
  if (candidates.length === 0) return null;

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
        Check the name and the number of open jobs before you track one — search can
        return a real board that belongs to a different company.
      </Typography>

      {candidates.slice(0, MAX_RENDERED).map((found) => {
        const { ats, boardToken, sourceUrl } = found.candidate;
        return (
          <Paper
            key={`${ats}:${boardToken}:${sourceUrl}`}
            variant="outlined"
            sx={{ p: RESPONSIVE.spacing.paperPadding }}
          >
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
                variant="contained"
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
                Track this one
              </Button>
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
}
