import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { NameSearchProgress } from '../../../components/my-companies/NameSearchProgress';
import { narrateNameSearch } from '../../../components/my-companies/nameSearchNarration';
import type {
  SearchCompanyCandidate,
  SearchCompanyResponse,
} from '../../../features/userCompanies/userCompaniesApi';

/**
 * The narration above the candidate list.
 *
 * ONE RULE UNDER TEST, and everything below is a way of asking it: **no line may claim
 * more than the payload supports.** A name search is a single ~2s HTTP call, so there is
 * exactly one honest in-flight state and no intermediate progress to report; every other
 * step is real data revealed after the fact. A test that let a number appear without a
 * field behind it would be letting the fabricated-progress version back in.
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

/** Every rule emotion emitted for this render, concatenated. */
function emittedCss(): string {
  return Array.from(document.querySelectorAll('style'))
    .map((tag) => tag.textContent ?? '')
    .join('');
}

describe('narrateNameSearch', () => {
  it('gives the in-flight request ONE step, and it is the only spinner there is', () => {
    // A search has no intermediate landmarks. Anything more than one step here would
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
    // 25 came back, 6 were aggregators, so 19 is what scoring actually saw. The three
    // lines are read together on screen, so the arithmetic has to hold.
    expect(labels).toContain('Scored all 19 against the six job boards we can read');
    expect(labels).toContain('3 turned out to be real job boards');
    expect(steps.find((step) => step.key === 'results')?.detail).toBe(
      '6 aggregator or social results dropped'
    );
  });

  it('shows the query verbatim, because the query IS the argument', () => {
    // Naming the six ATS hosts instead of writing the search a sentence is the whole
    // difference between 41% and 76%. It is the one ✓ detail worth a reader's eye.
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
    expect(steps.map((s) => s.label)).toContain('Checked the top 2 for open jobs');
  });

  it('does not repeat the row copy when it sums the probes', () => {
    // The rows below say "1,248 open jobs" for ONE board; this line is a different
    // claim — the total across everything checked, winner and also-rans alike.
    const step = narrateNameSearch('Cisco', response()).find((s) => s.key === 'probed');
    expect(step?.detail).toBe('1,248 jobs in total');
  });

  it('counts a board that could not be read without pretending it answered', () => {
    const steps = narrateNameSearch(
      'Cisco',
      response({
        candidates: [
          candidate(),
          candidate({ probe: { ok: false, jobCount: 0, error: 'timeout' } }),
        ],
      })
    );
    expect(steps.find((s) => s.key === 'probed')?.detail).toBe(
      '1,248 jobs in total · 1 could not be read'
    );
  });

  it('stops after "nothing came back" instead of listing three zeroes', () => {
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
    expect(steps.map((s) => s.key)).toEqual(['search', 'probed']);
    expect(steps[0].detail).toBeUndefined();
    // ...and with no `boards` to compare against, it never claims a "top N" either.
    expect(steps[1].label).toBe('Checked it for open jobs');
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

  it('draws exactly one spinner while the request is out', () => {
    renderWithProviders(<NameSearchProgress query="Cisco" searching result={null} />);
    expect(screen.getAllByLabelText('in progress')).toHaveLength(1);
    expect(screen.getByTestId('name-search-step-search')).toBeInTheDocument();
    expect(screen.queryByTestId('name-search-step-results')).not.toBeInTheDocument();
  });

  it('draws NO spinner once the answer has landed', () => {
    // Every step on screen has already happened, so a spinner — or a pending ○ — over
    // any of them would be the fabricated progress this component exists to refuse.
    renderWithProviders(
      <NameSearchProgress query="Cisco" searching={false} result={response()} />
    );
    expect(screen.queryByLabelText('in progress')).not.toBeInTheDocument();
    expect(screen.getByTestId('name-search-step-probed')).toBeInTheDocument();
  });

  it('ignores a stale answer while a new search is in flight', () => {
    // `searching` wins over `result`: the previous name's numbers must never appear
    // under a spinner carrying the new name.
    renderWithProviders(<NameSearchProgress query="Databricks" searching result={response()} />);
    expect(screen.queryByTestId('name-search-step-results')).not.toBeInTheDocument();
    expect(screen.getByTestId('name-search-step-search')).toHaveTextContent('Databricks');
  });

  it('staggers the reveal with animation-delay and nothing else', () => {
    // NO TIMERS. The whole reveal is `animation-delay`, which is what keeps this
    // component stateless — and stops it being the one thing on the page still
    // animating after the test that rendered it has finished.
    renderWithProviders(
      <NameSearchProgress query="Cisco" searching={false} result={response()} />
    );
    const styles = emittedCss();
    expect(styles).toContain('nameSearchStepIn 260ms ease-out 0ms backwards');
    expect(styles).toContain('nameSearchStepIn 260ms ease-out 220ms backwards');
    expect(styles).toContain('nameSearchStepIn 260ms ease-out 880ms backwards');
  });

  it('turns every one of those animations off under prefers-reduced-motion', () => {
    // EVERY one, not just the first: the guard rides the same rule as the animation,
    // so a step added without it would be the only thing on the page that still moved.
    renderWithProviders(
      <NameSearchProgress query="Cisco" searching={false} result={response()} />
    );
    const styles = emittedCss();
    const animated = styles.match(/animation:nameSearchStepIn/g) ?? [];
    const silenced =
      styles.match(/prefers-reduced-motion: reduce\)\{\.[\w-]+\{[^}]*animation:none/g) ?? [];
    expect(silenced.length).toBe(5); // one per step
    expect(animated.length).toBeGreaterThan(0);
  });
});
