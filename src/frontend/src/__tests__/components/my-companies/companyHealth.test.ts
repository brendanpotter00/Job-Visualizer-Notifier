import { describe, it, expect } from 'vitest';
import {
  DISCOVERY_STEP_LABELS,
  describeCompanyHealth,
  describeDiscoveryOutcome,
  describeDiscoveryStep,
  describeHealthState,
  describeLastChecked,
  failedDiscoveryStep,
  resolveDiscoveryOutcome,
  shouldShowDiscovery,
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

describe('describeLastChecked', () => {
  it('says "Not yet checked" before the first harvest (null)', () => {
    expect(describeLastChecked({ lastSuccessAt: null })).toBe('Not yet checked');
  });

  it('treats an unparseable timestamp as never-checked rather than "Invalid Date"', () => {
    expect(describeLastChecked({ lastSuccessAt: 'not-a-date' })).toBe('Not yet checked');
  });

  it('renders a "Last checked …" line for a real timestamp', () => {
    expect(describeLastChecked({ lastSuccessAt: '2026-08-09T10:00:00Z' })).toMatch(
      /^Last checked /
    );
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
    const keys: DiscoveryStepKey[] = ['open_page', 'find_feed', 'verify_read', 'ready'];
    for (const key of keys) {
      expect(describeDiscoveryStep({ key })).toBe(DISCOVERY_STEP_LABELS[key]);
      expect(describeDiscoveryStep({ key })).not.toBe('');
    }
  });

  it('names the four rungs in the words a person uses, not the engine\'s', () => {
    // The KEYS are the backend contract and must not move; the LABELS are ours. The
    // previous set ("Finding the jobs feed", "Verifying we can read it") described our
    // pipeline — this set describes what the user gets out of each step.
    expect(DISCOVERY_STEP_LABELS.open_page).toBe('Opening the page');
    expect(DISCOVERY_STEP_LABELS.find_feed).toBe('Reading jobs');
    expect(DISCOVERY_STEP_LABELS.verify_read).toBe('Building web scraper');
    expect(DISCOVERY_STEP_LABELS.ready).toBe('Ready to track');
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
    expect(
      resolveDiscoveryOutcome({ healthState: 'refused', discovery: progress() })
    ).toBe('refused');
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
    expect(resolveDiscoveryOutcome({ healthState: 'healthy', discovery: null })).toBe(
      'running'
    );
  });
});

describe('shouldShowDiscovery', () => {
  const tracking = progress({ outcome: 'tracking' });

  it('shows the checklist while a board is being set up, and after a refusal', () => {
    expect(
      shouldShowDiscovery({
        healthState: 'discovering',
        discovery: progress(),
        lastSuccessAt: null,
      })
    ).toBe(true);
    expect(
      shouldShowDiscovery({ healthState: 'refused', discovery: progress(), lastSuccessAt: null })
    ).toBe(true);
  });

  it('keeps the success summary only until the first harvest lands', () => {
    // After that the row is an ordinary tracked company and a permanent setup receipt
    // is clutter — which also means nothing has to sweep the blob away server-side.
    expect(
      shouldShowDiscovery({
        healthState: 'unverified',
        discovery: tracking,
        lastSuccessAt: null,
      })
    ).toBe(true);
    expect(
      shouldShowDiscovery({
        healthState: 'unverified',
        discovery: tracking,
        lastSuccessAt: '2026-08-09T10:00:00Z',
      })
    ).toBe(false);
  });

  it('does not resurrect the receipt when a harvested board drops to zero open jobs', () => {
    // The bug an open-job count stands in for "no harvest yet": a board that genuinely
    // has no roles today would render a green "We can read X's board" over a "0 open
    // jobs" chip, linking to postings the harvest just proved gone. `lastSuccessAt` is
    // the real signal, and it does not go back to null.
    expect(
      shouldShowDiscovery({
        healthState: 'unverified',
        discovery: tracking,
        lastSuccessAt: '2026-06-01T00:00:00Z',
      })
    ).toBe(false);
  });

  it('never shows a success receipt on a row the backend has marked broken', () => {
    // "We can read Acme's board" directly under "Paused — needs a look" is the UI
    // contradicting the badge beside it. Same for a graduated (healthy) row.
    expect(
      shouldShowDiscovery({
        healthState: 'quarantined',
        discovery: tracking,
        lastSuccessAt: null,
      })
    ).toBe(false);
    expect(
      shouldShowDiscovery({ healthState: 'healthy', discovery: tracking, lastSuccessAt: null })
    ).toBe(false);
  });

  it('never shows anything for a company with no checklist (every ATS board)', () => {
    expect(
      shouldShowDiscovery({ healthState: 'discovering', discovery: null, lastSuccessAt: null })
    ).toBe(false);
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

describe('describeCompanyHealth — a partial board must not look like a whole one', () => {
  // The bug this pins, measured on three live boards: Binance tracked one department
  // of fourteen, Kakao the tab its own page opened by itself, Walmart ten jobs of
  // forty-seven thousand — and all three showed the same green "Successfully tracking"
  // chip as a board we had read completely. Nothing was broken; the label was a lie.
  it('says WHAT is partial, in amber, when discovery only reached part of the board', () => {
    const badge = describeCompanyHealth({
      healthState: 'unverified',
      discovery: progress({ outcome: 'partial' }),
    });
    expect(badge.label).toBe('Tracking part of this board');
    expect(badge.color).toBe('warning');
  });

  it('keeps saying it after the board graduates to healthy', () => {
    // Coverage is a property of the RECIPE, decided once at discovery. Graduating to
    // `healthy` means we grew an oracle for the slice we read — it does not widen it.
    expect(
      describeCompanyHealth({ healthState: 'healthy', discovery: progress({ outcome: 'partial' }) })
    ).toEqual(
      describeCompanyHealth({
        healthState: 'unverified',
        discovery: progress({ outcome: 'partial' }),
      })
    );
  });

  it('leaves every other row exactly as it was', () => {
    // A board read whole, a board with no discovery blob at all (every ATS company),
    // and the two states that are genuinely about health must be byte-identical to
    // what shipped — this wrapper may only ever ADD the one thing healthState cannot say.
    for (const outcome of ['tracking', 'running'] as const) {
      expect(
        describeCompanyHealth({ healthState: 'unverified', discovery: progress({ outcome }) })
      ).toEqual(describeHealthState('unverified'));
    }
    expect(describeCompanyHealth({ healthState: 'unverified', discovery: null })).toEqual(
      describeHealthState('unverified')
    );
    for (const state of ['discovering', 'quarantined', 'refused'] as const) {
      expect(
        describeCompanyHealth({ healthState: state, discovery: progress({ outcome: 'partial' }) })
      ).toEqual(describeHealthState(state));
    }
  });
});

describe('a partial discovery keeps its evidence on screen', () => {
  it('names the shortfall in the heading', () => {
    expect(
      describeDiscoveryOutcome({
        displayName: 'Walmart',
        healthState: 'unverified',
        discovery: progress({ outcome: 'partial' }),
      })
    ).toBe("We can only read part of Walmart's board");
  });

  it('keeps the checklist visible for good, unlike a setup receipt', () => {
    // Every other tracked row drops its checklist once the first harvest lands, because
    // a permanent setup receipt is clutter. A partial row is the exception: the amber
    // chip makes a claim, and the rungs below it are the only place the board's own
    // numbers ("read 8 jobs, but its category counts add up to 31") are written down.
    const partial = progress({ outcome: 'partial' });
    expect(
      shouldShowDiscovery({
        healthState: 'unverified',
        discovery: partial,
        lastSuccessAt: '2026-08-22T00:00:00Z',
      })
    ).toBe(true);
    expect(
      shouldShowDiscovery({
        healthState: 'healthy',
        discovery: partial,
        lastSuccessAt: '2026-08-22T00:00:00Z',
      })
    ).toBe(true);
    // ...and a board read whole still loses it, exactly as before.
    expect(
      shouldShowDiscovery({
        healthState: 'unverified',
        discovery: progress({ outcome: 'tracking' }),
        lastSuccessAt: '2026-08-22T00:00:00Z',
      })
    ).toBe(false);
    // A quarantined row is one the backend marked broken; a success receipt under a
    // "Tracking paused" badge would be the UI contradicting the badge beside it.
    expect(
      shouldShowDiscovery({ healthState: 'quarantined', discovery: partial, lastSuccessAt: null })
    ).toBe(false);
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
