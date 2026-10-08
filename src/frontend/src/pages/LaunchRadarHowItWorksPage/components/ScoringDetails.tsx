import type { ReactNode } from 'react';
import Box from '@mui/material/Box';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import { TABLE_SCROLL_SX } from '../../../config/responsive';

// The rules mirror scripts/launch_radar/scoring.py (TALENT_RUBRIC, score_team,
// blend_talent, VC_TIERS). Change them together.

function Heading({ children }: { children: ReactNode }) {
  return (
    <Typography variant="subtitle2" component="h3" color="text.secondary" sx={{ mt: 2, mb: 0.75 }}>
      {children}
    </Typography>
  );
}

function Formula({ children }: { children: ReactNode }) {
  return (
    <Typography
      variant="body2"
      sx={{ bgcolor: 'background.paper', borderRadius: 1, px: 1.5, py: 1.25, mb: 1.5 }}
    >
      {children}
    </Typography>
  );
}

function Notes({ items }: { items: ReactNode[] }) {
  return (
    <Box component="ul" sx={{ m: 0, mb: 1, pl: 2.25, typography: 'body2' }}>
      {items.map((item, i) => (
        <Box component="li" key={i} sx={{ mt: i ? 0.25 : 0 }}>
          {item}
        </Box>
      ))}
    </Box>
  );
}

function RulesTable({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <Box sx={{ ...TABLE_SCROLL_SX, mb: 1 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            {head.map((h, i) => (
              <TableCell
                key={h}
                sx={{
                  color: 'text.secondary',
                  fontWeight: 600,
                  pl: 0,
                  pr: i < head.length - 1 ? 2 : 0,
                }}
              >
                {h}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row[0]}>
              {row.map((cell, i) => (
                <TableCell
                  key={i}
                  sx={{
                    pl: 0,
                    pr: i < row.length - 1 ? 2 : 0,
                    whiteSpace: i ? 'nowrap' : 'normal',
                    verticalAlign: 'top',
                  }}
                >
                  {cell}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

/** How a card's Talent and VC scores are worked out, with one real card as the example. */
export function ScoringDetails() {
  return (
    <>
      <Formula>
        <b>Talent</b> = leaders (0–50) + team (0–50)
      </Formula>

      <Heading>Leaders, from “Research each leader”</Heading>
      <RulesTable
        head={['Each leader with', 'Points', 'Max']}
        rows={[
          ['A top school', '+8', '24'],
          ['A top employer', '+10', '30'],
          ['A prior exit (acquired or IPO)', '+15', '30'],
          ['10+ years of experience', '+5', '10'],
        ]}
      />
      <Notes
        items={[
          'The total (up to 94) is scaled to 50.',
          'Founding a company scores nothing. Only an exit counts.',
          'Medium-confidence facts count at 80%, low at 50%.',
        ]}
      />

      <Heading>Team, from “Tally the rest of the team”</Heading>
      <RulesTable
        head={['Share of profiles with', 'Max']}
        rows={[
          ['A top school', '25'],
          ['A top employer', '25'],
        ]}
      />
      <Notes
        items={[
          'Full points when half of the profiles have one.',
          'Under 5 profiles, the rest of the team part follows the leaders.',
          'One part missing: the other part is doubled.',
          'Both missing: Talent shows a dash, not 0.',
        ]}
      />

      <Box sx={{ mt: 2.5 }}>
        <Formula>
          <b>VC</b> = best investor + extra investors + round size, up to 100
        </Formula>
      </Box>
      <RulesTable
        head={['Investor', 'Led', 'Joined', 'Each extra']}
        rows={[
          ['Tier 1: Sequoia, a16z, Benchmark, Founders Fund, Accel …', '60', '45', '+10, up to 30'],
          ['Tier 2: CRV, Felicis, First Round, Spark, 8VC …', '35', '25', '+5, up to 15'],
          ['Y Combinator', '15', '15', '–'],
          ['Any other named investor', '10', '10', '–'],
        ]}
      />
      <Notes items={['Round over $50M +15, over $20M +10, over $10M +5.']} />

      <Heading>Example: Lightfield</Heading>
      <Notes
        items={[
          <>
            <b>Talent 67</b> = leaders 37 + team 30.
          </>,
          'Leaders: Stanford, Waterloo, Cornell and Georgia Tech; Facebook and Meta; one exit (Tome, acquired by AngelList); five leaders with 10+ years.',
          'Team: 15 of 48 schools are top schools (+16); 9 of 21 employers are top employers (+14).',
          <>
            <b>VC 100</b>: a16z led; Coatue, Greylock, Lightspeed and 8VC joined; a $47M round.
          </>,
        ]}
      />

      <Heading>Post</Heading>
      <Notes items={['One card per company domain, in the New tab of the admin page.']} />
    </>
  );
}
