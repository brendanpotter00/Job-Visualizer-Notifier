export function fmtAge(seconds: number | null): string {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

export function fmtTs(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function fmtDurationMs(ms: number | null): string {
  if (ms == null) return "—";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function tickDuration(started: string, ended: string | null): string {
  if (!ended) return "running";
  const a = new Date(started).getTime();
  const b = new Date(ended).getTime();
  if (Number.isNaN(a) || Number.isNaN(b)) return "—";
  return `${((b - a) / 1000).toFixed(2)}s`;
}

export function fmtConfidence(c: number | null): string {
  return c == null ? "—" : c.toFixed(2);
}
