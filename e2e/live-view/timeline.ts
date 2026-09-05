// The instruments. Nothing in here knows about a scenario — it knows how to WATCH the
// live view in a real browser and how to say, afterwards, exactly what happened to it.
//
// Three things are measured, and the third is the one that matters:
//
//  1. the component's own narration — `[live-view] …` console lines, which carry
//     `which=` and therefore name the closer;
//  2. the iframe's presence in the DOM, sampled on a timer, because "was it on screen"
//     is a question about every instant and not about the two we happen to assert on;
//  3. the GAPS in (2), cross-referenced against (1), so a failure reads
//     "gone for 27.4s from t=3120ms — closer `postMessage` fired at t=3106ms"
//     rather than "expected visible to be true".

import type { Page } from '@playwright/test';

/** The window switch `liveViewDebug.ts` reads. Set before any page script runs. */
const DEBUG_FLAG = '__JVN_LIVE_VIEW_DEBUG__';
/** Where the DOM sampler parks its readings. */
const SAMPLES_KEY = '__JVN_LIVE_VIEW_SAMPLES__';
/** The iframe itself — not its wrapper, which stays mounted through the exit. */
export const FRAME_TESTID = 'discovery-live-view';
/** How often presence is sampled. 50ms is far finer than anything React does here. */
const SAMPLE_INTERVAL_MS = 50;

export interface LogLine {
  /** ms since the page started, from Playwright's clock, not the page's. */
  at: number;
  /** The raw line, minus the `[live-view] ` prefix. */
  text: string;
  /** `url-arrived`, `frame-load`, `closer-fired`, `lease-rearmed`, `phase`. */
  event: string;
  /** Parsed `k=v` fields. */
  fields: Record<string, string>;
}

export interface Sample {
  at: number;
  present: boolean;
}

export interface Gap {
  from: number;
  to: number | null;
  durationMs: number;
}

/**
 * Arm a page for observation. MUST run before `page.goto` — both halves are
 * `addInitScript`, which is the only hook that beats the app's own first render.
 */
export async function instrument(page: Page): Promise<Recorder> {
  const lines: LogLine[] = [];
  const started = Date.now();

  page.on('console', (msg) => {
    const text = msg.text();
    if (!text.startsWith('[live-view] ')) return;
    const body = text.slice('[live-view] '.length);
    const [event, ...rest] = body.split(' ');
    const fields: Record<string, string> = {};
    for (const token of rest) {
      const eq = token.indexOf('=');
      if (eq > 0) fields[token.slice(0, eq)] = token.slice(eq + 1);
    }
    lines.push({ at: Date.now() - started, text: body, event, fields });
  });

  await page.addInitScript(
    ({ flag, samplesKey, testid, intervalMs }) => {
      (window as unknown as Record<string, unknown>)[flag] = true;
      const samples: [number, number][] = [];
      (window as unknown as Record<string, unknown>)[samplesKey] = samples;
      const sample = () => {
        const found = document.querySelector(`[data-testid="${testid}"]`) !== null;
        samples.push([Math.round(performance.now()), found ? 1 : 0]);
      };
      sample();
      setInterval(sample, intervalMs);
    },
    {
      flag: DEBUG_FLAG,
      samplesKey: SAMPLES_KEY,
      testid: FRAME_TESTID,
      intervalMs: SAMPLE_INTERVAL_MS,
    }
  );

  return new Recorder(page, lines, started);
}

export class Recorder {
  constructor(
    private readonly page: Page,
    readonly lines: LogLine[],
    private readonly started: number
  ) {}

  /** ms since `instrument()` was called, on the test runner's clock. */
  now(): number {
    return Date.now() - this.started;
  }

  async samples(): Promise<Sample[]> {
    const raw = await this.page.evaluate((key) => {
      return ((window as unknown as Record<string, unknown>)[key] as [number, number][]) ?? [];
    }, SAMPLES_KEY);
    return raw.map(([at, present]) => ({ at, present: present === 1 }));
  }

  /** Every `closer-fired` line, in order. */
  closers(): LogLine[] {
    return this.lines.filter((l) => l.event === 'closer-fired');
  }

  /** The closer nearest to (and at or before) `at`, which is the one that caused a gap. */
  closerNear(at: number, windowMs = 2_500): LogLine | null {
    let best: LogLine | null = null;
    for (const line of this.closers()) {
      if (line.at <= at + 250 && at - line.at <= windowMs) {
        if (best === null || line.at > best.at) best = line;
      }
    }
    return best;
  }

  /** A human-readable dump. Printed on every failure, and on request. */
  report(samples: Sample[]): string {
    const out: string[] = [];
    out.push('--- [live-view] narration -------------------------------------------');
    for (const line of this.lines) {
      out.push(`  ${String(line.at).padStart(6)}ms  ${line.text}`);
    }
    out.push('--- iframe presence -------------------------------------------------');
    let last: boolean | null = null;
    for (const s of samples) {
      if (s.present !== last) {
        out.push(`  ${String(s.at).padStart(6)}ms  ${s.present ? 'PRESENT' : 'ABSENT'}`);
        last = s.present;
      }
    }
    return out.join('\n');
  }
}

/**
 * Gaps in presence AFTER the frame first appeared and BEFORE `until`.
 *
 * `until` is the moment the session is allowed to end — the payload that retracts the
 * URL. Anything absent before that is a frame taken away while its browser was still
 * open, which is the whole bug.
 *
 * A gap shorter than `graceMs` is still a gap and still reported; the caller decides.
 * There is deliberately no built-in tolerance: a frame that blinks is the symptom.
 */
export function gapsBeforeEnd(samples: Sample[], until: number): Gap[] {
  const firstPresent = samples.find((s) => s.present);
  if (!firstPresent) return [];
  const gaps: Gap[] = [];
  let openedAt: number | null = null;
  for (const s of samples) {
    if (s.at < firstPresent.at || s.at > until) continue;
    if (!s.present && openedAt === null) openedAt = s.at;
    if (s.present && openedAt !== null) {
      gaps.push({ from: openedAt, to: s.at, durationMs: s.at - openedAt });
      openedAt = null;
    }
  }
  if (openedAt !== null) {
    gaps.push({ from: openedAt, to: null, durationMs: until - openedAt });
  }
  return gaps;
}

/** Did the frame ever appear at all? A run where it never mounted proves nothing. */
export function everPresent(samples: Sample[]): boolean {
  return samples.some((s) => s.present);
}

/** Was it gone by `at`, and did it stay gone? The "don't linger" half. */
export function absentFrom(samples: Sample[], at: number): boolean {
  const after = samples.filter((s) => s.at >= at);
  return after.length > 0 && after.every((s) => !s.present);
}

/**
 * Every stretch the frame was on screen at or after `from` — the inverse of `gaps`.
 *
 * Used to bound what a SOFT closer is allowed to cost when it turns out to have been
 * right: after a genuine disconnect the frame may come back once, briefly, on a payload
 * the server had not yet caught up with. Once, and briefly, are both measurable.
 */
export function presentRunsAfter(samples: Sample[], from: number): Gap[] {
  const runs: Gap[] = [];
  let openedAt: number | null = null;
  for (const s of samples) {
    if (s.at < from) continue;
    if (s.present && openedAt === null) openedAt = s.at;
    if (!s.present && openedAt !== null) {
      runs.push({ from: openedAt, to: s.at, durationMs: s.at - openedAt });
      openedAt = null;
    }
  }
  if (openedAt !== null) {
    const last = samples[samples.length - 1];
    runs.push({ from: openedAt, to: null, durationMs: last.at - openedAt });
  }
  return runs;
}

/** Wait for a `[live-view]` line matching `predicate`, or throw after `timeoutMs`. */
export async function waitForLine(
  recorder: Recorder,
  predicate: (line: LogLine) => boolean,
  timeoutMs: number
): Promise<LogLine> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const hit = recorder.lines.find(predicate);
    if (hit) return hit;
    if (Date.now() > deadline) {
      throw new Error(
        `timed out after ${timeoutMs}ms waiting for a [live-view] line\n` +
          recorder.lines.map((l) => `  ${l.at}ms ${l.text}`).join('\n')
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}
