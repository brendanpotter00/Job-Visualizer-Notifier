import { useState, type ReactNode } from 'react';
import Box from '@mui/material/Box';
import Collapse from '@mui/material/Collapse';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import type { LaunchRadarCard, LaunchRadarRound } from '../../../features/admin/launchRadarTypes';
import { boardLine, formatUsd, hostnameOf, roundLine, summarizeTally } from '../format';

/** Bullets with a muted marker, the card body's only list style. */
const BULLETS_SX = {
  m: 0,
  mt: 0.375,
  pl: 2,
  '& > li': { my: 0.375 },
  '& > li::marker': { color: 'text.disabled' },
} as const;

function Section({
  label,
  aside,
  children,
}: {
  label: string;
  aside?: string | null;
  children: ReactNode;
}) {
  return (
    <Box component="section" aria-label={label} sx={{ mt: 1.25 }}>
      <Typography
        component="div"
        variant="caption"
        sx={{ fontWeight: 600, display: 'flex', justifyContent: 'space-between', gap: 1 }}
      >
        {label}
        {aside && (
          <Box component="span" sx={{ fontWeight: 400, color: 'text.disabled' }}>
            {aside}
          </Box>
        )}
      </Typography>
      <Typography component="ul" variant="body2" sx={BULLETS_SX}>
        {children}
      </Typography>
    </Box>
  );
}

function TeamSection({ card }: { card: LaunchRadarCard }) {
  const { leaders, leadersDropped } = card;
  if (leaders.length === 0) {
    return (
      <Section label="Team">
        <li>
          <Box component="span" sx={{ color: 'warning.dark' }}>
            No leaders confirmed.
          </Box>
          {leadersDropped > 0 && (
            <Box component="span" sx={{ color: 'text.secondary' }}>
              {' '}
              The people search returned company pages.
            </Box>
          )}
        </li>
      </Section>
    );
  }
  const noBackground = leaders.every(
    (l) => !l.summary && l.schools.length === 0 && l.priorCompanies.length === 0
  );
  return (
    <Section label="Team">
      {leaders.map((leader, i) => (
        <li key={`${leader.name}-${i}`}>
          <Box component="span" sx={{ fontWeight: 600 }}>
            {leader.name}
          </Box>
          {leader.title && (
            <Box component="span" sx={{ color: 'text.secondary', ml: 0.5 }}>
              {leader.title}
            </Box>
          )}
          {leader.summary && (
            <Box component="span" sx={{ display: 'block', color: 'text.secondary' }}>
              {leader.summary}
            </Box>
          )}
        </li>
      ))}
      {noBackground && (
        <Box component="li" sx={{ color: 'warning.dark' }}>
          No background data came back for these leaders
        </Box>
      )}
    </Section>
  );
}

function RestOfTeamSection({ stats }: { stats: NonNullable<LaunchRadarCard['teamStats']> }) {
  const schoolCount = stats.schools.length;
  const profiles =
    stats.profilesFound == null
      ? 'profile count unknown'
      : `${stats.profilesFound} public ${stats.profilesFound === 1 ? 'profile' : 'profiles'}`;
  return (
    <Section label="Rest of team" aside={profiles}>
      {stats.priorEmployers.length > 0 && (
        <li>Previously at {summarizeTally(stats.priorEmployers, 6)}</li>
      )}
      {schoolCount > 0 && (
        <li>
          {schoolCount} {schoolCount === 1 ? 'school' : 'schools'}:{' '}
          {summarizeTally(stats.schools, 4)}
        </li>
      )}
      {stats.exFoundersWithExit == null ? (
        <Box component="li" sx={{ color: 'text.secondary' }}>
          Prior exits unknown
        </Box>
      ) : stats.exFoundersWithExit === 0 ? (
        <Box component="li" sx={{ color: 'text.secondary' }}>
          No prior exits found
        </Box>
      ) : (
        <li>
          {stats.exFoundersWithExit} former{' '}
          {stats.exFoundersWithExit === 1 ? 'founder' : 'founders'} with an exit
        </li>
      )}
    </Section>
  );
}

function RoundItem({ round }: { round: LaunchRadarRound }) {
  const { head, tail } = roundLine(round);
  return (
    <li>
      <b>{head}</b>
      {tail}
    </li>
  );
}

function FundingSection({ funding }: { funding: LaunchRadarCard['funding'] }) {
  const rounds = [...(funding.latestRound ? [funding.latestRound] : []), ...funding.priorRounds];
  return (
    <Section
      label="Funding"
      aside={funding.totalRaisedUsd ? `${funding.totalRaisedUsd} total` : null}
    >
      {rounds.length === 0 ? (
        <Box component="li" sx={{ color: 'text.secondary' }}>
          No funding rounds found
        </Box>
      ) : (
        rounds.map((round, i) => <RoundItem key={i} round={round} />)
      )}
    </Section>
  );
}

/**
 * What went wrong during research (a step failed, ended early, or came back
 * empty). Shown so partial data never reads as "this startup has nothing".
 */
function ResearchIssues({ issues }: { issues: string[] }) {
  return (
    <Box
      component="section"
      aria-label="Research incomplete"
      sx={{ mt: 1.25, color: 'warning.dark' }}
    >
      <Typography component="div" variant="caption" sx={{ fontWeight: 600 }}>
        Research incomplete
      </Typography>
      <Typography component="ul" variant="body2" sx={BULLETS_SX}>
        {issues.map((issue, i) => (
          <li key={i}>{issue}</li>
        ))}
      </Typography>
    </Box>
  );
}

function WhyTheseScores({
  scores,
  incomplete,
}: {
  scores: LaunchRadarCard['scores'];
  incomplete: boolean;
}) {
  const [open, setOpen] = useState(false);
  const talent =
    scores.talent == null
      ? incomplete
        ? 'Talent: not scored, research incomplete'
        : 'Talent: no people data, so no score'
      : `Talent ${scores.talent}: ${scores.talentReasons.join('; ')}`;
  const vc =
    scores.vc == null
      ? incomplete
        ? 'VC: not scored, research incomplete'
        : 'VC: no funding data, so no score'
      : `VC ${scores.vc}: ${scores.vcReasons.join('; ')}`;
  return (
    <Box sx={{ mt: 1.25 }}>
      <Link
        component="button"
        type="button"
        variant="caption"
        color="text.secondary"
        underline="hover"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? '− ' : '+ '}Why these scores
      </Link>
      <Collapse in={open} unmountOnExit>
        <Typography component="ul" variant="body2" color="text.secondary" sx={BULLETS_SX}>
          <li>{talent}</li>
          <li>{vc}</li>
        </Typography>
      </Collapse>
    </Box>
  );
}

/**
 * The opened card: who runs it, who else works there, the money, three
 * highlights, why the scores are what they are, and a footer with the board,
 * the source and what the research cost. Indented under the company name.
 */
export function CardBody({ card }: { card: LaunchRadarCard }) {
  const sourceHost = hostnameOf(card.event?.sourceUrl);
  const highlights = card.notableFacts.slice(0, 3);
  const incomplete = card.issues.length > 0;
  return (
    <Box>
      {incomplete && <ResearchIssues issues={card.issues} />}
      <TeamSection card={card} />
      {card.teamStats && <RestOfTeamSection stats={card.teamStats} />}
      <FundingSection funding={card.funding} />
      {highlights.length > 0 && (
        <Section label="Highlights">
          {highlights.map((fact, i) => (
            <li key={i}>{fact}</li>
          ))}
        </Section>
      )}
      <WhyTheseScores scores={card.scores} incomplete={incomplete} />
      <Typography
        component="div"
        variant="caption"
        color="text.secondary"
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 1.25,
          mt: 1.5,
          pt: 1,
          borderTop: 1,
          borderColor: 'divider',
        }}
      >
        <span>{boardLine(card.ats)}</span>
        <Box component="span" sx={{ display: 'flex', gap: 1.5 }}>
          {card.event?.sourceUrl && sourceHost && (
            <Link
              href={card.event.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              color="inherit"
            >
              {sourceHost}
            </Link>
          )}
          <span>{formatUsd(card.costUsd)} research</span>
        </Box>
      </Typography>
    </Box>
  );
}
