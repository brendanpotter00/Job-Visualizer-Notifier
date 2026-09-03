import type { SearchCompanyResponse } from '../../features/userCompanies/userCompaniesApi';

/**
 * The copy AND the row list for `NameSearchProgress`, kept pure and kept here.
 *
 * Same split as `companyHealth.ts` next door: what a panel says is the part worth
 * testing without a DOM, and the thing actually worth testing about these is that
 * NO LINE AND NO ROW EVER CLAIMS MORE THAN THE PAYLOAD SUPPORTS. Every sentence
 * carries a number the server measured on this call, and every row stands for a
 * result that really came back — `trace.nonBoards` for the ones that were not
 * boards, `candidates` for the ones that were, `careersUrl` for the answer.
 *
 * There is no code path here that produces a row from a count. If the backend did
 * not send the URLs, the list is shorter; it is never filled in.
 *
 * See `NameSearchProgress.tsx` for why this is a reveal of data that has already
 * arrived rather than a stream, and why that is honest.
 */

/**
 * One state of the status line — it shows ONE of these at a time, in order.
 *
 * It used to show all of them at once, as a stack of seven ticks, and that was the
 * thing the owner rejected ("I don't like how you have all these steps, it's really
 * confusing"). So the sentences were MERGED as well as stacked differently: what
 * were separate "Scored all 19…", "5 turned out to be real job boards" and
 * "Checked the top 5 for open jobs" ticks are now one sentence with the probe
 * counts as its caption. Nothing was dropped — the numbers all still appear.
 */
export interface NameSearchStep {
  key: string;
  /** The sentence. Always a fact, always with the number in it. */
  label: string;
  /** The one line it may carry under that, or undefined for the usual silence. */
  detail?: string;
  /** Render the detail as machine input — only ever a query we literally sent. */
  mono?: boolean;
  /** This step is genuinely happening now. At most one, and only ever the request. */
  active?: boolean;
}

/**
 * What a row is FOR, which is the same thing as when it leaves.
 *
 * - `discarded` — a result that resolved to no board. Folds away in the first pass.
 * - `rejected`  — a real board whose token does not name the company. Gets its
 *                 verdict late, then folds away in the second pass.
 * - `answer`    — what survives: a board the server confirmed, or the company's own
 *                 careers page.
 */
export type NameSearchRowKind = 'discarded' | 'rejected' | 'answer';

/** One row of the morphing list. Every one of them is a real search result. */
export interface NameSearchRow {
  key: string;
  /** The search engine's own rank, or `—` where the row stands for several. */
  rank: string;
  /** The line the reader recognises the result by. Set in a monospace face. */
  url: string;
  /**
   * A board's identity — `greenhouse · anthropic · 582 open jobs`.
   *
   * Never omitted for a board row, and that is a rule rather than a style: the
   * name-path's worst failure is tracking a stranger's live board, and the token
   * plus the count is the only thing a person can catch it with.
   */
  meta: string | null;
  /** The right-hand verdict: `aggregator`, `not “meta”`, `their own site`. */
  status: string;
  kind: NameSearchRowKind;
  /**
   * This row arrived from the SECOND search, so it lands after the first list has
   * narrowed rather than with it. Only ever the careers page.
   */
  late?: boolean;
}

/** Plural `s`, because most lines here count something. */
function s(n: number): string {
  return n === 1 ? '' : 's';
}

/**
 * Turn a search into the status line's states, in order.
 *
 * `result === null` means the request is still out. That is the ONLY state that
 * gets a spinner, and it gets exactly one line, because one line is all we know:
 * the page makes a single HTTP call and there are no intermediate landmarks to
 * report. The SERVER may spend two searches inside it — see `careersSteps` — but we
 * learn that only when the answer lands, so it is narrated after the fact like
 * everything else.
 *
 * A missing `trace` is not an error. This app deploys on Vercel and its API on
 * Railway, so a freshly-shipped client talks to the previous backend for a few
 * minutes after every ship. The narration then gets SHORTER — the states whose
 * numbers are gone are not estimated, they are not shown.
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
      // THE QUERY IS THE POINT. Naming the six ATS hosts instead of writing the
      // search a sentence is the difference between 41% and 76%, and the query is
      // short, human-readable, and the whole reason this feature works.
      detail: trace?.query,
      mono: true,
    },
  ];
  if (!trace) {
    return [...steps, ...boardsStep(result, null, null), ...careersSteps(result)];
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
  // probed. A second line reading "0" says less than the one above it. The second
  // search still gets its states, because it is a real call made after this one.
  if (trace.results === 0) {
    return [...steps, ...careersSteps(result)];
  }

  return [
    ...steps,
    ...boardsStep(result, trace.boards, trace.results - trace.filtered),
    ...careersSteps(result),
  ];
}

/**
 * The verdict on the boards — what we found, and what checking them cost.
 *
 * THREE OLD TICKS IN ONE LINE. "Scored all 19 against the six job boards we can
 * read", "5 turned out to be real job boards" and "Checked the top 5 for open jobs"
 * were three rungs of a stack saying one thing between them; the merge is the point
 * of this rewrite, and no number went missing in it.
 *
 * `boards` is counted BEFORE the five-candidate display cap, so it is the only
 * field that can say "found 8, checked the top 5". `null` means we were not told
 * (no trace), and then the claim is not made in either direction — the line falls
 * back to the one number we own, which is how many we probed ourselves.
 */
function boardsStep(
  result: SearchCompanyResponse,
  boards: number | null,
  scored: number | null
): NameSearchStep[] {
  const probed = result.candidates.length;
  if (boards === null || scored === null) {
    if (probed === 0) {
      return [];
    }
    return [
      {
        key: 'boards',
        label: `Checked ${probed === 1 ? 'it' : `all ${probed}`} for open jobs`,
        detail: probeDetail(result) ?? undefined,
      },
    ];
  }

  // Every result was an aggregator, so nothing reached the matcher at all. The line
  // above ("6 results came back · 6 aggregator or social results dropped") is the
  // whole story, and "None of the 0 results we scored" would be a sentence about
  // work that did not happen.
  if (scored === 0) {
    return [];
  }
  if (boards === 0) {
    return [
      {
        key: 'boards',
        label:
          scored === 1
            ? 'The one result we scored was not a board we can read'
            : `None of the ${scored} results we scored was a board we can read`,
        // The feature's own argument, and the only place left to say it now that
        // the "Scored all 19…" rung is gone: the search engine only enumerates
        // URLs, and deciding which is a board is our own free pure function over
        // every result — the right board is ranked first about half the time.
        detail: 'Our own matcher, not the search ranking — we score every result.',
      },
    ];
  }
  const counted = `${boards} of the ${scored} result${s(scored)} we scored`;
  return [
    {
      key: 'boards',
      label:
        boards === 1
          ? `${counted} is a real job board`
          : `${counted} are real job boards`,
      detail:
        [
          boards > probed
            ? `Checked the top ${probed} for open jobs`
            : `Checked ${probed === 1 ? 'it' : `all ${probed}`} for open jobs`,
          probeDetail(result),
        ]
          .filter((part): part is string => part !== null)
          .join(' · ') || undefined,
    },
  ];
}

/**
 * What the live probes found, summed — the only stage that cost an outbound
 * request per candidate.
 *
 * "N jobs in total" and NOT "N open jobs": the rows below say "582 open jobs" per
 * board, and this is a different claim — the sum across everything we checked,
 * including boards that are not the one the user will pick. Two numbers a few
 * pixels apart reading identically would invite exactly that misreading.
 *
 * A board that answered with zero jobs really did answer, so "0 jobs in total" is
 * the truth and stays — it is also the cheapest signal that we picked the wrong one.
 */
function probeDetail(result: SearchCompanyResponse): string | null {
  const probed = result.candidates.length;
  if (probed === 0) {
    return null;
  }
  const answered = result.candidates.filter((found) => found.probe.ok);
  const unread = probed - answered.length;
  const jobs = answered.reduce((total, found) => total + found.probe.jobCount, 0);
  return (
    [
      answered.length > 0 ? `${jobs.toLocaleString()} job${s(jobs)} in total` : null,
      unread > 0 ? `${unread} could not be read` : null,
    ]
      .filter((part): part is string => part !== null)
      .join(' · ') || null
  );
}

/**
 * The SECOND search, narrated — and narrated only when it really happened.
 *
 * The server escalates to a plain `"{name} careers"` query when nothing it found
 * was something the user could just accept. That is a second paid call and a second
 * set of numbers, so the panel has to say so: describing one call when two were
 * made is the same lie as inventing progress, just quieter.
 *
 * Gated on `careersSearch` being present, never on `careersUrl`. A URL can also
 * come from the FIRST search's own results (the belt-and-braces path when the
 * second call fails), and claiming a second search on the strength of a URL would
 * narrate a call that never left the building.
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
 * The rows the list narrows through — every one of them a result that came back.
 *
 * ORDER IS THE NARRATION. The results we could not use first, then the boards we
 * could read, then the answer; the first group folds away, then the second, and
 * what is left standing is what the page is about to ask the user to accept.
 *
 * THE ONE ROW THAT DOES NOT STAND FOR ITSELF is the "…and N more results" row, and
 * it says so in its own text. The server caps how many result URLs it sends, and
 * this is the honest way to spend the remainder — a count we were given, not rows
 * we made up. With no cap hit there is no such row.
 */
export function buildNameSearchRows(result: SearchCompanyResponse): NameSearchRow[] {
  const rows: NameSearchRow[] = [];
  const named = `“${result.query}”`;

  for (const row of result.trace?.nonBoards ?? []) {
    rows.push({
      key: `result-${row.rank}`,
      rank: String(row.rank),
      url: row.url,
      meta: null,
      // Two different facts about a result, kept apart: an aggregator was thrown
      // out by a host denylist before anything looked at it, and everything else
      // simply did not resolve to a board.
      status: row.aggregator ? 'aggregator' : 'not a board',
      kind: 'discarded',
    });
  }

  const omitted = result.trace?.nonBoardsOmitted ?? 0;
  if (omitted > 0) {
    rows.push({
      key: 'result-overflow',
      rank: '—',
      url: `…and ${omitted} more result${s(omitted)}`,
      meta: null,
      status: 'not a board',
      kind: 'discarded',
    });
  }

  for (const found of result.candidates) {
    const { ats, boardToken } = found.candidate;
    rows.push({
      key: `board-${ats}:${boardToken}:${found.sourceUrl}`,
      rank: String(found.rank),
      url: found.sourceUrl,
      // The identity and the live count, always — see `NameSearchRow.meta`.
      meta: `${ats} · ${boardToken} · ${
        found.probe.ok
          ? `${found.probe.jobCount.toLocaleString()} open job${s(found.probe.jobCount)}`
          : 'could not read this board'
      }`,
      status: found.autoAddable ? `matches ${named}` : `not ${named}`,
      kind: found.autoAddable ? 'answer' : 'rejected',
    });
  }

  if (result.careersUrl !== null) {
    rows.push({
      key: 'careers',
      // Not a rank: this came from a different search, and giving it a number from
      // the first one's ranking would be a small, pointless lie.
      rank: '✓',
      url: result.careersUrl,
      meta: null,
      status: 'their own site',
      kind: 'answer',
      late: true,
    });
  }

  return rows;
}
