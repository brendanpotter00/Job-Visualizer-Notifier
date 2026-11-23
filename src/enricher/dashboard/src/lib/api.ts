// Shapes returned by the FastAPI dashboard API (src/job_enricher/dashboard.py).

export interface StageTimingAgg {
  stage: string;
  runs: number;
  avg_ms: number | null;
  items: number | null;
  retries: number | null;
}

export interface TickRow {
  id: number;
  uuid: string | null;
  started_at: string;
  ended_at: string | null;
  status: string;
  claimed: number;
  cleaned: number;
  classified: number;
  judged: number;
  corrected: number;
  needs_human: number;
  sent: number;
  errors: number;
  nulled_facets: number;
  notes: string | null;
}

export interface TickView extends TickRow {
  stage_timings: {
    stage: string;
    duration_ms: number;
    item_count: number;
    retry_count: number;
  }[];
  drift_suspected: boolean;
}

export interface Health {
  inbox: Record<string, number>;
  unsent: number;
  needs_human: number;
  failed_rows: number;
  last_heartbeat_at: string | null;
  last_heartbeat_age_s: number | null;
  stage_timings: StageTimingAgg[];
  classify_engine: string;
  classify_model: string;
  judge_engine: string;
  judge_model: string;
  opencode_model: string;
  latest_tick: TickRow | null;
}

export interface JobRow {
  source_id: string;
  job_listing_id: string;
  title: string;
  company: string;
  raw_location: string | null;
  status: string;
  claimed_at: string;
  category: string | null;
  level: string | null;
  classify_confidence: number | null;
  judged: number | null;
  judge_pass: number | null;
  needs_human: number;
  tick_id: number | null;
  enriched_at: string | null;
  sent_at: string | null;
}

export interface JobsResponse {
  jobs: JobRow[];
  total: number;
  limit: number;
  offset: number;
}

export type JobDetail = Record<string, unknown>;

export type KnobValue = string | number | boolean;

export interface KnobsResponse {
  snapshot: {
    classify_engine: string;
    classify_model: string;
    classify_batch_size: number;
    classify_fan_out: number;
    judge_enabled: boolean;
    judge_engine: string;
    judge_model: string;
    judge_human_floor: number;
    judge_scope: string;
    judge_confidence_ceiling: number;
    opencode_model: string;
    enrich_per_tick_limit: number;
  };
  meta: {
    models: string[];
    engines: string[];
    judge_scopes: string[];
    classify_batch_bounds: [number, number];
    classify_fanout_bounds: [number, number];
    enrich_per_tick_limit_bounds: [number, number];
    categories: string[];
    levels: string[];
    taxonomy_version: string | null;
  };
}

/** POST /api/knobs echoes only the fresh snapshot — no `meta` (unlike GET). */
export type KnobUpdateResponse = Pick<KnobsResponse, "snapshot">;

/** An HTTP error carrying the response status so callers can branch on it
 * (e.g. treat a 404 as "row vanished" while still surfacing 500s/network errors). */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message?: string) {
    super(message ?? String(status));
    this.name = "ApiError";
    this.status = status;
  }
}

const JSON_HEADERS = { "content-type": "application/json" };

/** Persist one knob; throws with the server's 400 detail on validation failure. */
export async function postKnob(key: string, value: KnobValue): Promise<KnobUpdateResponse> {
  const res = await fetch("/api/knobs", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ key, value }),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => b.detail as string)
      .catch(() => `${res.status}`);
    throw new Error(detail);
  }
  return res.json();
}

export async function fetchJobDetail(
  sourceId: string,
  jobListingId: string,
): Promise<JobDetail> {
  const qs = new URLSearchParams({
    source_id: sourceId,
    job_listing_id: jobListingId,
  });
  const res = await fetch(`/api/job?${qs}`);
  if (!res.ok) throw new ApiError(res.status);
  return res.json();
}
