import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';

export const WEBSCRAPER_LOOP_FRAMES = 750; // 25s seamless loop

// ---------------------------------------------------------------------------
// Helpers (same conventions as IngestionPipeline)
// ---------------------------------------------------------------------------

type Pt = {x: number; y: number};
type Key = {f: number; x: number; y: number};

const easeSeg = Easing.inOut(Easing.quad);

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
      const lift = Math.abs(b.x - a.x) > 220 ? Math.sin(t * Math.PI) * -36 : 0;
      pos = {x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t + lift};
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

const glowAt = (frame: number, times: number[], width = 30): number => {
  let g = 0;
  for (const t of times) {
    const d = frame - t;
    if (d >= 0 && d <= width) g = Math.max(g, Math.sin((d / width) * Math.PI));
  }
  return g;
};

const C = {
  bg: '#070b14',
  card: 'rgba(148, 163, 184, 0.06)',
  border: 'rgba(148, 163, 184, 0.28)',
  text: '#e2e8f0',
  subtext: '#94a3b8',
  green: '#34d399',
  teal: '#2dd4bf',
  amber: '#fbbf24',
  blue: '#38bdf8',
  violet: '#a78bfa',
};

// ---------------------------------------------------------------------------
// Schedule — one hourly auto-scraper cycle, strictly serial under the lock.
// Stats from prod scrape_runs (48h averages, 2026-06-06).
// ---------------------------------------------------------------------------

type Company = {
  name: string;
  host: string;
  color: string;
  jobs: number;
  min: number;
  s: number; // segment start frame
  nb: number; // pagination bursts
};

const COMPANIES: Company[] = [
  {name: 'Google', host: 'google.com/about/careers', color: '#60a5fa', jobs: 748, min: 5, s: 40, nb: 4},
  {name: 'Apple', host: 'jobs.apple.com', color: '#e2e8f0', jobs: 3766, min: 22, s: 270, nb: 5},
  {name: 'Microsoft', host: 'careers.microsoft.com', color: '#4ade80', jobs: 307, min: 2, s: 525, nb: 3},
];

const PAG_SPACING = 24;
const pagStart = (c: Company) => c.s + 60;
const upsertStart = (c: Company) => pagStart(c) + c.nb * PAG_SPACING + 12;
const chipEnd = (c: Company) => upsertStart(c) + 52;
const lockEnd = (c: Company) => upsertStart(c) + 58;

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

const AUTO: Pt = {x: 330, y: 230};
const LOCK: Pt = {x: 330, y: 425};
const WATCHDOG: Pt = {x: 330, y: 645};
const CMD: Pt = {x: 985, y: 268};
const CMD_DOCK: Pt = {x: 1235, y: 268};
const BROWSER = {x: 985, y: 515, w: 560, h: 340};
const CONTAINER_BOX = {x1: 140, y1: 120, x2: 1340, y2: 790};
const SUBPROC_BOX = {x1: 660, y1: 170, x2: 1310, y2: 770};
const CAREER_BOX = {x1: 1430, y1: 170, x2: 1850, y2: 710};
const PG_BOX = {x1: 660, y1: 830, x2: 1310, y2: 1025};

const CAREER_POS: Pt[] = [
  {x: 1640, y: 305},
  {x: 1640, y: 445},
  {x: 1640, y: 585},
];

const TABLES = [
  {name: 'job_listings', x: 880, y: 935},
  {name: 'scrape_runs', x: 1140, y: 935},
];

// ---------------------------------------------------------------------------
// Packets / glows
// ---------------------------------------------------------------------------

type PacketDef = {a: Pt; b: Pt; start: number; dur: number; color: string; arc?: number};
const PACKETS: PacketDef[] = [];
const CAREER_GLOWS: number[][] = COMPANIES.map(() => []);
const TABLE_GLOWS: number[][] = TABLES.map(() => []);

COMPANIES.forEach((c, ci) => {
  const browserRight: Pt = {x: BROWSER.x + BROWSER.w / 2, y: BROWSER.y};
  const browserBottom: Pt = {x: BROWSER.x, y: BROWSER.y + BROWSER.h / 2};
  const site = CAREER_POS[ci];
  // pagination: request out, page back, per burst
  for (let k = 0; k < c.nb; k++) {
    const t = pagStart(c) + k * PAG_SPACING;
    PACKETS.push({a: browserRight, b: site, start: t, dur: 16, color: c.color});
    PACKETS.push({a: site, b: browserRight, start: t + 16, dur: 16, color: C.amber});
    CAREER_GLOWS[ci].push(t + 12);
  }
  // upserts at the end of the run
  const u = upsertStart(c);
  for (let k = 0; k < 3; k++) {
    PACKETS.push({a: browserBottom, b: TABLES[0], start: u + k * 12, dur: 20, color: C.green, arc: 30});
  }
  PACKETS.push({a: browserBottom, b: TABLES[1], start: u + 34, dur: 18, color: C.teal, arc: 30});
  TABLE_GLOWS[0].push(u + 20);
  TABLE_GLOWS[1].push(u + 50);
});

// ---------------------------------------------------------------------------
// Step badges
// ---------------------------------------------------------------------------

const STEPS = [
  {n: '1', text: 'auto-scraper wakes — every 1h', x: 330, y: 322, active: [0, 60] as const},
  {n: '2', text: 'acquire scraper_lock — strictly serial', x: 330, y: 510, active: [44, 110] as const},
  {n: '3', text: 'spawn run_scraper.py --incremental --headless', x: 985, y: 805, active: [78, 150] as const},
  {n: '4', text: 'headless Chromium paginates the board', x: 1640, y: 745, active: [100, 200] as const},
  {n: '5', text: 'upsert job_listings · record scrape_runs', x: 985, y: 1055, active: [205, 280] as const},
];

// ---------------------------------------------------------------------------
// Pieces
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

const InfoCard: React.FC<{
  pos: Pt;
  w: number;
  h: number;
  icon?: string;
  title: string;
  subtitle: React.ReactNode;
  glow?: number;
  glowColor?: string;
}> = ({pos, w, h, icon, title, subtitle, glow = 0, glowColor = C.blue}) => (
  <div
    style={{
      position: 'absolute',
      left: pos.x - w / 2,
      top: pos.y - h / 2,
      width: w,
      height: h,
      borderRadius: 16,
      background: C.card,
      border: `1.8px solid ${glow > 0.05 ? glowColor : C.border}`,
      boxShadow: glow > 0.05 ? `0 0 ${26 * glow}px ${glowColor}aa` : 'none',
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      padding: '0 18px',
    }}
  >
    {icon ? <div style={{fontSize: 30}}>{icon}</div> : null}
    <div style={{minWidth: 0}}>
      <div style={{color: C.text, fontSize: 22, fontWeight: 700, whiteSpace: 'nowrap'}}>
        {title}
      </div>
      <div
        style={{
          color: C.subtext,
          fontSize: 15.5,
          marginTop: 2,
          fontFamily: 'Menlo, monospace',
          whiteSpace: 'nowrap',
        }}
      >
        {subtitle}
      </div>
    </div>
  </div>
);

const StepBadge: React.FC<{step: (typeof STEPS)[number]; frame: number}> = ({
  step,
  frame,
}) => {
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
      <div style={{color: active > 0.1 ? C.text : C.subtext, fontSize: 18.5, fontWeight: 600}}>
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

const Guides: React.FC = () => (
  <svg width={1920} height={1080} style={{position: 'absolute'}}>
    <defs>
      <marker
        id="warr"
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
      'M 330 290 L 330 372', // auto -> lock
      'M 525 425 Q 600 400 655 330', // lock -> subprocess
      'M 1315 440 Q 1375 440 1425 440', // subprocess -> career sites
      'M 985 775 L 985 825', // subprocess -> postgres
    ].map((d) => (
      <path
        key={d}
        d={d}
        stroke="rgba(148,163,184,0.22)"
        strokeWidth={2}
        strokeDasharray="7 7"
        fill="none"
        markerEnd="url(#warr)"
      />
    ))}
  </svg>
);

// ---------------------------------------------------------------------------
// Main composition
// ---------------------------------------------------------------------------

export const WebscraperPipeline: React.FC = () => {
  const frame = useCurrentFrame() % WEBSCRAPER_LOOP_FRAMES;

  const active = COMPANIES.find((c) => frame >= c.s && frame <= chipEnd(c)) ?? null;
  const lockHolder =
    COMPANIES.find((c) => frame >= c.s + 18 && frame <= lockEnd(c)) ?? null;

  // counters for the active segment
  const counting = active
    ? interpolate(frame, [pagStart(active), upsertStart(active) + 6], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: Easing.out(Easing.quad),
      })
    : 0;
  const jobsSeen = active ? Math.round(active.jobs * counting) : 0;
  const elapsedMin = active ? (active.min * counting).toFixed(1) : '0.0';
  const page = active
    ? Math.max(
        1,
        Math.min(active.nb, 1 + Math.floor((frame - pagStart(active)) / PAG_SPACING)),
      )
    : 0;

  const autoGlow = glowAt(frame, [0, ...COMPANIES.map((c) => c.s - 10)], 26);

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
          Webscraper pipeline
        </span>
        <span style={{fontSize: 32, fontWeight: 300, color: C.subtext}}>
          {'  ·  Playwright subprocess on Railway'}
        </span>
      </div>

      {/* Zones */}
      <Zone box={CONTAINER_BOX} title="Railway · Job-Visualizer-Notifier" accent={C.violet} />
      <Zone box={SUBPROC_BOX} title="child process · run_scraper.py" accent={C.teal} dashed />
      <Zone box={CAREER_BOX} title="Career sites" accent="#f87171" dashed />
      <Zone box={PG_BOX} title="PostgreSQL (Railway)" accent="#818cf8" />

      {/* Auto-scraper + lock + watchdog */}
      <InfoCard
        pos={AUTO}
        w={380}
        h={110}
        icon="⏰"
        title="auto-scraper"
        subtitle="every 1h · asyncio task in API"
        glow={autoGlow}
      />
      <InfoCard
        pos={LOCK}
        w={380}
        h={94}
        icon={lockHolder ? '🔒' : '🔓'}
        title="scraper_lock"
        subtitle={
          lockHolder ? `held by ${lockHolder.name.toLowerCase()}` : 'free — next acquire waits'
        }
        glow={lockHolder ? 0.8 : 0}
        glowColor={lockHolder?.color ?? C.blue}
      />
      {/* Watchdog */}
      <div
        style={{
          position: 'absolute',
          left: WATCHDOG.x - 190,
          top: WATCHDOG.y - 58,
          width: 380,
          height: 116,
          borderRadius: 16,
          background: C.card,
          border: `1.8px solid ${C.border}`,
          padding: '14px 18px',
        }}
      >
        <div style={{color: C.text, fontSize: 20, fontWeight: 700}}>
          ⏱ watchdog — 90 min timeout
        </div>
        <div
          style={{
            color: C.subtext,
            fontSize: 15,
            marginTop: 4,
            fontFamily: 'Menlo, monospace',
          }}
        >
          {active ? `elapsed ${elapsedMin}m / 90m → kill if stuck` : 'idle'}
        </div>
        <div
          style={{
            marginTop: 10,
            height: 8,
            borderRadius: 4,
            background: 'rgba(148,163,184,0.15)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${active ? (Number(elapsedMin) / 90) * 100 : 0}%`,
              height: '100%',
              borderRadius: 4,
              background: active?.color ?? C.blue,
            }}
          />
        </div>
      </div>

      {/* Command card */}
      <div
        style={{
          position: 'absolute',
          left: CMD.x - 305,
          top: CMD.y - 30,
          width: 610,
          height: 60,
          borderRadius: 12,
          background: '#0c1322',
          border: `1.5px solid ${active ? `${active.color}88` : C.border}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 18px',
          fontFamily: 'Menlo, monospace',
          fontSize: 15.5,
          color: active ? C.text : C.subtext,
          whiteSpace: 'nowrap',
        }}
      >
        {active
          ? `$ run_scraper.py --company ${active.name.toLowerCase()} --incremental --headless`
          : '$ … sleeping until next interval'}
      </div>

      {/* Browser frame */}
      <div
        style={{
          position: 'absolute',
          left: BROWSER.x - BROWSER.w / 2,
          top: BROWSER.y - BROWSER.h / 2,
          width: BROWSER.w,
          height: BROWSER.h,
          borderRadius: 14,
          background: '#0a101d',
          border: `1.5px solid ${active ? `${active.color}66` : C.border}`,
          overflow: 'hidden',
        }}
      >
        {/* title bar */}
        <div
          style={{
            height: 44,
            background: 'rgba(148,163,184,0.08)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '0 16px',
          }}
        >
          {['#f87171', '#fbbf24', '#34d399'].map((c) => (
            <div key={c} style={{width: 12, height: 12, borderRadius: '50%', background: c}} />
          ))}
          <div
            style={{
              marginLeft: 12,
              flex: 1,
              height: 26,
              borderRadius: 13,
              background: 'rgba(148,163,184,0.10)',
              display: 'flex',
              alignItems: 'center',
              padding: '0 14px',
              fontFamily: 'Menlo, monospace',
              fontSize: 14,
              color: active ? C.text : C.subtext,
            }}
          >
            {active ? `https://${active.host}` : 'about:blank'}
          </div>
        </div>
        {/* job rows skeleton, re-rendered per "page" */}
        <div style={{padding: '18px 22px'}}>
          {[0, 1, 2, 3, 4, 5].map((row) => {
            const o = active
              ? interpolate(
                  frame - pagStart(active) - (page - 1) * PAG_SPACING - row * 3,
                  [0, 7],
                  [0, 1],
                  {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
                )
              : 0.12;
            const w = [78, 62, 70, 55, 66, 48][row];
            return (
              <div key={row} style={{display: 'flex', gap: 10, marginBottom: 14, opacity: o}}>
                <div
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: 5,
                    background: active ? `${active.color}55` : 'rgba(148,163,184,0.2)',
                  }}
                />
                <div
                  style={{
                    width: `${w}%`,
                    height: 18,
                    borderRadius: 5,
                    background: 'rgba(148,163,184,0.22)',
                  }}
                />
              </div>
            );
          })}
          {/* status line */}
          <div
            style={{
              marginTop: 6,
              fontFamily: 'Menlo, monospace',
              fontSize: 15.5,
              color: active ? active.color : C.subtext,
            }}
          >
            {active
              ? `page ${page}/${active.nb} · jobs seen: ${jobsSeen.toLocaleString()}`
              : 'headless · idle'}
          </div>
        </div>
      </div>

      {/* Career site cards */}
      {COMPANIES.map((c, i) => {
        const glow = glowAt(frame, CAREER_GLOWS[i], 22);
        const w = 330;
        const h = 96;
        return (
          <div
            key={c.name}
            style={{
              position: 'absolute',
              left: CAREER_POS[i].x - w / 2,
              top: CAREER_POS[i].y - h / 2,
              width: w,
              height: h,
              borderRadius: 14,
              background: C.card,
              border: `1.8px solid ${glow > 0.05 ? c.color : C.border}`,
              boxShadow: glow > 0.05 ? `0 0 ${24 * glow}px ${c.color}aa` : 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              padding: '0 20px',
            }}
          >
            <div style={{width: 14, height: 14, borderRadius: '50%', background: c.color}} />
            <div>
              <div style={{color: C.text, fontSize: 22, fontWeight: 700}}>{c.name}</div>
              <div style={{color: C.subtext, fontSize: 15, marginTop: 2, fontFamily: 'Menlo, monospace'}}>
                ~{c.jobs.toLocaleString()} jobs · ~{c.min} min/run
              </div>
            </div>
          </div>
        );
      })}

      {/* Postgres tables */}
      {TABLES.map((t, i) => {
        const glow = glowAt(frame, TABLE_GLOWS[i]);
        const w = 200;
        const h = 58;
        return (
          <div
            key={t.name}
            style={{
              position: 'absolute',
              left: t.x - w / 2,
              top: t.y - h / 2,
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
            {t.name}
          </div>
        );
      })}

      {/* Step badges */}
      {STEPS.map((s) => (
        <StepBadge key={s.n} step={s} frame={frame} />
      ))}

      {/* Per-company dispatch chips: auto-scraper → lock → subprocess */}
      {COMPANIES.map((c) => {
        const keys: Key[] = [
          {f: c.s, ...AUTO},
          {f: c.s + 18, ...LOCK},
          {f: c.s + 26, ...LOCK},
          {f: c.s + 48, ...CMD_DOCK},
          {f: chipEnd(c), ...CMD_DOCK},
        ];
        const pos = journey(frame, keys);
        if (!pos) return null;
        const w = 132;
        const h = 44;
        return (
          <div
            key={c.name}
            style={{
              position: 'absolute',
              left: pos.x - w / 2,
              top: pos.y - h / 2,
              width: w,
              height: h,
              borderRadius: 10,
              background: '#0c1322',
              border: `1.8px solid ${c.color}`,
              boxShadow: `0 0 16px ${c.color}55`,
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
            {c.name.toLowerCase()}
          </div>
        );
      })}

      {/* Packets */}
      {PACKETS.map((def, i) => (
        <Packet key={i} def={def} frame={frame} />
      ))}
    </AbsoluteFill>
  );
};
