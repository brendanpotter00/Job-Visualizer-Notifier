import type { SearchCompanyResponse } from '../../features/userCompanies/userCompaniesApi';

/**
 * The copy for `NameSearchProgress`, kept pure and kept here.
 *
 * Same split as `companyHealth.ts` next door: the sentences a panel says are the part
 * worth testing without a DOM, and the thing actually worth testing about these is that
 * NO LINE EVER CLAIMS MORE THAN THE PAYLOAD SUPPORTS. Every label carries a number, and
 * every number is one the server measured on this call.
 *
 * See `NameSearchProgress.tsx` for why the steps are revealed after the fact rather
 * than streamed, and why that is honest.
 */

/** One narrated stage. */
export interface NameSearchStep {
  key: string;
  /** The sentence. Always a fact, always with the number in it. */
  label: string;
  /** The one line it may carry under that, or undefined for the usual silence. */
  detail?: string;
  /** Render the detail as machine input — only ever the query we literally sent. */
  mono?: boolean;
  /** This step is genuinely happening now. At most one, and only ever the request. */
  active?: boolean;
}

/** Plural `s`, because every line here counts something. */
function s(n: number): string {
  return n === 1 ? '' : 's';
}

/**
 * Turn a search into the steps that describe it.
 *
 * `result === null` means the request is still out. That is the ONLY state that gets a
 * spinner, and it gets exactly one step, because one step is all we know: the page
 * makes a single HTTP call and there are no intermediate landmarks to report. The
 * SERVER may spend two searches inside it — see `careersSteps` — but we learn that
 * only when the answer lands, so it is narrated after the fact like everything else.
 *
 * A missing `trace` is not an error. This app deploys on Vercel and its API on Railway,
 * so a freshly-shipped client talks to the previous backend for a few minutes after
 * every ship. The narration then gets SHORTER — the stages whose numbers are gone are
 * not estimated, they are not shown.
 */
export function narrateNameSearch(
  query: string,
  result: SearchCompanyResponse | null
): NameSearchStep[] {
  const named = `“${query}”`;
  if (result === null) {
    return [{ key: 'search', label: `Searching the web for ${named}`, active: true }];
  }

  const { trace } = result;
  const steps: NameSearchStep[] = [
    {
      key: 'search',
      label: `Asked the web for ${named}`,
      // THE QUERY IS THE POINT, and this is the one place this file breaks
      // `DiscoveryChecklist`'s rule that a ✓ never shows its `result`. That rule is
      // about engine telemetry ("recorded 14 JSON request(s)") — internals a reader
      // cannot act on, one under every rung, doubling a list built to be scanned.
      // Here the detail lines ARE the evidence: naming the six ATS hosts instead of
      // writing the search a sentence is the difference between 41% and 76%, and the
      // query is short, human-readable, and the whole reason this feature works.
      detail: trace?.query,
      mono: true,
    },
  ];
  if (!trace) {
    return [...steps, ...probeStep(result, null), ...careersSteps(result)];
  }

  steps.push({
    key: 'results',
    label:
      trace.results === 0
        ? 'Nothing came back'
        : `${trace.results} result${s(trace.results)} came back`,
    detail:
      trace.filtered > 0
        ? `${trace.filtered} aggregator or social result${s(trace.filtered)} dropped`
        : undefined,
  });
  // Nothing came back, so there is nothing that could have been scored, resolved or
  // probed. Three more rungs all reading "0" say less than the one line above them.
  // The second search still gets its lines, because it is a real call that was made
  // after this one and its numbers are its own.
  if (trace.results === 0) {
    return [...steps, ...careersSteps(result)];
  }

  const scored = trace.results - trace.filtered;
  if (scored > 0) {
    steps.push({
      key: 'scored',
      label: `Scored ${
        scored === 1 ? 'it' : `all ${scored}`
      } against the six job boards we can read`,
      detail:
        'Our own matcher, not the search ranking — the right board is first about half the time.',
    });
  }
  steps.push({
    key: 'boards',
    label:
      trace.boards === 0
        ? 'None of them was a board we can read'
        : `${trace.boards} turned out to be ${
            trace.boards === 1 ? 'a real job board' : 'real job boards'
          }`,
  });

  return [...steps, ...probeStep(result, trace.boards), ...careersSteps(result)];
}

/**
 * The SECOND search, narrated — and narrated only when it really happened.
 *
 * The server escalates to a plain `"{name} careers"` query when nothing it found was
 * something the user could just accept. That is a second paid call and a second set
 * of numbers, so the panel has to say so: describing one call when two were made is
 * the same lie as inventing progress, just quieter.
 *
 * Gated on `careersSearch` being present, never on `careersUrl`. A URL can also come
 * from the FIRST search's own results (the belt-and-braces path when the second call
 * fails), and claiming a second search on the strength of a URL would narrate a call
 * that never left the building.
 */
function careersSteps(result: SearchCompanyResponse): NameSearchStep[] {
  const careers = result.careersSearch;
  if (!careers) {
    return [];
  }
  const steps: NameSearchStep[] = [
    {
      key: 'careers-search',
      label: 'No board we could add, so we asked again in plain words',
      // Same reason the first query is shown: the query IS the evidence. Dropping
      // the ATS hostnames is the whole difference between being handed
      // `resumeadapter.com` and being handed `oracle.com/careers`.
      detail: careers.query,
      mono: true,
    },
  ];
  if (careers.results === 0) {
    steps.push({ key: 'careers-results', label: 'Nothing came back' });
    return steps;
  }
  steps.push({
    key: 'careers-results',
    label:
      careers.trusted === 0
        ? `None of the ${careers.results} result${s(careers.results)} was on their own site`
        : `${careers.trusted} of ${careers.results} ${
            careers.trusted === 1 ? 'was' : 'were'
          } on their own site`,
    detail:
      careers.filtered > 0
        ? `${careers.filtered} aggregator or social result${s(careers.filtered)} dropped`
        : undefined,
  });
  return steps;
}

/**
 * The live probe — the only stage that cost an outbound request per candidate, and the
 * only one whose numbers the user is about to be asked to judge.
 *
 * `boards` is passed in separately because it is counted BEFORE the five-candidate
 * display cap, and the gap between the two is a real thing to say: "found 8, checked the
 * top 5" is honest, and "checked all 5" when we found 8 is not. `null` means we were not
 * told (no trace), so the claim is not made either way.
 */
function probeStep(result: SearchCompanyResponse, boards: number | null): NameSearchStep[] {
  const probed = result.candidates.length;
  if (probed === 0) {
    return [];
  }
  const answered = result.candidates.filter((found) => found.probe.ok);
  const unread = probed - answered.length;
  const jobs = answered.reduce((total, found) => total + found.probe.jobCount, 0);
  // "N jobs in total" and NOT "N open jobs": the rows below say "794 open jobs" per
  // board, and this line is a different claim — the sum across everything we checked,
  // including boards that are not the one the user will pick. Two lines a few pixels
  // apart reading identically would invite exactly that misreading.
  //
  // A board that answered with zero jobs really did answer, so "0 jobs in total" is the
  // truth and stays — it is also the cheapest signal that we picked the wrong board.
  const detail = [
    answered.length > 0 ? `${jobs.toLocaleString()} job${s(jobs)} in total` : null,
    unread > 0 ? `${unread} could not be read` : null,
  ]
    .filter((part): part is string => part !== null)
    .join(' · ');
  return [
    {
      key: 'probed',
      label:
        boards !== null && boards > probed
          ? `Checked the top ${probed} for open jobs`
          : `Checked ${probed === 1 ? 'it' : `all ${probed}`} for open jobs`,
      detail: detail || undefined,
    },
  ];
}
