import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';

export const FPS = 30;
export const LOOP_FRAMES = 540; // 18s seamless loop

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Pt = {x: number; y: number};
type Key = {f: number; x: number; y: number};

const easeSeg = Easing.inOut(Easing.quad);

/** Interpolate along waypoint keyframes; returns null when not on stage. */
const journey = (
  frame: number,
  keys: Key[],
  fadeIn = 8,
  fadeOut = 10,
): {x: number; y: number; opacity: number} | null => {
  const first = keys[0];
  const last = keys[keys.length - 1];
  if (frame < first.f || frame > last.f + fadeOut) return null;

  let pos: Pt = {x: last.x, y: last.y};
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (frame <= b.f) {
      const t = b.f === a.f ? 1 : easeSeg((frame - a.f) / (b.f - a.f));
      // Arc the motion slightly: lift midpoints on long horizontal moves.
      const lift =
        Math.abs(b.x - a.x) > 220 ? Math.sin(t * Math.PI) * -36 : 0;
      pos = {
        x: a.x + (b.x - a.x) * t,
        y: a.y + (b.y - a.y) * t + lift,
      };
      break;
    }
  }
  const inO = interpolate(frame, [first.f, first.f + fadeIn], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const outO = interpolate(frame, [last.f, last.f + fadeOut], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return {...pos, opacity: Math.min(inO, outO)};
};

/** 0..1 pulse for each instant in `times`. */
const glowAt = (frame: number, times: number[], width = 36): number => {
  let g = 0;
  for (const t of times) {
    const d = frame - t;
    if (d >= 0 && d <= width) g = Math.max(g, Math.sin((d / width) * Math.PI));
  }
  return g;
};

// ---------------------------------------------------------------------------
// Palette / layout
// ---------------------------------------------------------------------------

const C = {
  bg: '#070b14',
  card: 'rgba(148, 163, 184, 0.06)',
  border: 'rgba(148, 163, 184, 0.28)',
  text: '#e2e8f0',
  subtext: '#94a3b8',
  violet: '#a78bfa',
  green: '#34d399',
  teal: '#2dd4bf',
  amber: '#fbbf24',
  blue: '#38bdf8',
  pink: '#f472b6',
};

// `n` = enabled companies per ATS in prod (companies table, 2026-06-06)
const ATS = [
  {name: 'Greenhouse', color: '#4ade80', n: 47},
  {name: 'Ashby', color: '#818cf8', n: 52},
  {name: 'Lever', color: '#e879f9', n: 3},
  {name: 'Gem', color: '#f472b6', n: 3},
  {name: 'Eightfold', color: '#fb923c', n: 1},
  {name: 'Workday', color: '#fbbf24', n: 11},
];
const RED = '#f87171';

const SCHEDULER: Pt = {x: 280, y: 235};
const QUEUE_BOX = {x1: 160, y1: 480, x2: 740, y2: 760};
const PG_BOX = {x1: 110, y1: 415, x2: 790, y2: 1005};
const POOL_BOX = {x1: 900, y1: 200, x2: 1340, y2: 945};
const ATS_BOX = {x1: 1490, y1: 200, x2: 1840, y2: 880};

// queue slots (2 rows x 3 cols)
const QSLOT: Pt[] = [
  {x: 265, y: 590},
  {x: 450, y: 590},
  {x: 635, y: 590},
  {x: 265, y: 685},
  {x: 450, y: 685},
  {x: 635, y: 685},
];

const SLOT_X = 1120;
const SLOT_Y = [330, 465, 600, 735, 870];

const ATS_POS: Pt[] = ATS.map((_, i) => ({x: 1665, y: 285 + i * 102}));

const TABLES = [
  {name: 'job_listings', x: 270, y: 900},
  {name: 'scrape_runs', x: 470, y: 900},
  {name: 'companies', x: 655, y: 900},
];

// ---------------------------------------------------------------------------
// Schedule — one 540-frame cycle
// ---------------------------------------------------------------------------

// Per-company fetch chips: queue slot i, claim frame, worker slot.
// `fail: true` = first attempt fails and the job retries with backoff
// (fetch tasks use RetryStrategy(max_attempts=5, exponential_wait=2)).
const FETCHES = [
  {ats: 0, q: 0, claim: 188, slot: 1, fail: true},
  {ats: 1, q: 1, claim: 200, slot: 2, fail: false},
  {ats: 2, q: 2, claim: 212, slot: 3, fail: false},
  {ats: 3, q: 3, claim: 224, slot: 4, fail: false},
  {ats: 4, q: 4, claim: 236, slot: 0, fail: false},
  {ats: 5, q: 5, claim: 300, slot: 1, fail: false}, // waits for a free worker (backpressure)
];

// Retry choreography for the failing greenhouse job.
const RETRY = {
  failAt: 252, // attempt 1 errors
  released: 296, // slot goes idle, job back in queue
  backToQueue: 316,
  claim: 372, // backoff elapsed, re-claimed
  atSlot: 396,
  done: 512,
  slot: 2,
};

const FANOUT = {spawn: 8, atQueue: 46, claim: 78, atSlot: 102, done: 182};
const PROCESS_LEN = 124; // claim+24 .. claim+24+124 busy

const slotPos = (i: number): Pt => ({x: SLOT_X, y: SLOT_Y[i]});
// chips dock at the right edge of a slot so the worker label stays readable
const slotDock = (i: number): Pt => ({x: SLOT_X + 116, y: SLOT_Y[i]});

type Busy = {from: number; to: number; label: string; color: string};
const SLOT_BUSY: Busy[][] = [[], [], [], [], []];
SLOT_BUSY[0].push({
  from: FANOUT.atSlot,
  to: FANOUT.done,
  label: 'enqueue_fan_out',
  color: C.violet,
});
for (const f of FETCHES) {
  if (f.fail) {
    // attempt 1: fetch, then error + backoff release
    SLOT_BUSY[f.slot].push({
      from: f.claim + 24,
      to: RETRY.failAt,
      label: `fetch_${ATS[f.ats].name.toLowerCase()}`,
      color: ATS[f.ats].color,
    });
    SLOT_BUSY[f.slot].push({
      from: RETRY.failAt,
      to: RETRY.released,
      label: '✗ error — backoff, retry 2/5',
      color: RED,
    });
    // attempt 2 on another worker after backoff
    SLOT_BUSY[RETRY.slot].push({
      from: RETRY.atSlot,
      to: RETRY.done,
      label: `fetch_${ATS[f.ats].name.toLowerCase()} · attempt 2`,
      color: ATS[f.ats].color,
    });
  } else {
    SLOT_BUSY[f.slot].push({
      from: f.claim + 24,
      to: f.claim + 24 + PROCESS_LEN,
      label: `fetch_${ATS[f.ats].name.toLowerCase()}`,
      color: ATS[f.ats].color,
    });
  }
}
// heartbeat blip late in the cycle
SLOT_BUSY[3].push({from: 506, to: 526, label: 'heartbeat', color: C.pink});

// ---------------------------------------------------------------------------
// Packets (straight or gently curved point-to-point dots)
// ---------------------------------------------------------------------------

type PacketDef = {
  a: Pt;
  b: Pt;
  start: number;
  dur: number;
  color: string;
  arc?: number;
};

const PACKETS: PacketDef[] = [];

// fan-out queries the companies table
PACKETS.push({
  a: slotPos(0),
  b: TABLES[2],
  start: 106,
  dur: 24,
  color: C.blue,
  arc: 60,
});
PACKETS.push({
  a: TABLES[2],
  b: slotPos(0),
  start: 134,
  dur: 24,
  color: C.amber,
  arc: 60,
});

const ATS_GLOWS: number[][] = ATS.map(() => []);
const TABLE_GLOWS: number[][] = TABLES.map(() => []);
TABLE_GLOWS[2].push(126);

for (const f of FETCHES) {
  const b = f.claim + 24;
  const sp = slotPos(f.slot);
  const ap = ATS_POS[f.ats];
  if (f.fail) {
    // attempt 1: fetch out, error comes back red — no upserts
    PACKETS.push({a: sp, b: ap, start: b + 8, dur: 26, color: ATS[f.ats].color});
    PACKETS.push({a: ap, b: sp, start: RETRY.failAt, dur: 26, color: RED});
    ATS_GLOWS[f.ats].push(b + 30);
    // attempt 2 after backoff, from a different worker
    const rp = slotPos(RETRY.slot);
    PACKETS.push({a: rp, b: ap, start: RETRY.atSlot + 6, dur: 26, color: ATS[f.ats].color});
    PACKETS.push({a: ap, b: rp, start: RETRY.atSlot + 38, dur: 24, color: C.amber});
    ATS_GLOWS[f.ats].push(RETRY.atSlot + 28);
    PACKETS.push({a: rp, b: TABLES[0], start: RETRY.atSlot + 70, dur: 26, color: C.green, arc: 70});
    PACKETS.push({a: rp, b: TABLES[1], start: RETRY.atSlot + 80, dur: 24, color: C.teal, arc: 70});
    TABLE_GLOWS[0].push(RETRY.atSlot + 94);
    TABLE_GLOWS[1].push(RETRY.atSlot + 102);
    continue;
  }
  // HTTP fetch out + payload back
  PACKETS.push({a: sp, b: ap, start: b + 8, dur: 26, color: ATS[f.ats].color});
  PACKETS.push({a: ap, b: sp, start: b + 42, dur: 26, color: C.amber});
  ATS_GLOWS[f.ats].push(b + 30);
  // upserts
  PACKETS.push({
    a: sp,
    b: TABLES[0],
    start: b + 80,
    dur: 28,
    color: C.green,
    arc: 70,
  });
  PACKETS.push({
    a: sp,
    b: TABLES[1],
    start: b + 92,
    dur: 26,
    color: C.teal,
    arc: 70,
  });
  TABLE_GLOWS[0].push(b + 104);
  TABLE_GLOWS[1].push(b + 114);
}

// ---------------------------------------------------------------------------
// Step badges
// ---------------------------------------------------------------------------

const STEPS = [
  {n: '1', text: 'cron tick (*/30) → defer fan-out', x: 280, y: 330, active: [0, 70] as const},
  {n: '2', text: 'fan-out: 1 fetch job per company (117 enabled)', x: 450, y: 792, active: [130, 210] as const},
  {n: '3', text: 'workers claim · concurrency = 5', x: 1120, y: 980, active: [185, 290] as const},
  {n: '4', text: 'fetch postings over HTTP', x: 1665, y: 915, active: [225, 330] as const},
  {n: '5', text: 'upsert job_listings · scrape_runs', x: 415, y: 970, active: [295, 430] as const},
  {n: '6', text: '✗ errors re-queue with backoff (5 attempts)', x: 450, y: 838, active: [252, 330] as const},
];

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

const Packet: React.FC<{def: PacketDef; frame: number}> = ({def, frame}) => {
  const {a, b, start, dur, color, arc = 0} = def;
  if (frame < start || frame > start + dur) return null;
  const raw = (frame - start) / dur;
  const t = easeSeg(raw);
  const x = a.x + (b.x - a.x) * t;
  const y = a.y + (b.y - a.y) * t + Math.sin(t * Math.PI) * arc;
  const fade = raw < 0.12 ? raw / 0.12 : raw > 0.88 ? (1 - raw) / 0.12 : 1;
  return (
    <div
      style={{
        position: 'absolute',
        left: x - 5,
        top: y - 5,
        width: 10,
        height: 10,
        borderRadius: '50%',
        background: color,
        boxShadow: `0 0 14px ${color}, 0 0 30px ${color}88`,
        opacity: fade,
      }}
    />
  );
};

const JobChip: React.FC<{
  label: string;
  color: string;
  keys: Key[];
  frame: number;
}> = ({label, color, keys, frame}) => {
  const pos = journey(frame, keys);
  if (!pos) return null;
  const w = 152;
  const h = 44;
  return (
    <div
      style={{
        position: 'absolute',
        left: pos.x - w / 2,
        top: pos.y - h / 2,
        width: w,
        height: h,
        borderRadius: 10,
        background: '#0c1322',
        border: `1.8px solid ${color}`,
        boxShadow: `0 0 16px ${color}55`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: C.text,
        fontSize: 15.5,
        fontWeight: 700,
        opacity: pos.opacity,
        zIndex: 5,
      }}
    >
      {label}
    </div>
  );
};

const WorkerSlot: React.FC<{index: number; frame: number}> = ({
  index,
  frame,
}) => {
  const busy = SLOT_BUSY[index].find((b) => frame >= b.from && frame <= b.to);
  const y = SLOT_Y[index];
  const w = 380;
  const h = 100;
  return (
    <div
      style={{
        position: 'absolute',
        left: SLOT_X - w / 2,
        top: y - h / 2,
        width: w,
        height: h,
        borderRadius: 14,
        background: busy ? `${busy.color}14` : C.card,
        border: `1.8px solid ${busy ? busy.color : C.border}`,
        boxShadow: busy ? `0 0 22px ${busy.color}44` : 'none',
        display: 'flex',
        alignItems: 'center',
        padding: '0 20px',
        gap: 16,
      }}
    >
      <div
        style={{
          width: 14,
          height: 14,
          borderRadius: '50%',
          background: busy ? busy.color : 'rgba(148,163,184,0.35)',
          boxShadow: busy ? `0 0 12px ${busy.color}` : 'none',
        }}
      />
      <div>
        <div style={{color: C.text, fontSize: 21, fontWeight: 700}}>
          worker-{index + 1}
        </div>
        <div
          style={{
            color: busy ? busy.color : C.subtext,
            fontSize: 15.5,
            marginTop: 2,
            fontFamily: 'Menlo, monospace',
          }}
        >
          {busy ? `▶ ${busy.label}` : 'idle — polling queue'}
        </div>
      </div>
    </div>
  );
};

const Zone: React.FC<{
  box: {x1: number; y1: number; x2: number; y2: number};
  title: string;
  accent: string;
  dashed?: boolean;
}> = ({box, title, accent, dashed}) => (
  <div
    style={{
      position: 'absolute',
      left: box.x1,
      top: box.y1,
      width: box.x2 - box.x1,
      height: box.y2 - box.y1,
      borderRadius: 20,
      border: `1.5px ${dashed ? 'dashed' : 'solid'} ${accent}45`,
      background: `${accent}07`,
    }}
  >
    <div
      style={{
        position: 'absolute',
        top: 12,
        left: 20,
        color: `${accent}dd`,
        fontSize: 16,
        fontWeight: 700,
        letterSpacing: 1.4,
        textTransform: 'uppercase',
      }}
    >
      {title}
    </div>
  </div>
);

const TableCard: React.FC<{
  name: string;
  x: number;
  y: number;
  glow: number;
}> = ({name, x, y, glow}) => {
  const w = 172;
  const h = 56;
  return (
    <div
      style={{
        position: 'absolute',
        left: x - w / 2,
        top: y - h / 2,
        width: w,
        height: h,
        borderRadius: 10,
        background: C.card,
        border: `1.5px solid ${glow > 0.05 ? C.green : C.border}`,
        boxShadow: glow > 0.05 ? `0 0 ${22 * glow}px ${C.green}aa` : 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: C.text,
        fontSize: 17.5,
        fontFamily: 'Menlo, monospace',
      }}
    >
      {name}
    </div>
  );
};

const StepBadge: React.FC<{
  step: (typeof STEPS)[number];
  frame: number;
}> = ({step, frame}) => {
  const active = glowAt(frame, [step.active[0]], step.active[1] - step.active[0]);
  const accent = C.blue;
  return (
    <div
      style={{
        position: 'absolute',
        left: step.x,
        top: step.y,
        transform: 'translate(-50%, -50%)',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        whiteSpace: 'nowrap',
        zIndex: 6,
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: '50%',
          background: active > 0.1 ? accent : 'rgba(56,189,248,0.14)',
          border: `1.5px solid ${accent}`,
          color: active > 0.1 ? '#04111d' : accent,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 19,
          fontWeight: 800,
          boxShadow: active > 0.1 ? `0 0 ${18 * active}px ${accent}` : 'none',
          flexShrink: 0,
        }}
      >
        {step.n}
      </div>
      <div
        style={{
          color: active > 0.1 ? C.text : C.subtext,
          fontSize: 18.5,
          fontWeight: 600,
        }}
      >
        {step.text}
      </div>
    </div>
  );
};

const DotGrid: React.FC = () => {
  const dots: React.ReactNode[] = [];
  for (let x = 60; x < 1920; x += 90) {
    for (let y = 60; y < 1080; y += 90) {
      dots.push(
        <circle
          key={`${x}-${y}`}
          cx={x}
          cy={y}
          r={1.6}
          fill="rgba(148,163,184,0.10)"
        />,
      );
    }
  }
  return (
    <svg width={1920} height={1080} style={{position: 'absolute'}}>
      {dots}
    </svg>
  );
};

// faint static guide arrows between stages
const Guides: React.FC = () => (
  <svg width={1920} height={1080} style={{position: 'absolute'}}>
    <defs>
      <marker
        id="arr"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(148,163,184,0.30)" />
      </marker>
    </defs>
    {[
      'M 280 300 Q 280 400 300 470', // scheduler -> queue
      'M 750 620 Q 830 620 890 580', // queue -> pool
      'M 1350 540 Q 1420 540 1480 540', // pool -> ats
      'M 890 760 Q 820 850 745 890', // pool -> tables
    ].map((d) => (
      <path
        key={d}
        d={d}
        stroke="rgba(148,163,184,0.22)"
        strokeWidth={2}
        strokeDasharray="7 7"
        fill="none"
        markerEnd="url(#arr)"
      />
    ))}
  </svg>
);

// ---------------------------------------------------------------------------
// Main composition — seamless loop
// ---------------------------------------------------------------------------

export const IngestionPipeline: React.FC = () => {
  const frame = useCurrentFrame() % LOOP_FRAMES;

  const schedulerGlow = glowAt(frame, [0, 460], 30);

  // fan-out chip
  const fanoutKeys: Key[] = [
    {f: FANOUT.spawn, ...SCHEDULER},
    {f: FANOUT.atQueue, ...QSLOT[0]},
    {f: FANOUT.claim, ...QSLOT[0]},
    {f: FANOUT.atSlot, ...slotDock(0)},
    {f: FANOUT.done, ...slotDock(0)},
  ];

  // heartbeat chip
  const heartKeys: Key[] = [
    {f: 462, ...SCHEDULER},
    {f: 484, ...QSLOT[0]},
    {f: 488, ...QSLOT[0]},
    {f: 508, ...slotDock(3)},
    {f: 524, ...slotDock(3)},
  ];

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at 50% 40%, #0d1426 0%, ${C.bg} 62%)`,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
      }}
    >
      <DotGrid />
      <Guides />

      {/* Header */}
      <div style={{position: 'absolute', top: 34, left: 0, right: 0, textAlign: 'center'}}>
        <span style={{fontSize: 32, fontWeight: 800, color: C.text}}>
          Ingestion pipeline
        </span>
        <span style={{fontSize: 32, fontWeight: 300, color: C.subtext}}>
          {'  ·  Procrastinate worker on Railway'}
        </span>
      </div>

      {/* Zones */}
      <Zone box={PG_BOX} title="PostgreSQL (Railway)" accent="#818cf8" />
      <Zone box={POOL_BOX} title="Procrastinate worker · in-process" accent={C.violet} />
      <Zone box={ATS_BOX} title="ATS public APIs" accent="#fb923c" dashed />

      {/* Queue box inside Postgres */}
      <div
        style={{
          position: 'absolute',
          left: QUEUE_BOX.x1,
          top: QUEUE_BOX.y1,
          width: QUEUE_BOX.x2 - QUEUE_BOX.x1,
          height: QUEUE_BOX.y2 - QUEUE_BOX.y1,
          borderRadius: 16,
          border: `1.5px solid rgba(56,189,248,0.35)`,
          background: 'rgba(56,189,248,0.05)',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 12,
            left: 18,
            color: 'rgba(56,189,248,0.9)',
            fontSize: 16,
            fontWeight: 700,
            fontFamily: 'Menlo, monospace',
          }}
        >
          procrastinate_jobs — queue
        </div>
      </div>

      {/* Scheduler */}
      <div
        style={{
          position: 'absolute',
          left: SCHEDULER.x - 170,
          top: SCHEDULER.y - 55,
          width: 340,
          height: 110,
          borderRadius: 16,
          background: C.card,
          border: `1.8px solid ${schedulerGlow > 0.05 ? C.blue : C.border}`,
          boxShadow:
            schedulerGlow > 0.05 ? `0 0 ${26 * schedulerGlow}px ${C.blue}aa` : 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '0 18px',
        }}
      >
        <div style={{fontSize: 30}}>⏰</div>
        <div>
          <div style={{color: C.text, fontSize: 22, fontWeight: 700}}>
            Periodic deferrer
          </div>
          <div style={{color: C.subtext, fontSize: 15.5, marginTop: 2, fontFamily: 'Menlo, monospace'}}>
            cron */30 · runs in worker
          </div>
        </div>
      </div>

      {/* Worker slots */}
      {SLOT_Y.map((_, i) => (
        <WorkerSlot key={i} index={i} frame={frame} />
      ))}

      {/* ATS chips */}
      {ATS.map((ats, i) => {
        const glow = glowAt(frame, ATS_GLOWS[i]);
        const w = 240;
        const h = 70;
        return (
          <div
            key={ats.name}
            style={{
              position: 'absolute',
              left: ATS_POS[i].x - w / 2,
              top: ATS_POS[i].y - h / 2,
              width: w,
              height: h,
              borderRadius: 12,
              background: C.card,
              border: `1.8px solid ${glow > 0.05 ? ats.color : C.border}`,
              boxShadow: glow > 0.05 ? `0 0 ${24 * glow}px ${ats.color}aa` : 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 12,
              color: C.text,
              fontSize: 21,
              fontWeight: 700,
            }}
          >
            <div
              style={{
                width: 12,
                height: 12,
                borderRadius: '50%',
                background: ats.color,
              }}
            />
            {ats.name}
          </div>
        );
      })}

      {/* Postgres tables */}
      {TABLES.map((t, i) => (
        <TableCard
          key={t.name}
          name={t.name}
          x={t.x}
          y={t.y}
          glow={glowAt(frame, TABLE_GLOWS[i])}
        />
      ))}

      {/* Step badges */}
      {STEPS.map((s) => (
        <StepBadge key={s.n} step={s} frame={frame} />
      ))}

      {/* Moving job chips */}
      <JobChip label="fan-out" color={C.violet} keys={fanoutKeys} frame={frame} />
      {FETCHES.map((f, i) => {
        const spawn = 130 + i * 8;
        const keys: Key[] = f.fail
          ? [
              {f: spawn, ...slotPos(0)},
              {f: spawn + 26, ...QSLOT[f.q]},
              {f: f.claim, ...QSLOT[f.q]},
              {f: f.claim + 24, ...slotDock(f.slot)},
              {f: RETRY.released, ...slotDock(f.slot)},
              {f: RETRY.backToQueue, ...QSLOT[f.q]}, // job re-queued for backoff
              {f: RETRY.claim, ...QSLOT[f.q]},
              {f: RETRY.atSlot, ...slotDock(RETRY.slot)},
              {f: RETRY.done, ...slotDock(RETRY.slot)},
            ]
          : [
              {f: spawn, ...slotPos(0)},
              {f: spawn + 26, ...QSLOT[f.q]},
              {f: f.claim, ...QSLOT[f.q]},
              {f: f.claim + 24, ...slotDock(f.slot)},
              {f: f.claim + 24 + PROCESS_LEN, ...slotDock(f.slot)},
            ];
        return (
          <JobChip
            key={i}
            label={`${ATS[f.ats].name.toLowerCase()} ×${ATS[f.ats].n}`}
            color={ATS[f.ats].color}
            keys={keys}
            frame={frame}
          />
        );
      })}
      <JobChip label="♥ beat" color={C.pink} keys={heartKeys} frame={frame} />

      {/* Packets */}
      {PACKETS.map((def, i) => (
        <Packet key={i} def={def} frame={frame} />
      ))}
    </AbsoluteFill>
  );
};
