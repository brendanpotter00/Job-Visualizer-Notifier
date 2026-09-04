/**
 * Smooth open path through the points: quadratic segments aimed at successive
 * midpoints (the standard sparkline-smoothing trick), so the line bends gently
 * instead of reading as a jagged chart.
 */
export function buildSmoothPath(points: ReadonlyArray<readonly [number, number]>): string {
  if (points.length < 2) return '';
  const [first, ...rest] = points;
  const segments: string[] = [`M ${first[0]} ${first[1]}`];
  for (let i = 0; i < rest.length - 1; i += 1) {
    const control = rest[i];
    const next = rest[i + 1];
    const midX = (control[0] + next[0]) / 2;
    const midY = (control[1] + next[1]) / 2;
    segments.push(`Q ${control[0]} ${control[1]} ${midX} ${midY}`);
  }
  const last = rest[rest.length - 1];
  segments.push(`L ${last[0]} ${last[1]}`);
  return segments.join(' ');
}
