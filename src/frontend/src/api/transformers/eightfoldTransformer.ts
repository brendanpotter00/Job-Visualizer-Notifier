import type { Job } from '../../types';
import type { EightfoldJobPosition } from '../types';

/**
 * Transforms an Eightfold AI position into the normalized Job model
 *
 * Key mapping decisions (verified via live API on 2026-04-18):
 * - `id`: prefer numeric `id`, then `ats_job_id`, then `display_job_id`
 * - `createdAt`: `t_create` is unix *seconds* (multiply by 1000); fall back to `t_update`, then `now`
 * - `location`: comma-delimited without spaces — split, trim, rejoin with ", "
 * - `isRemote`: true only when `work_location_option === "remote"`
 * - `isPrivate` filtering happens in the client, NOT the transformer
 *
 * @param raw - Raw Eightfold position from API
 * @param companyId - Internal company identifier (e.g., "netflix")
 * @returns Normalized Job object
 */
export function transformEightfoldJob(
  raw: EightfoldJobPosition,
  companyId: string
): Job {
  // Prefer numeric id; fall back to ats/display job ids
  const idSource =
    raw.id !== undefined && raw.id !== null
      ? raw.id
      : raw.ats_job_id || raw.display_job_id || '';
  const id = String(idSource);

  // Eightfold encodes location as "City,State,Country" (no spaces).
  // Normalise to "City, State, Country" for display consistency.
  const rawLocation = raw.location || raw.locations?.[0];
  const location = rawLocation
    ? rawLocation
        .split(',')
        .map((segment) => segment.trim())
        .filter(Boolean)
        .join(', ')
    : undefined;

  // Department is optional and may be null — coerce to undefined
  const department = raw.department || undefined;

  // t_create and t_update are unix epoch SECONDS (not milliseconds).
  // Prefer t_create (original post time) over t_update.
  const unixSeconds = raw.t_create ?? raw.t_update;
  const createdAt =
    typeof unixSeconds === 'number'
      ? new Date(unixSeconds * 1000).toISOString()
      : new Date().toISOString();

  // Only "remote" counts as remote. "hybrid" and "onsite" (and null) → false.
  const isRemote = raw.work_location_option === 'remote';

  // Surface the requisition id as a tag so it's discoverable in the UI.
  const reqId = raw.display_job_id || raw.ats_job_id;
  const tags = reqId ? [reqId] : undefined;

  return {
    id,
    source: 'eightfold' as const,
    company: companyId,
    title: raw.name,
    department,
    location,
    isRemote,
    createdAt,
    url: raw.canonicalPositionUrl ?? '',
    tags,
    raw,
  };
}
