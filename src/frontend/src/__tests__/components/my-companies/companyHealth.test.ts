import { describe, it, expect } from 'vitest';
import {
  DISCOVERY_STEP_LABELS,
  describeCompanyHealth,
  describeDiscoveryOutcome,
  describeDiscoveryStep,
  describeHealthState,
  describeLastFetched,
  describePartialScope,
  failedDiscoveryStep,
  isFirstScanInFlight,
  resolveDiscoveryOutcome,
  shouldExpandDiscovery,
  shouldShowDiscovery,
  sourceBoardLabel,
  sourceBoardUrl,
} from '../../../components/my-companies/companyHealth';
import type {
  DiscoveryProgress,
  DiscoveryStep,
  DiscoveryStepKey,
} from '../../../features/userCompanies/userCompaniesApi';

describe('describeHealthState', () => {
  it('frames the provisional discovering state as "Setting up…", not an error', () => {
    const badge = describeHealthState('discovering');
    expect(badge.label).toMatch(/setting up/i);
    expect(badge.color).toBe('info');
  });

  it('says a tracked board is tracked — in green — before it is verified', () => {
    // The defect this pins: `unverified` shipped as a BLUE "Tracking — building
    // history" chip, which reads as "something here is still wrong" on a board that
    // is working. A board we are successfully reading says so, in the success colour.
    const badge = describeHealthState('unverified');
    expect(badge.label).toBe('Successfully tracking');
    expect(badge.color).toBe('success');
  });

  it('says exactly the same thing once the board graduates to healthy', () => {
    // `unverified` vs `healthy` is whether WE have an oracle for the board yet. The
    // user cannot act on that, so two different chips for it is a distinction they
    // are made to learn for nothing.
    expect(describeHealthState('healthy')).toEqual(describeHealthState('unverified'));
  });

  it('maps the other known states to distinct colors', () => {
    expect(describeHealthState('discovering').color).toBe('info');
    expect(describeHealthState('quarantined').color).toBe('warning');
    expect(describeHealthState('refused').color).toBe('error');
  });

  it('keeps the whole set in one vocabulary', () => {
    // Four states, four colours, one family of words — a person reading a list of
    // rows should be able to sort them without a legend.
    expect(describeHealthState('discovering').label).toBe('Setting up…');
    expect(describeHealthState('unverified').label).toBe('Successfully tracking');
    expect(describeHealthState('quarantined').label).toBe('Tracking paused');
    expect(describeHealthState('refused').label).toBe('Not trackable');
  });

  it('echoes an unknown/newer code verbatim rather than blanking the chip', () => {
    const badge = describeHealthState('some_future_state');
    expect(badge.label).toBe('some_future_state');
    expect(badge.color).toBe('default');
  });

  it('never returns an empty label, even for an empty string', () => {
    expect(describeHealthState('').label).not.toBe('');
  });
});

describe('describeLastFetched', () => {
  const FETCHED_AT = '2026-08-09T10:00:00Z';
  const fetchedAtMs = Date.parse(FETCHED_AT);
  const MINUTE = 60_000;
  const HOUR = 60 * MINUTE;
  const DAY = 24 * HOUR;

  it('says "Not fetched yet" before the first harvest (null)', () => {
    expect(describeLastFetched({ lastSuccessAt: null }, fetchedAtMs)).toEqual({
      label: 'Not fetched yet',
      exactAt: null,
    });
  });

  it('treats an unparseable timestamp as never-fetched rather than "Invalid Date"', () => {
    expect(describeLastFetched({ lastSuccessAt: 'not-a-date' }, fetchedAtMs).label).toBe(
      'Not fetched yet'
    );
  });

  // THE DEFECT. `lastSuccessAt` only moves on a run that did NOT fail, so "checked" was a
  // claim about looking that a nightly-failing board disproved every night. Nothing on this
  // row may imply we have not looked since — only that this is when we last GOT jobs.
  it('never says "checked" — the stamp is the last successful fetch, not the last attempt', () => {
    const line = describeLastFetched({ lastSuccessAt: FETCHED_AT }, fetchedAtMs + 3 * DAY);
    expect(line.label).toBe('Last fetched 3 days ago');
    expect(line.label).not.toMatch(/check/i);
    // ...and not "full"/"complete" either: this same stamp is written by a knowingly
    // PARTIAL read (Microsoft's 2,055 of 2,075), so a completeness claim is the same bug.
    expect(line.label).not.toMatch(/full|complete/i);
  });

  it('counts in the coarsest unit that fits, singular at one', () => {
    const at = (offsetMs: number) =>
      describeLastFetched({ lastSuccessAt: FETCHED_AT }, fetchedAtMs + offsetMs).label;

    expect(at(30_000)).toBe('Last fetched just now');
    expect(at(MINUTE)).toBe('Last fetched 1 minute ago');
    expect(at(45 * MINUTE)).toBe('Last fetched 45 minutes ago');
    expect(at(HOUR)).toBe('Last fetched 1 hour ago');
    expect(at(5 * HOUR)).toBe('Last fetched 5 hours ago');
    expect(at(DAY)).toBe('Last fetched 1 day ago');
    expect(at(6 * DAY)).toBe('Last fetched 6 days ago');
  });

  // Pins the ROUNDING DIRECTION, which every boundary-exact case above leaves free: a
  // part-used unit is dropped, the "one and a bit" reading, not rounded up to the next
  // one. Without this the phrase could silently flip to ceiling and read 61 minutes as
  // "2 hours ago".
  it('drops the part-unit rather than rounding up to the next one', () => {
    const at = (offsetMs: number) =>
      describeLastFetched({ lastSuccessAt: FETCHED_AT }, fetchedAtMs + offsetMs).label;

    expect(at(HOUR + 59 * MINUTE)).toBe('Last fetched 1 hour ago');
    expect(at(90 * MINUTE)).toBe('Last fetched 1 hour ago');
    expect(at(DAY + 23 * HOUR)).toBe('Last fetched 1 day ago');
  });

  it('keeps the exact instant for the tooltip, so rounding loses nothing', () => {
    const line = describeLastFetched({ lastSuccessAt: FETCHED_AT }, fetchedAtMs + 2 * HOUR);
    expect(line.label).toBe('Last fetched 2 hours ago');
    expect(line.exactAt).toBe(new Date(FETCHED_AT).toLocaleString());
  });

  // A stamp AHEAD of the payload is clock skew between the server and this browser, not a
  // fetch from the future — the same call `isDiscoveryLive` makes. It must never render a
  // negative age.
  it('reads a forward-dated stamp as clock skew, not a negative age', () => {
    expect(describeLastFetched({ lastSuccessAt: FETCHED_AT }, fetchedAtMs - 5 * MINUTE).label).toBe(
      'Last fetched just now'
    );
  });

  // Past a month the relative phrase is arithmetic the reader has to undo.
  it('falls back to the date once the age passes a month', () => {
    const line = describeLastFetched({ lastSuccessAt: FETCHED_AT }, fetchedAtMs + 40 * DAY);
    expect(line.label).toBe(`Last fetched ${new Date(FETCHED_AT).toLocaleDateString()}`);
  });

  // `receivedAt` is `fulfilledTimeStamp ?? 0`. Measuring an age against the epoch would
  // make every board look freshly fetched — a new lie in place of the old one.
  it('shows the date rather than a bogus age when the payload has no timestamp', () => {
    const line = describeLastFetched({ lastSuccessAt: FETCHED_AT }, 0);
    expect(line.label).toBe(`Last fetched ${new Date(FETCHED_AT).toLocaleDateString()}`);
    expect(line.label).not.toMatch(/just now|ago/);
  });
});

// ── discovery checklist helpers (E7 capture pivot) ─────────────────────────

function step(
  key: DiscoveryStepKey,
  status: DiscoveryStep['status'],
  result: string | null = null
): DiscoveryStep {
  return { key, status, result };
}

function progress(overrides: Partial<DiscoveryProgress> = {}): DiscoveryProgress {
  return {
    steps: [
      step('open_page', 'pending'),
      step('find_feed', 'pending'),
      step('verify_read', 'pending'),
      step('ready', 'pending'),
    ],
    outcome: 'running',
    liveViewUrl: null,
    updatedAt: null,
    ...overrides,
  };
}

describe('describeDiscoveryStep', () => {
  it('labels every step in the closed union', () => {
    const keys: DiscoveryStepKey[] = [
      'open_page',
      'find_feed',
      'verify_read',
      'ready',
      'first_scan',
    ];
    for (const key of keys) {
      expect(describeDiscoveryStep({ key })).toBe(DISCOVERY_STEP_LABELS[key]);
      expect(describeDiscoveryStep({ key })).not.toBe('');
    }
  });

  it("names the four rungs in the words a person uses, not the engine's", () => {
    // The KEYS are the backend contract and must not move; the LABELS are ours. The
    // previous set ("Finding the jobs feed", "Verifying we can read it") described our
    // pipeline — this set describes what the user gets out of each step.
    expect(DISCOVERY_STEP_LABELS.open_page).toBe('Opening the page');
    expect(DISCOVERY_STEP_LABELS.find_feed).toBe('Reading jobs');
    expect(DISCOVERY_STEP_LABELS.verify_read).toBe('Building web scraper');
    expect(DISCOVERY_STEP_LABELS.ready).toBe('Ready to track');
    // "Fetching all current jobs", not "Reading the board": this rung IS the first
    // harvest, and the word "all" is what a partial board cannot honestly tick — which
    // is the whole reason the ◐ on it means something.
    expect(DISCOVERY_STEP_LABELS.first_scan).toBe('Fetching all current jobs');
  });

  it('falls back to the raw key rather than an empty rung', () => {
    // The union is closed and the backend normalizes unknown keys away, but the value
    // still arrives as wire data — a blank row in a checklist someone is reading to
    // decide what to do next is the worst possible failure mode.
    expect(describeDiscoveryStep({ key: 'some_future_step' as DiscoveryStepKey })).toBe(
      'some_future_step'
    );
  });
});

describe('resolveDiscoveryOutcome', () => {
  it('reads a refused row as refused even when its blob still says "running"', () => {
    // The discovery TIMEOUT: no terminal checklist was written, so the last live
    // snapshot survives beside health_state='refused'. health_state wins.
    expect(resolveDiscoveryOutcome({ healthState: 'refused', discovery: progress() })).toBe(
      'refused'
    );
  });

  it('reads a discovering row as running whatever the blob says', () => {
    expect(
      resolveDiscoveryOutcome({
        healthState: 'discovering',
        discovery: progress({ outcome: 'tracking' }),
      })
    ).toBe('running');
  });

  it('otherwise trusts the blob, defaulting to running when there is none', () => {
    expect(
      resolveDiscoveryOutcome({
        healthState: 'unverified',
        discovery: progress({ outcome: 'tracking' }),
      })
    ).toBe('tracking');
    expect(resolveDiscoveryOutcome({ healthState: 'healthy', discovery: null })).toBe('running');
  });
});

describe('describeDiscoveryOutcome', () => {
  const refused = progress({
    outcome: 'refused',
    steps: [
      step('open_page', 'done', 'opened acme.example — recorded 4 JSON request(s)'),
      step('find_feed', 'done', 'found 3 candidate feed(s)'),
      step('verify_read', 'failed', 'the replay returned a different list'),
      step('ready', 'pending'),
    ],
  });

  it('frames a refusal around the company, in one line and no more', () => {
    // It used to return a title AND a "Opening the careers page ✓ · Finding the jobs
    // feed ✕" chain of the same four steps rendered directly underneath it. One fact,
    // stated once: the heading is the verdict, the rungs below show how far we got.
    expect(
      describeDiscoveryOutcome({
        displayName: 'Acme',
        healthState: 'refused',
        discovery: refused,
      })
    ).toBe("We couldn't read Acme's board");
  });

  it('frames success and in-progress distinctly', () => {
    expect(
      describeDiscoveryOutcome({
        displayName: 'Acme',
        healthState: 'unverified',
        discovery: progress({ outcome: 'tracking' }),
      })
    ).toBe("We can read Acme's board");
    expect(
      describeDiscoveryOutcome({
        displayName: 'Acme',
        healthState: 'discovering',
        discovery: progress(),
      })
    ).toBe('Setting up Acme');
  });
});

describe('failedDiscoveryStep', () => {
  it('finds the one step a refusal stopped on', () => {
    const found = failedDiscoveryStep(
      progress({ steps: [step('open_page', 'done'), step('find_feed', 'failed', 'nope')] })
    );
    expect(found?.key).toBe('find_feed');
  });

  it('returns null when nothing failed — a timeout fails no step', () => {
    expect(failedDiscoveryStep(progress())).toBeNull();
    expect(failedDiscoveryStep(null)).toBeNull();
  });
});

// ── the row's chip, and the rule it now obeys ──────────────────────────────
//
// ONE RULE ACROSS ALL OF IT: an alarm colour is for a state the reader can do
// something about. Amber says "this needs you"; on a board whose own API refuses to
// hand over more (Amazon hard-refuses `offset + limit > 10000`) there is no button, no
// URL to change, nothing — and the amber chip sat directly above five green ticks, so
// the row read as a malfunction rather than a fact. The shortfall is real and still
// shown; it just stops shouting.

const HARVESTED = '2026-08-22T00:00:00Z';

/** A settled partial board: discovery said `partial` and the first harvest has landed. */
const settledPartial = (openJobCount = 1_000) => ({
  healthState: 'unverified',
  lastSuccessAt: HARVESTED,
  openJobCount,
  discovery: progress({
    outcome: 'partial' as const,
    steps: [
      step('open_page', 'done'),
      step('find_feed', 'done'),
      step(
        'verify_read',
        'done',
        "read 20 job(s), but this board's own response counts 22,500 job(s) — we can " +
          'only track part of this board'
      ),
      step('ready', 'done'),
      step('first_scan', 'done', 'read 1,000 job(s) from the board'),
    ],
  }),
});

describe('describeCompanyHealth — a partial board must not look like a whole one', () => {
  // The bug this pins, measured on three live boards: Binance tracked one department
  // of fourteen, Kakao the tab its own page opened by itself, Walmart ten jobs of
  // forty-seven thousand — and all three showed the same green "Successfully tracking"
  // chip as a board we had read completely. Nothing was broken; the label was a lie.
  it('says WHAT is partial — in the SUCCESS colour, hollow, never amber', () => {
    const badge = describeCompanyHealth(settledPartial());
    expect(badge.label).toBe('Tracking part of this board');
    // Not `warning`. Amber is this app's "Tracking paused" colour — it promises the
    // reader something to look at, and there is nothing: the cap is the board's own.
    expect(badge.color).toBe('success');
    expect(badge.variant).toBe('outlined');
  });

  it('still separates a partial board from a whole one at a glance', () => {
    // The other half of the fix. Making it calm must not make it invisible: same hue,
    // different weight, different words. Solid green vs hollow green.
    const whole = describeCompanyHealth({
      healthState: 'unverified',
      lastSuccessAt: HARVESTED,
      discovery: progress({ outcome: 'tracking' }),
    });
    const part = describeCompanyHealth(settledPartial());
    expect(whole.label).not.toBe(part.label);
    expect(whole.variant ?? 'filled').toBe('filled');
    expect(part.variant).toBe('outlined');
  });

  it('keeps saying it after the board graduates to healthy', () => {
    // Coverage is a property of the RECIPE, decided once at discovery. Graduating to
    // `healthy` means we grew an oracle for the slice we read — it does not widen it.
    expect(describeCompanyHealth({ ...settledPartial(), healthState: 'healthy' })).toEqual(
      describeCompanyHealth(settledPartial())
    );
  });

  it('leaves every other row exactly as it was', () => {
    // A board read whole, a board with no discovery blob at all (every ATS company),
    // and the two states that are genuinely about health must be byte-identical to
    // what shipped — this wrapper may only ever ADD the one thing healthState cannot say.
    for (const outcome of ['tracking', 'running'] as const) {
      expect(
        describeCompanyHealth({
          healthState: 'unverified',
          lastSuccessAt: HARVESTED,
          discovery: progress({ outcome }),
        })
      ).toEqual(describeHealthState('unverified'));
    }
    expect(
      describeCompanyHealth({
        healthState: 'unverified',
        lastSuccessAt: HARVESTED,
        discovery: null,
      })
    ).toEqual(describeHealthState('unverified'));
    for (const state of ['discovering', 'quarantined', 'refused'] as const) {
      expect(
        describeCompanyHealth({
          healthState: state,
          lastSuccessAt: HARVESTED,
          discovery: progress({ outcome: 'partial' }),
        })
      ).toEqual(describeHealthState(state));
    }
  });
});

describe('a row mid-fetch must not claim how much of the board it got', () => {
  // THE MISREAD, OBSERVED LIVE. A row showed a settled chip, a job count, and a fifth
  // rung still spinning; the reader took the chip as the verdict on a fetch that had
  // not finished. The verdict is decided at DISCOVERY time and the harvest runs after
  // it, so `outcome: 'partial'` genuinely exists over a count that is still climbing.
  const fetching = (scan: DiscoveryStep['status'], result: string | null = null) => ({
    healthState: 'unverified',
    lastSuccessAt: null,
    discovery: progress({
      outcome: 'partial' as const,
      steps: [
        step('open_page', 'done'),
        step('find_feed', 'done'),
        step('verify_read', 'done'),
        step('ready', 'done'),
        step('first_scan', scan, result),
      ],
    }),
  });

  it('says it is still fetching, and says nothing about partiality', () => {
    const badge = describeCompanyHealth(fetching('active'));
    expect(badge.label).toBe('Fetching all current jobs…');
    expect(badge.color).toBe('info');
    // The claim the row is not entitled to make yet.
    expect(badge.label).not.toMatch(/part of this board/i);
  });

  it('makes the claim the moment the harvest lands', () => {
    expect(describeCompanyHealth(settledPartial()).label).toBe('Tracking part of this board');
  });

  it('never says "Successfully tracking" over a board it has not scraped yet', () => {
    // Applies to an ATS row too — Workday/Greenhouse have no checklist at all, and
    // since `853457f` their first scan is ~20s rather than ~15min, but a green
    // "Successfully tracking" over "0 open jobs" is a lie for as long as it lasts.
    const badge = describeCompanyHealth({
      healthState: 'unverified',
      lastSuccessAt: null,
      discovery: null,
    });
    expect(badge.label).toBe('Fetching all current jobs…');
    expect(badge.color).toBe('info');
  });

  it('stops claiming to be running once we know the scan FAILED — and stays calm', () => {
    // The chip that would otherwise rot: `!lastSuccessAt` never expires, so a board
    // failing every night would look like it started a moment ago, forever. Where the
    // checklist gives us the fact, say it — in blue, because the scheduler retries
    // tonight and there is nothing for the reader to do in between.
    const badge = describeCompanyHealth(
      fetching('failed', 'we could not read the board on this run — we will try again')
    );
    expect(badge.label).toBe("Couldn't fetch yet — retrying");
    expect(badge.color).toBe('info');
    expect(badge.color).not.toBe('error');
  });

  it('reads the rung, not the clock', () => {
    expect(isFirstScanInFlight(fetching('active'))).toBe(true);
    expect(isFirstScanInFlight(fetching('failed'))).toBe(true);
    expect(isFirstScanInFlight(settledPartial())).toBe(false);
    // A blob written before this rung existed comes back `pending`. Treating that as
    // in-flight would strand every legacy row on "Fetching…" for good.
    expect(isFirstScanInFlight(fetching('pending'))).toBe(false);
    expect(isFirstScanInFlight({ discovery: null })).toBe(false);
  });

  it('narrates in the heading instead of concluding, while the scan runs', () => {
    expect(describeDiscoveryOutcome({ displayName: 'Amazon', ...fetching('active') })).toBe(
      "Fetching Amazon's jobs"
    );
  });
});

describe('describePartialScope — the board’s own numbers, under the last rung', () => {
  it('states the board’s claim and what we reach, from the middle clause only', () => {
    // The backend writes `read {N} job(s), but {claim} — we can only track part of this
    // board` onto `verify_read`. The leading N is the ACCEPTANCE PROBE's count (two
    // pages, 20 for Microsoft) on a row whose chip says "1,000 open jobs" — rendering it
    // would answer one confusion with a worse one. The trailing clause is what the
    // heading one line above already says.
    expect(describePartialScope(settledPartial())).toBe(
      "This board's own response counts 22,500 job(s); we can reach 1,000."
    );
  });

  it('drops the reach clause when there is nothing to reach yet', () => {
    expect(describePartialScope(settledPartial(0))).toBe(
      "This board's own response counts 22,500 job(s)."
    );
  });

  it('returns null rather than a wrong sentence when it cannot parse one', () => {
    // A missing sentence is recoverable; an invented one is not. The rung keeps its ◐
    // and simply carries no caption.
    expect(
      describePartialScope({
        openJobCount: 5,
        discovery: progress({
          outcome: 'partial',
          steps: [step('verify_read', 'done', 'read 20 job(s)')],
        }),
      })
    ).toBeNull();
    expect(describePartialScope({ openJobCount: 5, discovery: null })).toBeNull();
  });

  it('handles the other evidence templates the backend can emit', () => {
    // Three templates today ("…response counts N", "…facets agree on N", "…category
    // counts add up to N") and a fourth is free: this splits on the separators, never
    // on the numbers.
    expect(
      describePartialScope({
        openJobCount: 10,
        discovery: progress({
          outcome: 'partial',
          steps: [
            step(
              'verify_read',
              'done',
              "read 10 job(s), but this board's own category counts add up to 47,000 — " +
                'we can only track part of this board'
            ),
          ],
        }),
      })
    ).toBe("This board's own category counts add up to 47,000; we can reach 10.");
  });
});

describe('the discovery evidence, and when it is reachable', () => {
  it('names the shortfall in the heading', () => {
    expect(
      describeDiscoveryOutcome({
        displayName: 'Walmart',
        healthState: 'unverified',
        discovery: progress({ outcome: 'partial' }),
      })
    ).toBe("We can only read part of Walmart's board");
  });

  it('keeps the evidence on EVERY tracked row, not just the partial ones', () => {
    // The rule changed. It used to vanish the moment `lastSuccessAt` was set, because a
    // permanent setup receipt is clutter — true of a panel that is always expanded, and
    // this one is now a collapsed accordion once a row settles. The owner assumed the
    // evidence was deleted on reload; it never was (5 KB in `provider_config`), but a
    // panel that disappears is indistinguishable from data that was thrown away.
    const partial = progress({ outcome: 'partial' });
    const whole = progress({ outcome: 'tracking' });
    for (const state of ['unverified', 'healthy'] as const) {
      for (const discovery of [partial, whole]) {
        expect(
          shouldShowDiscovery({ healthState: state, discovery, lastSuccessAt: HARVESTED })
        ).toBe(true);
      }
    }
    expect(
      shouldShowDiscovery({ healthState: 'discovering', discovery: whole, lastSuccessAt: null })
    ).toBe(true);
    expect(
      shouldShowDiscovery({ healthState: 'refused', discovery: whole, lastSuccessAt: null })
    ).toBe(true);
  });

  it('still hides it on a quarantined row, and on a state we do not know', () => {
    // A quarantined row is one the backend marked broken; a "We can read X's board"
    // receipt under a "Tracking paused" badge is the UI contradicting the badge beside
    // it. An unknown/newer state gets the same caution — we cannot know whether the
    // receipt is a lie there.
    const partial = progress({ outcome: 'partial' });
    expect(
      shouldShowDiscovery({ healthState: 'quarantined', discovery: partial, lastSuccessAt: null })
    ).toBe(false);
    expect(
      shouldShowDiscovery({
        healthState: 'some_future_state',
        discovery: partial,
        lastSuccessAt: null,
      })
    ).toBe(false);
    // ...and nothing to show is still nothing to show.
    expect(
      shouldShowDiscovery({ healthState: 'unverified', discovery: null, lastSuccessAt: null })
    ).toBe(false);
  });

  it('opens while something is happening or went wrong, and folds once settled', () => {
    // ONE rule: `lastSuccessAt`, plus refusals. A settled row is one collapsed line; a
    // running one shows its rungs ticking and its requests arriving, which IS the
    // feature — a one-time setup that happens inside a closed box is the spinner it
    // replaced.
    expect(
      shouldExpandDiscovery({
        healthState: 'discovering',
        discovery: progress(),
        lastSuccessAt: null,
      })
    ).toBe(true);
    expect(
      shouldExpandDiscovery({
        healthState: 'refused',
        discovery: progress({ outcome: 'refused' }),
        lastSuccessAt: null,
      })
    ).toBe(true);
    // Accepted, first harvest not landed — `first_scan` is still spinning.
    expect(
      shouldExpandDiscovery({
        healthState: 'unverified',
        discovery: progress({ outcome: 'tracking' }),
        lastSuccessAt: null,
      })
    ).toBe(true);
    // Settled. Both a whole board AND a partial one: the partial verdict is permanent
    // and unactionable, so it does not earn a permanently open panel either.
    for (const outcome of ['tracking', 'partial'] as const) {
      expect(
        shouldExpandDiscovery({
          healthState: 'unverified',
          discovery: progress({ outcome }),
          lastSuccessAt: HARVESTED,
        })
      ).toBe(false);
    }
    // A refusal stays open even though it can never harvest — the verdict and the one
    // action that changes it must not need a click to find.
    expect(
      shouldExpandDiscovery({
        healthState: 'refused',
        discovery: progress({ outcome: 'refused' }),
        lastSuccessAt: HARVESTED,
      })
    ).toBe(true);
  });

  it('reads the outcome off the blob', () => {
    expect(
      resolveDiscoveryOutcome({
        healthState: 'unverified',
        discovery: progress({ outcome: 'partial' }),
      })
    ).toBe('partial');
    // ...but `refused` on the row still wins: a discovery timeout leaves a stale blob.
    expect(
      resolveDiscoveryOutcome({
        healthState: 'refused',
        discovery: progress({ outcome: 'partial' }),
      })
    ).toBe('refused');
  });
});

describe('sourceBoardUrl — the board a tracked row was built from', () => {
  it('uses the server’s url whenever the payload carries one', () => {
    // The answer is the SERVER's now (`api/services/board_url.py`), because that is the
    // only place `provider_config` exists — see the Workday case below.
    expect(
      sourceBoardUrl({
        ats: 'greenhouse',
        boardToken: 'duolingo',
        boardUrl: 'https://job-boards.greenhouse.io/duolingo',
      })
    ).toBe('https://job-boards.greenhouse.io/duolingo');
  });

  it('gives Workday and Eightfold the link they could never have here', () => {
    // THE REPORTED BUG: their `boardToken` is a cosmetic tenant label naming no host, so
    // these two rows rendered nothing — and "Cisco", typed as a NAME, is a Workday board.
    // The host lives in `provider_config`, which this payload has never carried, so the
    // fix could only ever be the server sending the assembled url.
    expect(
      sourceBoardUrl({
        ats: 'workday',
        boardToken: 'cisco',
        boardUrl: 'https://cisco.wd5.myworkdayjobs.com/Cisco_Careers',
      })
    ).toBe('https://cisco.wd5.myworkdayjobs.com/Cisco_Careers');
    expect(
      sourceBoardUrl({
        ats: 'eightfold',
        boardToken: 'netflix',
        boardUrl: 'https://explore.jobs.netflix.net/careers?domain=netflix.com',
      })
    ).toBe('https://explore.jobs.netflix.net/careers?domain=netflix.com');
  });

  it('treats a null boardUrl as the server’s answer, and does NOT fall back to a guess', () => {
    // `null` and absent are different things and collapsing them would undo half of this.
    // `null` is the server saying it looked at the row and could not name an honest
    // destination; deriving one here would be this file overruling the only code that can
    // see the config.
    expect(
      sourceBoardUrl({ ats: 'greenhouse', boardToken: 'duolingo', boardUrl: null })
    ).toBeNull();
    expect(sourceBoardUrl({ ats: 'workday', boardToken: 'blueorigin', boardUrl: null })).toBeNull();
    // Whitespace-only is the same nothing.
    expect(
      sourceBoardUrl({ ats: 'greenhouse', boardToken: 'duolingo', boardUrl: '   ' })
    ).toBeNull();
  });

  it('never puts a non-http server url in an href either', () => {
    // "The server sent it" is not the property that makes a string safe in an `href`, and
    // the check costs nothing.
    expect(
      sourceBoardUrl({ ats: 'discovered', boardToken: 'x', boardUrl: 'javascript:alert(1)' })
    ).toBeNull();
    expect(
      sourceBoardUrl({ ats: 'greenhouse', boardToken: 'x', boardUrl: 'job-boards.greenhouse.io/x' })
    ).toBeNull();
  });

  it('uses a discovered board’s pasted URL verbatim', () => {
    // `board_token` IS the normalized URL for a discovered board
    // (`custom_companies_service.py` stores `board_token=normalized_url`), and this is
    // the case the whole feature was asked for: the Jane Street page we read to build
    // the scraper was nowhere on screen.
    expect(
      sourceBoardUrl({
        ats: 'discovered',
        boardToken: 'https://www.janestreet.com/join-jane-street/open-roles/',
      })
    ).toBe('https://www.janestreet.com/join-jane-street/open-roles/');
  });

  it('builds the public board for the four ATS providers whose token IS the slug', () => {
    // All of these run the LEGACY fallback: no `boardUrl` key at all, which is what a
    // server that predates the field sends. The frontend and backend deploy separately,
    // so every link that works today has to survive a Vercel deploy landing first.
    expect(sourceBoardUrl({ ats: 'greenhouse', boardToken: 'spacex' })).toBe(
      'https://job-boards.greenhouse.io/spacex'
    );
    expect(sourceBoardUrl({ ats: 'ashby', boardToken: 'sierra' })).toBe(
      'https://jobs.ashbyhq.com/sierra'
    );
    expect(sourceBoardUrl({ ats: 'lever', boardToken: 'zoox' })).toBe('https://jobs.lever.co/zoox');
    expect(sourceBoardUrl({ ats: 'gem', boardToken: 'nominal' })).toBe(
      'https://jobs.gem.com/nominal'
    );
  });

  it('refuses to GUESS a Workday or Eightfold board on a payload with no boardUrl', () => {
    // Their `board_token` is a cosmetic tenant label; the real board lives at a host the
    // token does not spell (`<tenant>.wd5.myworkdayjobs.com/<career_site>`,
    // `explore.jobs.netflix.net/careers?domain=…`), and that host is in `provider_config`
    // which this payload does not carry. A confident link to a 404 is worse than no link
    // — the row is missing information either way, and one of the two lies about it.
    //
    // The server now sends the real url, so these two rows DO get a link in practice
    // (above). What this pins is that the fallback never learns to fake one: the only
    // version of these it could ever build here is a guess.
    expect(sourceBoardUrl({ ats: 'workday', boardToken: 'blueorigin' })).toBeNull();
    expect(sourceBoardUrl({ ats: 'eightfold', boardToken: 'netflix' })).toBeNull();
  });

  it('never builds an href out of something that is not http(s)', () => {
    // `boardToken` is server data, but it ORIGINATES in a URL a stranger pasted, and an
    // `href` is the one place that distinction matters.
    expect(sourceBoardUrl({ ats: 'discovered', boardToken: 'javascript:alert(1)' })).toBeNull();
    expect(sourceBoardUrl({ ats: 'discovered', boardToken: 'careers.acme.example' })).toBeNull();
    expect(sourceBoardUrl({ ats: 'discovered', boardToken: '' })).toBeNull();
    expect(sourceBoardUrl({ ats: 'greenhouse', boardToken: '   ' })).toBeNull();
    // ...and an ATS we have never heard of gets nothing rather than a guessed host.
    expect(sourceBoardUrl({ ats: 'brand_new_ats', boardToken: 'acme' })).toBeNull();
  });
});

describe('sourceBoardLabel — what the link says', () => {
  it('is the host, without www., so the row answers the question without a click', () => {
    expect(sourceBoardLabel('https://www.janestreet.com/join-jane-street/open-roles/')).toBe(
      'janestreet.com'
    );
    expect(sourceBoardLabel('https://job-boards.greenhouse.io/spacex')).toBe(
      'job-boards.greenhouse.io'
    );
  });

  it('is null on anything that will not parse, so a label cannot outlive its href', () => {
    expect(sourceBoardLabel('not a url')).toBeNull();
  });
});
