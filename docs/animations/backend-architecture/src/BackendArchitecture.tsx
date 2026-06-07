import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

export const FPS = 30;
export const DURATION_IN_FRAMES = 1140; // 38s

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

type Pt = {x: number; y: number};

type EdgePath =
  | {kind: 'line'; a: Pt; b: Pt}
  | {kind: 'quad'; a: Pt; c: Pt; b: Pt};

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const pointAt = (p: EdgePath, t: number): Pt => {
  if (p.kind === 'line') {
    return {x: lerp(p.a.x, p.b.x, t), y: lerp(p.a.y, p.b.y, t)};
  }
  const u = 1 - t;
  return {
    x: u * u * p.a.x + 2 * u * t * p.c.x + t * t * p.b.x,
    y: u * u * p.a.y + 2 * u * t * p.c.y + t * t * p.b.y,
  };
};

const pathD = (p: EdgePath): string =>
  p.kind === 'line'
    ? `M ${p.a.x} ${p.a.y} L ${p.b.x} ${p.b.y}`
    : `M ${p.a.x} ${p.a.y} Q ${p.c.x} ${p.c.y} ${p.b.x} ${p.b.y}`;

const pathLength = (p: EdgePath): number => {
  let len = 0;
  let prev = pointAt(p, 0);
  for (let i = 1; i <= 24; i++) {
    const cur = pointAt(p, i / 24);
    len += Math.hypot(cur.x - prev.x, cur.y - prev.y);
    prev = cur;
  }
  return len;
};

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------

const C = {
  bg: '#070b14',
  card: 'rgba(148, 163, 184, 0.06)',
  border: 'rgba(148, 163, 184, 0.28)',
  text: '#e2e8f0',
  subtext: '#94a3b8',
  request: '#38bdf8', // blue – inbound HTTP
  response: '#34d399', // green – responses / DB writes
  claim: '#a78bfa', // violet – Procrastinate queue
  fetch: '#fb923c', // orange – outbound ATS fetches
  back: '#fbbf24', // amber – payloads coming back
  spawn: '#2dd4bf', // teal – subprocess spawn
};

// ---------------------------------------------------------------------------
// Layout (all coordinates are centers unless noted)
// ---------------------------------------------------------------------------

const NODES = {
  browser: {x: 250, y: 300, w: 280, h: 96},
  vercel: {x: 640, y: 300, w: 280, h: 96},
  fastapi: {x: 1060, y: 300, w: 340, h: 96},
  worker: {x: 1060, y: 580, w: 340, h: 96},
  scrapers: {x: 1060, y: 850, w: 340, h: 96},
  postgres: {x: 1640, y: 580, w: 320, h: 150},
};

const RAILWAY_BOX = {x1: 850, y1: 205, x2: 1270, y2: 945};
const ATS_BOX = {x1: 130, y1: 540, x2: 750, y2: 765};
const CAREER_BOX = {x1: 130, y1: 805, x2: 750, y2: 985};

const ATS_CHIPS = [
  {label: 'Greenhouse', x: 255, y: 632},
  {label: 'Ashby', x: 452, y: 632},
  {label: 'Lever', x: 649, y: 632},
  {label: 'Gem', x: 255, y: 710},
  {label: 'Eightfold', x: 452, y: 710},
  {label: 'Workday', x: 649, y: 710},
];

const CAREER_CHIPS = [
  {label: 'Google', x: 255, y: 915},
  {label: 'Apple', x: 452, y: 915},
  {label: 'Microsoft', x: 649, y: 915},
];

const EDGES: Record<string, EdgePath> = {
  browserVercel: {kind: 'line', a: {x: 392, y: 300}, b: {x: 498, y: 300}},
  vercelFastapi: {kind: 'line', a: {x: 782, y: 300}, b: {x: 888, y: 300}},
  fastapiPg: {
    kind: 'quad',
    a: {x: 1232, y: 300},
    c: {x: 1580, y: 300},
    b: {x: 1640, y: 503},
  },
  workerPg: {kind: 'line', a: {x: 1232, y: 580}, b: {x: 1478, y: 580}},
  spawn: {
    kind: 'quad',
    a: {x: 1208, y: 350},
    c: {x: 1296, y: 575},
    b: {x: 1208, y: 800},
  },
  workerAts: {
    kind: 'quad',
    a: {x: 888, y: 580},
    c: {x: 800, y: 600},
    b: {x: 752, y: 628},
  },
  scrapersCareer: {
    kind: 'quad',
    a: {x: 888, y: 850},
    c: {x: 815, y: 870},
    b: {x: 752, y: 893},
  },
  scrapersPg: {
    kind: 'quad',
    a: {x: 1232, y: 850},
    c: {x: 1580, y: 850},
    b: {x: 1640, y: 657},
  },
};

// ---------------------------------------------------------------------------
// Animation schedule
// ---------------------------------------------------------------------------

const SHOW = {
  header: 65,
  browser: 78,
  vercel: 90,
  railwayBox: 100,
  fastapi: 104,
  postgres: 116,
  e1: 122,
  e2: 130,
  e3: 138,
  worker: 360,
  e4: 380,
  atsBox: 400,
  atsChips: 412, // + i * 8
  e6: 424,
  scrapersNode: 690,
  e5: 704,
  careerBox: 716,
  careerChips: 726, // + i * 10
  e7: 738,
  e8: 748,
};

const LOOP_END = 1100;

type PacketDef = {
  path: EdgePath;
  start: number;
  dur: number;
  color: string;
  reverse?: boolean;
  period?: number;
  until?: number;
  size?: number;
};

const SERVE = {start: 170, period: 200};
const INGEST = {start: 440, period: 290};
const SCRAPE = {start: 760, period: 340};

const buildPackets = (): PacketDef[] => {
  const pk: PacketDef[] = [];
  const add = (
    path: EdgePath,
    offset: number,
    dur: number,
    color: string,
    loop: {start: number; period: number},
    reverse = false,
  ) =>
    pk.push({
      path,
      start: loop.start + offset,
      dur,
      color,
      reverse,
      period: loop.period,
      until: LOOP_END,
    });

  // --- Serving: request out, response back -------------------------------
  add(EDGES.browserVercel, 0, 16, C.request, SERVE);
  add(EDGES.vercelFastapi, 16, 16, C.request, SERVE);
  add(EDGES.fastapiPg, 32, 26, C.request, SERVE);
  add(EDGES.fastapiPg, 78, 26, C.response, SERVE, true);
  add(EDGES.vercelFastapi, 104, 16, C.response, SERVE, true);
  add(EDGES.browserVercel, 120, 16, C.response, SERVE, true);

  // --- Ingestion: claim task -> fetch ATS -> payload back -> upsert ------
  add(EDGES.workerPg, 0, 20, C.claim, INGEST, true);
  for (let i = 0; i < 3; i++) {
    add(EDGES.workerAts, 28 + i * 10, 24, C.fetch, INGEST);
    add(EDGES.workerAts, 92 + i * 10, 24, C.back, INGEST, true);
  }
  add(EDGES.workerPg, 150, 22, C.response, INGEST);

  // --- Scraping: spawn -> headless scrape -> payload back -> upsert ------
  add(EDGES.spawn, 0, 30, C.spawn, SCRAPE);
  for (let i = 0; i < 3; i++) {
    add(EDGES.scrapersCareer, 38 + i * 12, 24, C.fetch, SCRAPE);
    add(EDGES.scrapersCareer, 110 + i * 12, 24, C.back, SCRAPE, true);
  }
  add(EDGES.scrapersPg, 165, 28, C.response, SCRAPE);

  return pk;
};

const PACKETS = buildPackets();

const CAPTIONS = [
  {
    from: 150,
    to: 372,
    text: '① Serving — React SPA → Vercel proxy → FastAPI → PostgreSQL',
  },
  {
    from: 388,
    to: 700,
    text: '② Ingestion — in-process Procrastinate worker fans out to six ATS boards',
  },
  {
    from: 712,
    to: 944,
    text: '③ Custom scraping — Playwright subprocesses for Google · Apple · Microsoft',
  },
  {
    from: 958,
    to: 1108,
    text: 'Every source, one endpoint — GET /api/jobs',
  },
];

// ---------------------------------------------------------------------------
// Small presentational pieces
// ---------------------------------------------------------------------------

const useEntrance = (startFrame: number) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({
    frame: frame - startFrame,
    fps,
    config: {damping: 14, stiffness: 120},
  });
  return {
    opacity: frame < startFrame ? 0 : s,
    transform: `scale(${interpolate(s, [0, 1], [0.7, 1])})`,
  };
};

const NodeCard: React.FC<{
  pos: {x: number; y: number; w: number; h: number};
  title: string;
  subtitle: string;
  icon: string;
  accent: string;
  start: number;
}> = ({pos, title, subtitle, icon, accent, start}) => {
  const entrance = useEntrance(start);
  return (
    <div
      style={{
        position: 'absolute',
        left: pos.x - pos.w / 2,
        top: pos.y - pos.h / 2,
        width: pos.w,
        height: pos.h,
        borderRadius: 16,
        background: C.card,
        border: `1.5px solid ${C.border}`,
        boxShadow: `0 0 28px rgba(0,0,0,0.45), inset 0 0 24px rgba(255,255,255,0.02)`,
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '0 18px',
        ...entrance,
      }}
    >
      <div
        style={{
          width: 46,
          height: 46,
          borderRadius: 12,
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 26,
          background: `${accent}1f`,
          border: `1px solid ${accent}55`,
        }}
      >
        {icon}
      </div>
      <div style={{minWidth: 0}}>
        <div
          style={{
            color: C.text,
            fontSize: 23,
            fontWeight: 700,
            letterSpacing: 0.2,
            whiteSpace: 'nowrap',
          }}
        >
          {title}
        </div>
        <div
          style={{
            color: C.subtext,
            fontSize: 15.5,
            marginTop: 3,
            whiteSpace: 'nowrap',
          }}
        >
          {subtitle}
        </div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 14,
          bottom: 14,
          width: 4,
          borderRadius: 4,
          background: accent,
          opacity: 0.9,
        }}
      />
    </div>
  );
};

const Chip: React.FC<{
  label: string;
  x: number;
  y: number;
  accent: string;
  start: number;
  glow: number; // 0..1 pulse
}> = ({label, x, y, accent, start, glow}) => {
  const entrance = useEntrance(start);
  const w = 178;
  const h = 56;
  return (
    <div
      style={{
        position: 'absolute',
        left: x - w / 2,
        top: y - h / 2,
        width: w,
        height: h,
        borderRadius: 12,
        background: C.card,
        border: `1.5px solid ${glow > 0.05 ? accent : C.border}`,
        boxShadow: glow > 0.05 ? `0 0 ${22 * glow}px ${accent}aa` : 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: C.text,
        fontSize: 19,
        fontWeight: 600,
        ...entrance,
      }}
    >
      {label}
    </div>
  );
};

const GroupBox: React.FC<{
  box: {x1: number; y1: number; x2: number; y2: number};
  title: string;
  accent: string;
  start: number;
  dashed?: boolean;
}> = ({box, title, accent, start, dashed}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [start, start + 18], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        left: box.x1,
        top: box.y1,
        width: box.x2 - box.x1,
        height: box.y2 - box.y1,
        borderRadius: 20,
        border: `1.5px ${dashed ? 'dashed' : 'solid'} ${accent}45`,
        background: `${accent}08`,
        opacity,
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
};

const EdgeLine: React.FC<{
  path: EdgePath;
  start: number;
  dashed?: boolean;
}> = ({path, start, dashed}) => {
  const frame = useCurrentFrame();
  const len = pathLength(path);
  const drawn = interpolate(frame, [start, start + 22], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });
  return (
    <path
      d={pathD(path)}
      stroke="rgba(148,163,184,0.4)"
      strokeWidth={2.5}
      fill="none"
      strokeDasharray={dashed ? `9 8` : `${len}`}
      strokeDashoffset={dashed ? undefined : len * (1 - drawn)}
      opacity={dashed ? drawn : 1}
      strokeLinecap="round"
    />
  );
};

const Packet: React.FC<{def: PacketDef}> = ({def}) => {
  const frame = useCurrentFrame();
  const {path, start, dur, color, reverse, period, until, size = 9} = def;
  if (frame < start) return null;
  if (until !== undefined && frame > until + dur) return null;

  let local = frame - start;
  if (period) {
    const cycle = Math.floor(local / period);
    const cycleStart = start + cycle * period;
    if (until !== undefined && cycleStart > until) return null;
    local = local - cycle * period;
  }
  if (local > dur) return null;

  const raw = local / dur;
  const eased = Easing.inOut(Easing.quad)(raw);
  const t = reverse ? 1 - eased : eased;
  const pt = pointAt(path, t);
  const fade =
    raw < 0.12
      ? raw / 0.12
      : raw > 0.88
        ? (1 - raw) / 0.12
        : 1;

  return (
    <div
      style={{
        position: 'absolute',
        left: pt.x - size / 2,
        top: pt.y - size / 2,
        width: size,
        height: size,
        borderRadius: '50%',
        background: color,
        boxShadow: `0 0 14px ${color}, 0 0 28px ${color}88`,
        opacity: fade,
      }}
    />
  );
};

// Pulse helper for chips: returns 0..1 glow for a repeating arrival.
const chipPulse = (
  frame: number,
  loop: {start: number; period: number},
  offset: number,
  width = 34,
): number => {
  if (frame < loop.start + offset) return 0;
  const local = (frame - loop.start - offset) % loop.period;
  if (local > width) return 0;
  const t = local / width;
  return Math.sin(t * Math.PI);
};

const Label: React.FC<{
  x: number;
  y: number;
  text: string;
  start: number;
}> = ({x, y, text, start}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [start, start + 16], [0, 0.95], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        transform: 'translate(-50%, -50%)',
        color: C.subtext,
        fontSize: 15,
        fontStyle: 'italic',
        whiteSpace: 'nowrap',
        opacity,
        background: 'rgba(7,11,20,0.75)',
        padding: '2px 8px',
        borderRadius: 6,
      }}
    >
      {text}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Background
// ---------------------------------------------------------------------------

const DotGrid: React.FC = () => {
  const dots: React.ReactNode[] = [];
  for (let x = 60; x < 1920; x += 90) {
    for (let y = 60; y < 1080; y += 90) {
      dots.push(
        <circle key={`${x}-${y}`} cx={x} cy={y} r={1.6} fill="rgba(148,163,184,0.10)" />,
      );
    }
  }
  return (
    <svg width={1920} height={1080} style={{position: 'absolute'}}>
      {dots}
    </svg>
  );
};

// ---------------------------------------------------------------------------
// Title / captions / header
// ---------------------------------------------------------------------------

const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (frame > 80) return null;
  const s = spring({frame, fps, config: {damping: 16, stiffness: 90}});
  const out = interpolate(frame, [56, 76], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill
      style={{
        alignItems: 'center',
        justifyContent: 'center',
        opacity: out,
      }}
    >
      <div
        style={{
          transform: `scale(${interpolate(s, [0, 1], [0.85, 1])})`,
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: 88,
            fontWeight: 800,
            color: C.text,
            letterSpacing: -1,
          }}
        >
          Job Posting Analytics
        </div>
        <div
          style={{
            fontSize: 36,
            marginTop: 18,
            color: C.request,
            fontWeight: 600,
            letterSpacing: 6,
            textTransform: 'uppercase',
          }}
        >
          Backend Architecture
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Header: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [SHOW.header, SHOW.header + 15], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        top: 36,
        left: 0,
        right: 0,
        textAlign: 'center',
        opacity,
      }}
    >
      <span style={{fontSize: 34, fontWeight: 800, color: C.text}}>
        Job Posting Analytics
      </span>
      <span style={{fontSize: 34, fontWeight: 300, color: C.subtext}}>
        {'  ·  backend architecture'}
      </span>
    </div>
  );
};

const Captions: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      {CAPTIONS.map((cap) => {
        const opacity = interpolate(
          frame,
          [cap.from, cap.from + 14, cap.to - 14, cap.to],
          [0, 1, 1, 0],
          {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
        );
        if (opacity <= 0) return null;
        return (
          <div
            key={cap.from}
            style={{
              position: 'absolute',
              top: 108,
              left: 0,
              right: 0,
              textAlign: 'center',
              opacity,
            }}
          >
            <span
              style={{
                display: 'inline-block',
                fontSize: 26,
                color: C.text,
                background: 'rgba(56,189,248,0.08)',
                border: '1px solid rgba(56,189,248,0.25)',
                borderRadius: 999,
                padding: '10px 30px',
                fontWeight: 500,
              }}
            >
              {cap.text}
            </span>
          </div>
        );
      })}
    </>
  );
};

// ---------------------------------------------------------------------------
// Main composition
// ---------------------------------------------------------------------------

export const BackendArchitecture: React.FC = () => {
  const frame = useCurrentFrame();

  const globalFade = interpolate(frame, [1106, 1138], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at 50% 38%, #0d1426 0%, ${C.bg} 62%)`,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
      }}
    >
      <DotGrid />

      <AbsoluteFill style={{opacity: globalFade}}>
        <Header />
        <Captions />

        {/* Zone boxes */}
        <GroupBox
          box={RAILWAY_BOX}
          title="Railway · Job-Visualizer-Notifier"
          accent="#c084fc"
          start={SHOW.railwayBox}
        />
        <GroupBox
          box={ATS_BOX}
          title="ATS boards · public APIs"
          accent={C.fetch}
          start={SHOW.atsBox}
          dashed
        />
        <GroupBox
          box={CAREER_BOX}
          title="Career sites · headless Chromium"
          accent="#f87171"
          start={SHOW.careerBox}
          dashed
        />

        {/* Edges */}
        <svg width={1920} height={1080} style={{position: 'absolute'}}>
          <EdgeLine path={EDGES.browserVercel} start={SHOW.e1} />
          <EdgeLine path={EDGES.vercelFastapi} start={SHOW.e2} />
          <EdgeLine path={EDGES.fastapiPg} start={SHOW.e3} />
          <EdgeLine path={EDGES.workerPg} start={SHOW.e4} />
          <EdgeLine path={EDGES.workerAts} start={SHOW.e6} />
          <EdgeLine path={EDGES.spawn} start={SHOW.e5} dashed />
          <EdgeLine path={EDGES.scrapersCareer} start={SHOW.e7} />
          <EdgeLine path={EDGES.scrapersPg} start={SHOW.e8} />
        </svg>

        {/* Edge labels */}
        <Label x={445} y={268} text="GET /api/jobs" start={SHOW.e1 + 10} />
        <Label x={1500} y={332} text="asyncpg pool" start={SHOW.e3 + 12} />
        <Label
          x={1355}
          y={552}
          text="claim tasks · upsert jobs"
          start={SHOW.e4 + 12}
        />
        <Label x={1352} y={700} text="spawns subprocess" start={SHOW.e5 + 14} />
        <Label x={1500} y={822} text="upsert jobs" start={SHOW.e8 + 12} />

        {/* Nodes */}
        <NodeCard
          pos={NODES.browser}
          title="React SPA"
          subtitle="Redux Toolkit · RTK Query"
          icon={'🌐'}
          accent={C.request}
          start={SHOW.browser}
        />
        <NodeCard
          pos={NODES.vercel}
          title="Vercel"
          subtitle="serverless proxies · api/jobs.ts"
          icon={'▲'}
          accent="#e2e8f0"
          start={SHOW.vercel}
        />
        <NodeCard
          pos={NODES.fastapi}
          title="FastAPI"
          subtitle="/api/jobs · auth · QA · admin"
          icon={'⚡'}
          accent={C.spawn}
          start={SHOW.fastapi}
        />
        <NodeCard
          pos={NODES.worker}
          title="Procrastinate worker"
          subtitle="in-process · 6× ATS queues + heartbeat"
          icon={'⚙️'}
          accent={C.claim}
          start={SHOW.worker}
        />
        <NodeCard
          pos={NODES.scrapers}
          title="Playwright scrapers"
          subtitle="asyncio subprocess · scripts/"
          icon={'🎭'}
          accent="#4ade80"
          start={SHOW.scrapersNode}
        />
        <NodeCard
          pos={NODES.postgres}
          title="PostgreSQL"
          subtitle="job_listings · scrape_runs · queue"
          icon={'🐘'}
          accent="#818cf8"
          start={SHOW.postgres}
        />

        {/* External source chips */}
        {ATS_CHIPS.map((chip, i) => (
          <Chip
            key={chip.label}
            label={chip.label}
            x={chip.x}
            y={chip.y}
            accent={C.fetch}
            start={SHOW.atsChips + i * 8}
            glow={
              frame <= LOOP_END + 40
                ? chipPulse(frame, INGEST, 56 + i * 7)
                : 0
            }
          />
        ))}
        {CAREER_CHIPS.map((chip, i) => (
          <Chip
            key={chip.label}
            label={chip.label}
            x={chip.x}
            y={chip.y}
            accent="#f87171"
            start={SHOW.careerChips + i * 10}
            glow={
              frame <= LOOP_END + 40
                ? chipPulse(frame, SCRAPE, 66 + i * 12)
                : 0
            }
          />
        ))}

        {/* Animated packets */}
        {PACKETS.map((def, i) => (
          <Packet key={i} def={def} />
        ))}
      </AbsoluteFill>

      <Intro />
    </AbsoluteFill>
  );
};
