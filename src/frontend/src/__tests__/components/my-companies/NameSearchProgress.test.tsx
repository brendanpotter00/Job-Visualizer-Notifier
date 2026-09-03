import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { NameSearchProgress } from '../../../components/my-companies/NameSearchProgress';
import { morphTimeline } from '../../../components/my-companies/nameSearchMorph';
import {
  buildNameSearchRows,
  narrateNameSearch,
} from '../../../components/my-companies/nameSearchNarration';
import type {
  SearchCompanyCandidate,
  SearchCompanyResponse,
} from '../../../features/userCompanies/userCompaniesApi';

/**
 * The narration above the answer — one list that narrows to it.
 *
 * ONE RULE UNDER TEST, and everything below is a way of asking it: **nothing on
 * screen may claim more than the payload supports.** A name search is a single ~2s
 * HTTP call, so there is exactly one honest in-flight state and no intermediate
 * progress to report; every sentence after that is real data revealed after the
 * fact, and every ROW is a result the server actually sent us. A test that let a
 * row appear without a URL behind it would be letting the fabricated version in
 * through the door the numbers are already locked against.
 */

const QUERY =
  'Cisco jobs myworkdayjobs.com greenhouse.io ashbyhq.com lever.co jobs.gem.com eightfold.ai';

function candidate(overrides: Partial<SearchCompanyCandidate> = {}): SearchCompanyCandidate {
  return {
    candidate: {
      ats: 'workday',
      boardToken: 'cisco',
      providerConfig: {},
      sourceUrl: 'https://cisco.wd5.myworkdayjobs.com/Cisco_Careers',
    },
    probe: { ok: true, jobCount: 1248, error: null },
    sourceUrl: 'https://cisco.wd5.myworkdayjobs.com/Cisco_Careers',
    title: 'Cisco Careers',
    rank: 1,
    autoAddable: true,
    ...overrides,
  };
}

function response(overrides: Partial<SearchCompanyResponse> = {}): SearchCompanyResponse {
  return {
    query: 'Cisco',
    candidates: [candidate()],
    careersUrl: null,
    trace: { query: QUERY, results: 25, filtered: 6, boards: 3 },
    ...overrides,
  };
}

/** Every rule emitted for this render, concatenated. */
function emittedCss(): string {
  return Array.from(document.querySelectorAll('style'))
    .map((tag) => tag.textContent ?? '')
    .join('');
}

describe('narrateNameSearch', () => {
  it('gives the in-flight request ONE line, and it is the only spinner there is', () => {
    // A search has no intermediate landmarks. Anything more than one line here would
    // be a stage invented to fill two seconds.
    const steps = narrateNameSearch('Cisco', null);
    expect(steps).toHaveLength(1);
    expect(steps[0].active).toBe(true);
    expect(steps[0].label).toContain('Cisco');
  });

  it('reports the numbers the server measured, and they add up', () => {
    const steps = narrateNameSearch('Cisco', response());
    const labels = steps.map((step) => step.label);

    expect(labels).toContain('25 results came back');
    // 25 came back, 6 were aggregators, so 19 is what scoring actually saw — and the
    // three boards came out of those 19. The line is read whole, so the arithmetic
    // has to hold inside it.
    expect(labels).toContain('3 of the 19 results we scored are real job boards');
    expect(steps.find((step) => step.key === 'results')?.detail).toBe(
      '6 aggregator or social results dropped'
    );
  });

  it('says the whole board verdict in ONE line, not three ticks', () => {
    // "Scored all 19…", "3 turned out to be real job boards" and "Checked all 3 for
    // open jobs" used to be three rungs of a stack saying one thing between them.
    // They are merged now — and nothing went missing in the merge.
    const steps = narrateNameSearch(
      'Cisco',
      response({ trace: { query: QUERY, results: 25, filtered: 6, boards: 1 } })
    );
    expect(steps.map((step) => step.key)).not.toContain('scored');
    expect(steps.map((step) => step.key)).not.toContain('probed');
    const boards = steps.find((step) => step.key === 'boards');
    expect(boards?.label).toBe('1 of the 19 results we scored is a real job board');
    expect(boards?.detail).toBe('Checked it for open jobs · 1,248 jobs in total');
  });

  it('shows the query verbatim, because the query IS the argument', () => {
    // Naming the six ATS hosts instead of writing the search a sentence is the whole
    // difference between 41% and 76%. It is the one caption worth a reader's eye.
    const step = narrateNameSearch('Cisco', response()).find((s) => s.key === 'search');
    expect(step?.detail).toBe(QUERY);
    expect(step?.mono).toBe(true);
  });

  it('says it checked the TOP few when more boards were found than shown', () => {
    // `boards` is counted before the five-candidate display cap. "Checked all 2" when
    // eight were found would be the panel quietly under-reporting its own work.
    const steps = narrateNameSearch(
      'Acme',
      response({
        candidates: [candidate(), candidate()],
        trace: { query: QUERY, results: 25, filtered: 0, boards: 8 },
      })
    );
    expect(steps.find((s) => s.key === 'boards')?.detail).toContain(
      'Checked the top 2 for open jobs'
    );
  });

  it('does not repeat the row copy when it sums the probes', () => {
    // The rows say "1,248 open jobs" for ONE board; this caption is a different
    // claim — the total across everything checked, winner and also-rans alike.
    const steps = narrateNameSearch(
      'Cisco',
      response({
        candidates: [candidate(), candidate()],
        trace: { query: QUERY, results: 25, filtered: 6, boards: 2 },
      })
    );
    expect(steps.find((s) => s.key === 'boards')?.detail).toBe(
      'Checked all 2 for open jobs · 2,496 jobs in total'
    );
  });

  it('counts a board that could not be read without pretending it answered', () => {
    const steps = narrateNameSearch(
      'Cisco',
      response({
        candidates: [
          candidate(),
          candidate({ probe: { ok: false, jobCount: 0, error: 'timeout' } }),
        ],
        trace: { query: QUERY, results: 25, filtered: 6, boards: 2 },
      })
    );
    expect(steps.find((s) => s.key === 'boards')?.detail).toBe(
      'Checked all 2 for open jobs · 1,248 jobs in total · 1 could not be read'
    );
  });

  it('says plainly when nothing we scored was a board', () => {
    const steps = narrateNameSearch(
      'Meta',
      response({
        candidates: [],
        trace: { query: QUERY, results: 25, filtered: 6, boards: 0 },
      })
    );
    expect(steps.find((s) => s.key === 'boards')?.label).toBe(
      'None of the 19 results we scored was a board we can read'
    );
  });

  it('says nothing about scoring when every result was an aggregator', () => {
    // Nothing reached the matcher, so there is no verdict to give. "None of the 0
    // results we scored" would be a sentence about work that did not happen.
    const steps = narrateNameSearch(
      'Meta',
      response({
        candidates: [],
        trace: { query: QUERY, results: 6, filtered: 6, boards: 0 },
      })
    );
    expect(steps.map((s) => s.key)).toEqual(['search', 'results']);
    expect(steps[1].detail).toBe('6 aggregator or social results dropped');
  });

  it('stops after "nothing came back" instead of listing zeroes', () => {
    const steps = narrateNameSearch(
      'Obscure Co',
      response({
        candidates: [],
        trace: { query: QUERY, results: 0, filtered: 0, boards: 0 },
      })
    );
    expect(steps.map((s) => s.key)).toEqual(['search', 'results']);
    expect(steps[1].label).toBe('Nothing came back');
  });

  it('says a SECOND search happened, when a second search happened', () => {
    // The server escalates to a plain query when nothing it found was addable. That
    // is a second paid call with its own numbers, so describing one call would be
    // the same lie as inventing progress — just quieter.
    const steps = narrateNameSearch(
      'Oracle',
      response({
        candidates: [],
        trace: { query: QUERY, results: 23, filtered: 2, boards: 0 },
        careersUrl: 'https://www.oracle.com/careers/',
        careersSearch: { query: 'Oracle careers', results: 25, filtered: 4, trusted: 3 },
      })
    );
    const step = steps.find((s) => s.key === 'careers-search');
    expect(step?.label).toBe('No board we could add, so we asked again in plain words');
    // The query is shown for the same reason the first one is: dropping the ATS
    // hostnames IS the fix, and it is legible in one glance.
    expect(step?.detail).toBe('Oracle careers');
    expect(step?.mono).toBe(true);
    expect(steps.find((s) => s.key === 'careers-results')?.label).toBe(
      '3 of 25 were on their own site'
    );
    expect(steps.find((s) => s.key === 'careers-results')?.detail).toBe(
      '4 aggregator or social results dropped'
    );
  });

  it('says so plainly when the second search found nothing of theirs', () => {
    // Zero trusted results is why nothing is offered, so it is the one number that
    // explains the "paste the URL of their careers page" the user is about to read.
    const steps = narrateNameSearch(
      'Zzyzx',
      response({
        candidates: [],
        trace: { query: QUERY, results: 4, filtered: 0, boards: 0 },
        careersUrl: null,
        careersSearch: { query: 'Zzyzx careers', results: 25, filtered: 0, trusted: 0 },
      })
    );
    expect(steps.find((s) => s.key === 'careers-results')?.label).toBe(
      'None of the 25 results was on their own site'
    );
  });

  it('never mentions a second search that did not happen', () => {
    // THE HONESTY RULE, in the direction that matters. `careersUrl` can also come
    // from the FIRST search's own results, so a URL is not evidence of a second call
    // — only `careersSearch` is.
    const steps = narrateNameSearch(
      'Tesla',
      response({
        candidates: [],
        trace: { query: QUERY, results: 22, filtered: 0, boards: 0 },
        careersUrl: 'https://www.tesla.com/careers',
      })
    );
    expect(steps.map((s) => s.key)).not.toContain('careers-search');
    expect(steps.map((s) => s.key)).not.toContain('careers-results');
  });

  it('gets SHORTER, never invented, when the backend sent no trace', () => {
    // Vercel and Railway deploy separately, so a new client talks to the previous
    // backend for a few minutes after every ship. The stages whose numbers are gone
    // must not be guessed at.
    const steps = narrateNameSearch('Cisco', response({ trace: undefined }));
    expect(steps.map((s) => s.key)).toEqual(['search', 'boards']);
    expect(steps[0].detail).toBeUndefined();
    // ...and with no `boards` to compare against, it never claims a "top N" either.
    expect(steps[1].label).toBe('Checked it for open jobs');
  });
});

describe('buildNameSearchRows', () => {
  it('draws a row for every result the server actually named, and none it did not', () => {
    const rows = buildNameSearchRows(
      response({
        candidates: [],
        trace: {
          query: QUERY,
          results: 25,
          filtered: 1,
          boards: 0,
          nonBoards: [
            { url: 'https://www.linkedin.com/jobs/cisco', rank: 1, aggregator: true },
            { url: 'https://medium.com/@dev/ats', rank: 3, aggregator: false },
          ],
          nonBoardsOmitted: 0,
        },
      })
    );
    expect(rows.map((row) => [row.url, row.status, row.kind])).toEqual([
      ['https://www.linkedin.com/jobs/cisco', 'aggregator', 'discarded'],
      ['https://medium.com/@dev/ats', 'not a board', 'discarded'],
    ]);
  });

  it('draws NOTHING for results it was not sent the URLs of', () => {
    // The whole point. An older backend sends counts and no `nonBoards`; the list is
    // shorter, and there is no code path that turns "25 results" into 25 rows.
    const rows = buildNameSearchRows(
      response({ candidates: [], trace: { query: QUERY, results: 25, filtered: 6, boards: 0 } })
    );
    expect(rows).toEqual([]);
  });

  it('spends the server’s remainder on ONE row that says it stands for many', () => {
    const rows = buildNameSearchRows(
      response({
        candidates: [],
        trace: {
          query: QUERY,
          results: 25,
          filtered: 0,
          boards: 0,
          nonBoards: [{ url: 'https://example.com/a', rank: 1, aggregator: false }],
          nonBoardsOmitted: 18,
        },
      })
    );
    expect(rows[1].url).toBe('…and 18 more results');
    expect(rows[1].rank).toBe('—');
    expect(rows[1].kind).toBe('discarded');
  });

  it('carries a board’s token and its live count on every board row', () => {
    // The name path's worst failure is tracking a stranger's live board. The token
    // and the count are the only things a person can catch that with, so they are
    // never collapsed away — here or in `CompanyCandidateList`.
    const rows = buildNameSearchRows(
      response({
        query: 'Meta',
        candidates: [
          candidate({
            candidate: {
              ats: 'greenhouse',
              boardToken: 'anthropic',
              providerConfig: {},
              sourceUrl: 'https://job-boards.greenhouse.io/anthropic',
            },
            sourceUrl: 'https://job-boards.greenhouse.io/anthropic',
            probe: { ok: true, jobCount: 582, error: null },
            autoAddable: false,
            rank: 15,
          }),
        ],
      })
    );
    expect(rows[0].meta).toBe('greenhouse · anthropic · 582 open jobs');
    expect(rows[0].rank).toBe('15');
    // The verdict names the company it was measured against, exactly as the gate did.
    expect(rows[0].status).toBe('not “Meta”');
    expect(rows[0].kind).toBe('rejected');
  });

  it('makes a confirmed board an answer, and a careers page a LATE answer', () => {
    const confirmed = buildNameSearchRows(response())[0];
    expect(confirmed.kind).toBe('answer');
    expect(confirmed.status).toBe('matches “Cisco”');
    expect(confirmed.late).toBeUndefined();

    const rows = buildNameSearchRows(
      response({
        query: 'Meta',
        candidates: [],
        careersUrl: 'https://www.metacareers.com',
      })
    );
    // It came from the SECOND search, so it lands after the first list has narrowed.
    expect(rows).toEqual([
      {
        key: 'careers',
        rank: '✓',
        url: 'https://www.metacareers.com',
        meta: null,
        status: 'their own site',
        kind: 'answer',
        late: true,
      },
    ]);
  });
});

describe('morphTimeline', () => {
  const junk = (n: number) =>
    Array.from({ length: n }, (_, i) => ({
      key: `j${i}`,
      rank: String(i + 1),
      url: `https://example.com/${i}`,
      meta: null,
      status: 'not a board',
      kind: 'discarded' as const,
    }));
  const board = (autoAddable: boolean) => ({
    key: `b${autoAddable}`,
    rank: '9',
    url: 'https://job-boards.greenhouse.io/anthropic',
    meta: 'greenhouse · anthropic · 582 open jobs',
    status: 'not “Meta”',
    kind: (autoAddable ? 'answer' : 'rejected') as 'answer' | 'rejected',
  });
  const careers = {
    key: 'careers',
    rank: '✓',
    url: 'https://www.metacareers.com',
    meta: null,
    status: 'their own site',
    kind: 'answer' as const,
    late: true,
  };

  it('folds the junk, then the boards, and lands the answer after both', () => {
    const rows = [...junk(2), board(false), careers];
    const timeline = morphTimeline(rows);
    const [first, second, rejected, answer] = timeline.rows;

    // Everything but the late answer lands in a stagger, from zero.
    expect([first.inAt, second.inAt, rejected.inAt]).toEqual([0, 60, 120]);
    // The junk goes first, the board after it, and the answer arrives last of all.
    expect(first.outAt).toBeLessThan(rejected.outAt!);
    expect(answer.outAt).toBeNull();
    expect(answer.inAt).toBeGreaterThan(rejected.outAt!);
    // The verdicts appear between the two folds, which is what "not Meta as it goes"
    // means: after the junk has gone, before the boards do.
    expect(timeline.verdictAt).toBeGreaterThan(first.outAt!);
    expect(timeline.verdictAt).toBeLessThan(rejected.outAt!);
    expect(timeline.totalMs).toBeGreaterThan(answer.inAt);
  });

  it('never folds a list to nothing — with no survivors, everything stays', () => {
    // 25 junk results, no board, no careers page. A list that folded itself away to
    // an empty box would be the panel deleting its own evidence.
    const timeline = morphTimeline(junk(3));
    expect(timeline.rows.map((row) => row.outAt)).toEqual([null, null, null]);
  });

  it('keeps the boards when there is no answer to narrow to', () => {
    // Nothing was confirmed and no careers page came back: the boards we found are
    // the most we have, and `CompanyCandidateList` is about to offer them.
    const timeline = morphTimeline([...junk(1), board(false)]);
    expect(timeline.rows[0].outAt).not.toBeNull(); // the junk still goes
    expect(timeline.rows[1].outAt).toBeNull(); // the board stays
  });
});

describe('NameSearchProgress', () => {
  it('renders nothing when no search is in play', () => {
    const { container } = renderWithProviders(
      <NameSearchProgress query={null} searching={false} result={null} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing once the answer has been cleared', () => {
    // The panel must not outlive the question it explains.
    const { container } = renderWithProviders(
      <NameSearchProgress query="Cisco" searching={false} result={null} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('draws exactly one spinner and no rows while the request is out', () => {
    renderWithProviders(<NameSearchProgress query="Cisco" searching result={null} />);
    expect(screen.getAllByLabelText('in progress')).toHaveLength(1);
    expect(screen.getByTestId('name-search-step-search')).toBeInTheDocument();
    // Nothing has come back, so there is nothing to draw a row for.
    expect(screen.queryByTestId('name-search-rows')).not.toBeInTheDocument();
  });

  it('draws NO spinner once the answer has landed', () => {
    // Every sentence on screen describes something that has already happened, so a
    // spinner over any of them would be the fabricated progress this refuses.
    renderWithProviders(
      <NameSearchProgress query="Cisco" searching={false} result={response()} />
    );
    expect(screen.queryByLabelText('in progress')).not.toBeInTheDocument();
    expect(screen.getByTestId('name-search-step-boards')).toBeInTheDocument();
  });

  it('ignores a stale answer while a new search is in flight', () => {
    // `searching` wins over `result`: the previous name's numbers must never appear
    // under a spinner carrying the new name.
    renderWithProviders(<NameSearchProgress query="Databricks" searching result={response()} />);
    expect(screen.queryByTestId('name-search-step-results')).not.toBeInTheDocument();
    expect(screen.getByTestId('name-search-step-search')).toHaveTextContent('Databricks');
  });

  it('renders one row per real result, and the fold reaches the careers answer', () => {
    renderWithProviders(
      <NameSearchProgress
        query="Meta"
        searching={false}
        result={response({
          query: 'Meta',
          candidates: [
            candidate({
              candidate: {
                ats: 'greenhouse',
                boardToken: 'anthropic',
                providerConfig: {},
                sourceUrl: 'https://job-boards.greenhouse.io/anthropic',
              },
              sourceUrl: 'https://job-boards.greenhouse.io/anthropic',
              probe: { ok: true, jobCount: 582, error: null },
              autoAddable: false,
              rank: 15,
            }),
          ],
          careersUrl: 'https://www.metacareers.com',
          trace: {
            query: QUERY,
            results: 25,
            filtered: 1,
            boards: 1,
            nonBoards: [
              { url: 'https://www.reddit.com/r/cscareerquestions', rank: 1, aggregator: true },
            ],
            nonBoardsOmitted: 18,
          },
        })}
      />
    );

    const rows = screen.getAllByTestId('name-search-row');
    expect(rows.map((row) => row.dataset.kind)).toEqual([
      'discarded', // reddit
      'discarded', // …and 18 more
      'rejected', // anthropic's board — a real board, not Meta's
      'answer', // metacareers.com, the thing left standing
    ]);
    expect(rows[3]).toHaveTextContent('https://www.metacareers.com');
    expect(rows[3]).toHaveTextContent('their own site');
    // The board keeps its identity on screen, which is the whole mitigation.
    expect(rows[2]).toHaveTextContent('greenhouse · anthropic · 582 open jobs');
    expect(rows[2]).toHaveTextContent('not “Meta”');
  });

  it('drives the whole morph from animation-delay and nothing else', () => {
    // NO TIMERS. That is what keeps this component stateless — and stops it being
    // the one thing on the page still animating after the test that rendered it has
    // finished.
    renderWithProviders(
      <NameSearchProgress
        query="Meta"
        searching={false}
        result={response({
          query: 'Meta',
          candidates: [candidate({ autoAddable: false })],
          careersUrl: 'https://www.metacareers.com',
          trace: {
            query: QUERY,
            results: 25,
            filtered: 0,
            boards: 1,
            nonBoards: [{ url: 'https://example.com/a', rank: 2, aggregator: false }],
            nonBoardsOmitted: 0,
          },
        })}
      />
    );
    const styles = emittedCss();
    // Rows arrive on the same 260ms fade+rise `DiscoveryNetworkLog` gives a request.
    expect(styles).toContain('nameSearchRowIn 260ms ease-out 0ms backwards');
    // ...and leave on a collapse that holds its end state.
    expect(styles).toMatch(/nameSearchRowOut 300ms cubic-bezier\(0\.4, 0, 0\.2, 1\) \d+ms forwards/);
    // The careers page GROWS in from nothing, because it arrived from a second call.
    expect(styles).toMatch(/nameSearchRowGrow 260ms ease-out \d+ms backwards/);
    // The status line cross-fades rather than stacking.
    expect(styles).toMatch(/nameSearchStatusIn 220ms ease-out 0ms backwards/);
    expect(styles).toMatch(/nameSearchStatusOut 220ms ease-in \d+ms forwards/);
  });

  it('gives reduced motion the END STATE, not every row at once', () => {
    // The point of the morph is what survives it, so a reader who cannot have motion
    // should see the answer — never eleven rows and five sentences painted at once.
    renderWithProviders(
      <NameSearchProgress
        query="Meta"
        searching={false}
        result={response({
          query: 'Meta',
          candidates: [candidate({ autoAddable: false })],
          careersUrl: 'https://www.metacareers.com',
          trace: {
            query: QUERY,
            results: 25,
            filtered: 0,
            boards: 1,
            nonBoards: [{ url: 'https://example.com/a', rank: 2, aggregator: false }],
            nonBoardsOmitted: 0,
          },
        })}
      />
    );
    const styles = emittedCss();
    // EVERY animated element is switched off, not just the first: the guard rides the
    // same rule as the animation, so anything added without it would be the only thing
    // on the page that still moved. Checked per class rather than by counting, because
    // emotion's `<style>` tags accumulate across every render in this file.
    const animated = Array.from(
      document.querySelectorAll(
        '[data-testid="name-search-row"], [data-testid^="name-search-step-"]'
      )
    )
      .flatMap((el) => Array.from(el.classList))
      .filter((name) => name.startsWith('css-'));
    expect(animated.length).toBeGreaterThan(0);
    for (const name of animated) {
      expect(styles).toContain(
        `@media (prefers-reduced-motion: reduce){.${name}{-webkit-animation:none;animation:none`
      );
    }
    // ...and the rows that fold are simply not rendered under it — the END STATE.
    expect(styles).toMatch(/prefers-reduced-motion: reduce\)\{[^}]*display:none/);
  });
});
