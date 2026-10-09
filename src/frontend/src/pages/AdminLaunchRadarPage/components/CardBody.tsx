import { useState, type ReactNode } from 'react';
import Box from '@mui/material/Box';
import Collapse from '@mui/material/Collapse';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import type {
  LaunchRadarCard,
  LaunchRadarRound,
  LaunchRadarSource,
} from '../../../features/admin/launchRadarTypes';
import {
  boardLine,
  formatUsd,
  groupSources,
  leadersFromBrief,
  researchGaps,
  roundLine,
  summarizeTally,
  talentBreakdown,
} from '../format';

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
      {/* Where these names came from, said quietly: the people search confirmed
          nobody, so the leaders are the brief's founders. Not a research gap. */}
      {leadersFromBrief(card.issues) && (
        <Box component="li" sx={{ color: 'text.secondary' }}>
          Leaders from the company brief
        </Box>
      )}
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
      {/* The tally is schools and employers only: prior exits are checked on the leaders. */}
      {schoolCount === 0 && stats.priorEmployers.length === 0 && (
        <Box component="li" sx={{ color: 'text.secondary' }}>
          No schools or employers listed
        </Box>
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
 * Provenance notes (`researchGaps` leaves them out) are not listed here.
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

/**
 * A collapsed "+ Label" toggle and the details it opens. "Why these scores" and
 * "Sources" share it, so they look and behave alike. The sign is decoration:
 * aria-expanded already says whether it is open, so it is hidden from the name.
 */
function Disclosure({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <Box sx={{ mt: 1.25 }}>
      <Link
        component="button"
        type="button"
        variant="caption"
        color="text.secondary"
        underline="hover"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
      >
        <span aria-hidden="true">{open ? '− ' : '+ '}</span>
        {label}
      </Link>
      <Collapse id={id} in={open} unmountOnExit>
        {children}
      </Collapse>
    </Box>
  );
}

function WhyTheseScores({
  cardId,
  scores,
  incomplete,
}: {
  cardId: number;
  scores: LaunchRadarCard['scores'];
  incomplete: boolean;
}) {
  const talent = talentBreakdown(scores, incomplete);
  const vc =
    scores.vc == null
      ? incomplete
        ? 'VC: not scored, research incomplete'
        : 'VC: no funding data, so no score'
      : `VC ${scores.vc}: ${scores.vcReasons.join('; ')}`;
  return (
    <Disclosure id={`radar-card-${cardId}-why`} label="Why these scores">
      <Typography component="ul" variant="body2" color="text.secondary" sx={BULLETS_SX}>
        <li>
          {talent.line}
          {talent.parts.length > 0 && (
            <Box component="ul" aria-label="Talent parts" sx={BULLETS_SX}>
              {talent.parts.map((part, i) => (
                <li key={i}>{part}</li>
              ))}
            </Box>
          )}
        </li>
        <li>{vc}</li>
      </Typography>
    </Disclosure>
  );
}

/** A group's list: the card's bullets, and long titles or hosts wrap instead of scrolling sideways. */
const SOURCES_LIST_SX = { ...BULLETS_SX, overflowWrap: 'anywhere' } as const;

/**
 * The citations behind the research, grouped by what they back up: the company,
 * its funding, its people. Each opens in a new tab. Not shown when no source can
 * be a link.
 */
function Sources({ cardId, sources }: { cardId: number; sources: readonly LaunchRadarSource[] }) {
  const groups = groupSources(sources);
  const count = groups.reduce((n, g) => n + g.items.length, 0);
  if (count === 0) return null;
  const id = `radar-card-${cardId}-sources`;
  return (
    <Disclosure id={id} label={`Sources (${count})`}>
      {groups.map((group) => {
        const labelId = `${id}-${group.topic}`;
        return (
          <Box key={group.topic} sx={{ mt: 0.75 }}>
            <Typography id={labelId} component="div" variant="caption" sx={{ fontWeight: 600 }}>
              {group.label}
            </Typography>
            <Typography
              component="ul"
              variant="body2"
              aria-labelledby={labelId}
              sx={SOURCES_LIST_SX}
            >
              {group.items.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    color="text.secondary"
                  >
                    {item.text}
                  </Link>
                  {item.detail && (
                    <Typography
                      component="span"
                      variant="caption"
                      color="text.secondary"
                      sx={{ display: 'block' }}
                    >
                      {item.detail}
                    </Typography>
                  )}
                </li>
              ))}
            </Typography>
          </Box>
        );
      })}
    </Disclosure>
  );
}

/**
 * The opened card: who runs it, who else works there, the money, three
 * highlights, why the scores are what they are, the sources behind the research,
 * and a footer with the board and what the research cost. The announcement link
 * lives on the closed card's event line, so the footer does not repeat it.
 * Aligned under the company name.
 */
export function CardBody({ card }: { card: LaunchRadarCard }) {
  const highlights = card.notableFacts.slice(0, 3);
  // A note on where data came from ("leaders from the brief …") rides in
  // `issues` too, but it is not a gap: it must not raise the warning heading or
  // turn a null score into "research incomplete".
  const gaps = researchGaps(card.issues);
  const incomplete = gaps.length > 0;
  return (
    <Box>
      {incomplete && <ResearchIssues issues={gaps} />}
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
      <WhyTheseScores cardId={card.id} scores={card.scores} incomplete={incomplete} />
      <Sources cardId={card.id} sources={card.sources} />
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
        <span>{formatUsd(card.costUsd)} research</span>
      </Typography>
    </Box>
  );
}
