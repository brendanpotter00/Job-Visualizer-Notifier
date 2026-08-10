import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import type { Job } from '../../types';
import type { BackendJobListing } from '../../api/types';
import { transformBackendJob } from '../../api/transformers/backendScraperTransformer';

/**
 * Arg for `addUserCompany`. `trackAnyway` is the single override for the
 * already-published checks: omitted (the default) the add stops and links to the
 * public company; `true` skips all three and creates the private copy.
 *
 * THE SERVER HONOURS IT ON EVERY CHECK. The UI only *offers* it on the guessed
 * `matchKind: 'name'` branch — on an exact board match a duplicate is strictly worse
 * for the user, so there is no button. That is a UI decision, not a server one: a
 * bookmarked or replayed request carrying the flag must still work rather than 500.
 *
 * Not sticky and not stored server-side — it is a property of one submit, so the
 * user is never silently opted out of the check on a later add.
 */
export interface AddUserCompanyArgs {
  url: string;
  trackAnyway?: boolean;
}

/**
 * Health lifecycle a stored user-company can be in. The wire value is a bare
 * `str` (backend-owned, may add codes), so display code narrows it and falls
 * back to raw text — see `companyHealth.ts`.
 *
 * `'discovering'` is the PROVISIONAL state a non-ATS board sits in between the
 * `202` add and the one-time capture discovery finishing (E7 capture
 * pivot): the row exists (so the list shows it as "Setting up…") but nothing is
 * scraped yet. The discovery task flips it to `'unverified'` (tracked) or
 * `'refused'`.
 */
export type UserCompanyHealthState =
  | 'discovering'
  | 'unverified'
  | 'healthy'
  | 'quarantined'
  | 'refused';

/**
 * The four steps a one-time discovery walks, in display order (E7 capture pivot).
 *
 * A CLOSED union on purpose, unlike `healthState`: the backend owns the vocabulary
 * (`api/services/discovery/progress.py`) and normalizes unknown keys away before they
 * reach the wire, so a rename there should be a compile error here — not a blank rung
 * in a checklist the user is reading to decide what to do next.
 */
export type DiscoveryStepKey =
  | 'open_page'
  | 'find_feed'
  | 'verify_read'
  | 'ready'
  // The FIFTH rung, and the only one a different run settles. Discovery ticks 1-4
  // and OPENS this one; the first harvest closes it. Before it existed the panel
  // went fully green while the row still read "0 open jobs" — every rung was true,
  // and the thing the user was actually waiting for had no rung at all.
  | 'first_scan';

/** Per-step state. `failed` lands on at most one step per run. */
export type DiscoveryStepStatus = 'pending' | 'active' | 'done' | 'failed';

/**
 * Terminal-ness of the whole run. `running` includes "queued but not started".
 *
 * `partial` is tracked-but-not-the-whole-board: the recipe reads a real slice of the
 * company's jobs and nothing more, because the board's own captured response proved
 * there is more than the recipe can reach (one department of a grouped payload, the tab
 * the page opened by itself, ten of forty-seven thousand). It is a SUCCESS — every job
 * we can see is refreshed daily and none is ever closed — but it is not the same
 * success as a board we read completely, and it used to render identically to one.
 */
export type DiscoveryOutcomeState = 'running' | 'tracking' | 'partial' | 'refused';

export interface DiscoveryStep {
  key: DiscoveryStepKey;
  status: DiscoveryStepStatus;
  /**
   * The SPECIFIC thing this step found ("found 3 candidate feeds", "read 90 jobs"), or
   * — on the failed step — why it stopped. Null while pending. A generic tick would be
   * a spinner with extra steps, which is what this replaced.
   */
  result: string | null;
}

/**
 * What happened to one recorded response, in the order the outcomes are decided.
 *
 * A closed union for the same reason `DiscoveryStepKey` is one — the backend owns the
 * vocabulary (`api/services/discovery/progress.py`) and normalizes anything else away
 * before it reaches the wire.
 */
export type DiscoveryRequestState =
  /** Seen and recorded. The ordinary case. */
  | 'recorded'
  /** Body over the capture's per-response ceiling, so it was never parsed. OUR limit. */
  | 'oversize'
  /** Job-shaped, but its address failed our outbound-safety check. */
  | 'blocked'
  /** The one we picked — and proved we can replay from our own servers. */
  | 'chosen';

/**
 * One JSON request the capture browser watched the careers page make.
 *
 * The evidence behind the verdict. A refusal saying "none of the 14 JSON requests this
 * page made returned a list of job postings" is an assertion with nothing attached;
 * these are the fourteen requests.
 *
 * `url` has already been redacted server-side — userinfo and port stripped, every query
 * VALUE replaced with an ellipsis — because a board that signs its URLs signs them in
 * the query. There are deliberately no headers, no cookies and no request body here.
 */
export interface DiscoveryRequest {
  method: string;
  url: string;
  status: number;
  /** Size of the response body, in bytes. The real size even when it was too big to keep. */
  bytes: number;
  /** Job-shaped records found in it. `null` = we have not looked yet; `0` = we looked. */
  records: number | null;
  state: DiscoveryRequestState;
  /** Why this row is what it is. Set on the chosen and blocked rows only. */
  note: string | null;
}

/** One record from the request we picked, pretty-printed — the "show me the JSON" bit. */
export interface DiscoveryPayloadSample {
  /** Where in the response the records live (`data.jobs`). */
  path: string;
  /** How many records the response held. */
  records: number;
  /** The pretty-printed record. Redacted and clipped server-side; render as-is. */
  text: string;
}

/**
 * The network log behind the checklist.
 *
 * `recorded` can exceed `requests.length`: the stored blob is clipped to a size budget
 * because every open tab re-downloads it every 4s while a discovery runs, and the
 * heading stays truthful about what we saw even when the list under it is shorter.
 */
export interface DiscoveryNetwork {
  requests: DiscoveryRequest[];
  recorded: number;
  sample: DiscoveryPayloadSample | null;
}

/**
 * The discovery checklist attached to a user company, when it has one.
 *
 * Rides the SAME `GET /api/users/companies` payload the list already polls — there is
 * deliberately no second polling channel. Absent (`undefined`) for every ATS company
 * and for anything discovered before this shipped.
 */
export interface DiscoveryProgress {
  /** Always all four steps, in order — the backend fills missing ones as `pending`. */
  steps: DiscoveryStep[];
  outcome: DiscoveryOutcomeState;
  /**
   * Hosted, iframe-embeddable view of the capture session. Only a Browserbase run has
   * one and our default is our own Chromium, so this is null on nearly every discovery
   * — the UI treats it as an optional extra and never blocks the checklist on it.
   */
  liveViewUrl: string | null;
  updatedAt: string | null;
  /**
   * What the capture browser actually saw — the requests, and which one we chose.
   *
   * Optional because a server that predates it simply omits the field; the backend
   * always sends it (possibly empty) once deployed. Empty means there is nothing to
   * show, which is a real state: a page that fetched no JSON at all recorded nothing.
   */
  network?: DiscoveryNetwork | null;
  // The wire also carries `job_preview` — the handful of jobs the acceptance replay
  // returned. It is deliberately NOT typed here: nothing renders it any more (the
  // "a few of the jobs we found" block was cut as noise), and an untyped extra field
  // on the response is free. The backend keeps sending it; re-add the type here if
  // something ever wants to show it again.
}

/**
 * "This looks like Spotify, which we already track" — a SUGGESTION, never a merge.
 *
 * Present once a board's first VERIFIED harvest found that its OPEN job titles overlap a
 * published company's by at least 70%, on sets of at least 20 titles each. It is the only
 * thing that catches the case the URL check cannot: `lifeatspotify.com` resolves to no
 * ATS at all, so nothing about the URL or the captured endpoint links it to `lever:spotify`
 * — only the job set does.
 *
 * WHAT IT DOES NOT MEAN: nothing was merged, moved or changed. The backend writes no job
 * row and touches no company's identity on this path — there is no un-merge in this
 * codebase, so a false merge would be permanent and silent while a false suggestion is one
 * dismissible banner. The user decides, and dismissing is a normal outcome.
 *
 * `companyId` is a PUBLIC company id (`spotify`), not a `u-…` runtime id, so it belongs on
 * `/companies?company=…` and never on `buildMyCompanyDetailPath`.
 */
export interface PublicBoardMatch {
  companyId: string;
  displayName: string;
  /** Normalized titles the two boards share — the "70" in "70 of 81 roles match". */
  shared: number;
  /** Distinct normalized OPEN titles on THIS board — the "81". */
  candidateTitles: number;
  /** When the comparison ran. Null on a blob written without one. */
  detectedAt: string | null;
}

/**
 * A company the signed-in user brought themselves — one row of
 * `GET /api/users/companies`, and the body of a successful add. camelCase on
 * the wire (backend `to_camel`).
 */
export interface UserCompany {
  /** `u-<10 base36>` runtime id. NOT a compile-time `COMPANY_IDS` member. */
  id: string;
  displayName: string;
  /** Bare `str` on the wire — backend-owned, so a new provider is not a type error. */
  ats: string;
  boardToken: string;
  /** `custom:<id>` — per-company job namespace. */
  sourceId: string;
  /** See `UserCompanyHealthState`; typed wide because the server owns the list. */
  healthState: string;
  openJobCount: number;
  /** ISO-8601 of the last successful harvest, or null before the first run. */
  lastSuccessAt: string | null;
  /**
   * ISO-8601 of the first VERIFIED harvest (E7 Phase 2), or null until the
   * company graduates. Carried on the wire ahead of any consumer: the trend
   * page's "already live when tracking began" line is still derived from the
   * `firstSeenAt` seed-window heuristic, not from this field.
   */
  trackingStartedAt: string | null;
  /**
   * The 4-step discovery checklist. Optional because it exists only for a discovered
   * (non-ATS) board — and because a server that predates it simply omits the field.
   */
  discovery?: DiscoveryProgress | null;
  /**
   * The published-board suggestion, if this board's first VERIFIED harvest found one.
   * Optional AND nullable: absent from a server that predates it, null on the
   * overwhelming majority of rows, and both render nothing.
   */
  publicMatch?: PublicBoardMatch | null;
}

/**
 * How many companies the signed-in user may still add this calendar month.
 *
 * 20 URLs per user per month, resetting at midnight UTC on the 1st. Every submission
 * the server ACTS on spends a slot — a success, a board it read and refused, and a
 * board that turns out to be one we already publish — and deleting a company does not
 * give one back. A URL it could not read at all (a bad scheme, a private address, a
 * dead domain) costs nothing: see `add_quota.py`, which owns that exception.
 *
 * `limit` is the configured cap and means exactly what it says: the number of adds
 * allowed this month. **`0` allows none** — it is a kill switch, not an "unlimited"
 * sentinel. There is no `remaining` on the wire, by design: see {@link addsRemaining},
 * the single definition of that arithmetic anywhere.
 *
 * Optional on {@link GetUserCompaniesResponse} because the server omits it in two
 * cases, and both mean "no cap in force": the caller is an **admin**, who is exempt
 * from the cap entirely (`add_quota.quota_response`), or the server predates the
 * counter. The UI renders nothing and disables nothing for either — it never guesses a
 * number. Absence is a different thing from `limit: 0`, which is a cap that IS in
 * force and allows none.
 */
export interface AddQuota {
  /** Submissions recorded this UTC calendar month. */
  used: number;
  /** The cap. `0` allows no adds at all — it is not "unlimited". */
  limit: number;
  /** ISO-8601 start of the next UTC month — when `used` goes back to 0. */
  resetsAt: string;
}

/**
 * Slots left, floored at 0. Returns `null` for exactly one INPUT: no quota on the
 * payload at all. The server sends none to an admin (exempt from the cap) and none
 * from a build that predates the counter — "no cap in force" and "we don't know" want
 * the same rendering, which is why one absence covers both. The caller renders no
 * counter and disables nothing; the server still refuses over quota regardless of what
 * the button does. Locking a user out of the whole feature on a missing field would be
 * the worst possible reading of it.
 *
 * `null` and `0` ARE NOT THE SAME THING and must never be collapsed. `limit: 0` is a
 * cap that is in force and fully spent, so it returns `0` — the counter renders and the
 * submit disables. (It used to return `null` here, because `0` meant unlimited. It
 * doesn't any more: the number is the number of adds allowed.)
 *
 * THE ONLY definition of this arithmetic — the backend deliberately has none (it only
 * ever asks "is it exhausted?"). The counter copy and the "is the submit disabled?"
 * check must never be able to disagree, which is exactly what two inline
 * `limit - used` expressions would allow.
 */
export function addsRemaining(quota: AddQuota | null | undefined): number | null {
  if (!quota) return null;
  return Math.max(quota.limit - quota.used, 0);
}

/**
 * `GET /api/users/companies` envelope — newest first.
 *
 * The slice deliberately does NOT unwrap this to a bare `UserCompany[]` any more.
 * `quota` rides the same payload because the Add Companies page already fetches and
 * polls this endpoint, so the counter costs no extra request, is refreshed by the
 * same `MyCompanies` tag every add and delete already invalidates, and can never go
 * stale against the list it is rendered above.
 */
export interface GetUserCompaniesResponse {
  companies: UserCompany[];
  quota?: AddQuota | null;
}

/** Arg for the owner-scoped jobs + delete endpoints. */
export interface UserCompanyIdArg {
  id: string;
}

/** Arg for the rename mutation. */
export interface RenameUserCompanyArgs {
  id: string;
  displayName: string;
}

/**
 * How long a company name may be, enforced identically on both sides.
 *
 * The server is the authority (`_DISPLAY_NAME_MAX_LENGTH` in
 * `routers/user_companies.py`) and rejects an over-long name with
 * `reason: 'name_too_long'`. This copy exists so the input can stop the user at the
 * boundary rather than letting them type a paragraph and then explaining it — and it
 * is the same 100 the account-page display name already uses, not a new number.
 */
export const COMPANY_NAME_MAX_LENGTH = 100;

/**
 * The 422 body when a rename is rejected: `name_empty` or `name_too_long`.
 *
 * Same flat `{ reason, detail }` shape as the add failure, and 422 for the same
 * load-bearing reason — the UI's narrowers hard-check the status before they will
 * read a `reason`, so any other 4xx loses the explanation.
 */
export interface RenameUserCompanyFailure {
  reason: string;
  detail: string;
}

const RENAME_FAILURE_REASONS = ['name_empty', 'name_too_long'] as const;

type RenameFailureReason = (typeof RENAME_FAILURE_REASONS)[number];

/**
 * One line of copy per code the rename endpoint can return.
 *
 * A `Record` over the closed union, exactly like `ADD_REASON_TITLES` and
 * `REASON_COPY`: a code added to the union without copy is a compile error rather
 * than a blank alert. The server's `detail` is preferred when it sends one; this is
 * the floor.
 */
const RENAME_REASON_COPY: Record<RenameFailureReason, string> = {
  name_empty: "A company name can't be blank.",
  name_too_long: `Keep the name to ${COMPANY_NAME_MAX_LENGTH} characters or fewer.`,
};

/**
 * The rename endpoint's own 422, or `null` for anything else.
 *
 * `status !== 422` is a hard check for the same reason `asAddFailure` makes it: only
 * that status carries the flat `{ reason, detail }` body. A 404, a 429 or a network
 * error falls through to {@link describeRenameError}'s generic branch.
 */
export function asRenameFailure(error: unknown): RenameUserCompanyFailure | null {
  if (typeof error !== 'object' || error === null) return null;
  if ((error as { status?: unknown }).status !== 422) return null;
  const data = (error as { data?: unknown }).data;
  if (typeof data !== 'object' || data === null) return null;
  const reason = (data as { reason?: unknown }).reason;
  if (typeof reason !== 'string') return null;
  const detail = (data as { detail?: unknown }).detail;
  return { reason, detail: typeof detail === 'string' ? detail : '' };
}

/**
 * One short sentence for any rename failure — never empty, never `[object Object]`.
 *
 * The card renders this inline under the field, so it has to be one line and it has
 * to always say something. The four cases the feature can actually produce (too long,
 * empty, not found, not yours) are all named; everything else gets the generic line.
 */
export function describeRenameError(error: unknown): string {
  const failure = asRenameFailure(error);
  if (failure) {
    const known = (RENAME_FAILURE_REASONS as readonly string[]).includes(failure.reason)
      ? (failure.reason as RenameFailureReason)
      : null;
    if (known) return failure.detail || RENAME_REASON_COPY[known];
    // An unknown 422 code: the server still sent a sentence, so use it.
    if (failure.detail) return failure.detail;
  }
  const status = (error as { status?: unknown } | null)?.status;
  // 404 is "not yours" and "no longer there" at once — the endpoint deliberately does
  // not distinguish them, so neither does this. Either way the list is about to
  // refresh and the row will tell the truth.
  if (status === 404) return "That company isn't in your list any more.";
  if (status === 401 || status === 403) return 'Please sign in again to rename this.';
  if (status === 429) return "You're renaming too quickly. Try again in a moment.";
  if (status === 503) return 'Renaming is unavailable right now.';
  return "That didn't save. Please try again.";
}

/**
 * The 422 body when an add is rejected. Distinct from the *resolver's* flat 422
 * (`ResolveUrlFailure`): the add failure carries a human `detail` and the
 * `finalUrl` that was probed. `reason` is one of
 * `unsupported | probe_failed | empty | deadline_exceeded | no_ats_detected`,
 * typed as `string` because the server owns the code list.
 */
export interface AddUserCompanyFailure {
  reason: string;
  detail: string;
  finalUrl: string;
}

/**
 * The `reason` on the 422 the add endpoint returns when the caller has spent every
 * add of the current calendar month.
 *
 * 422 rather than 403 is load-bearing on this side: the UI's `asAddFailure` hard-checks
 * `status !== 422` before it will read a `reason` at all, so a 403 would fall through
 * to generic copy and the explanation would be lost.
 */
export const MONTHLY_LIMIT_REASON = 'monthly_limit_reached';

/**
 * True when an RTK Query rejection is the monthly-cap refusal.
 *
 * Exists so error UI can avoid giving advice that does not apply — "paste a supported
 * board instead" is actively wrong when the board was never the problem.
 */
export function isMonthlyLimitError(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false;
  if ((error as { status?: unknown }).status !== 422) return false;
  const data = (error as { data?: unknown }).data;
  if (typeof data !== 'object' || data === null) return false;
  return (data as { reason?: unknown }).reason === MONTHLY_LIMIT_REASON;
}

/**
 * The `202 Accepted` body when a non-ATS URL is handed to one-time discovery
 * (E7 Phase 3b). The board isn't tracked yet — a background agent is teaching
 * itself to read it, and the company surfaces in the list after the first scan
 * (or as a `refused` health badge if it can't be tracked). Distinct from the
 * `UserCompany` success body by its `status` discriminant.
 */
export interface DiscoveryPendingResponse {
  status: 'discovery_pending';
  detail: string;
  finalUrl?: string;
  /**
   * The provisional row's runtime id (and its `custom:<id>` namespace). Without these
   * the caller could only find the board it just added by diffing the list, so the
   * "one-time setup" notice could never point at the row now narrating its own
   * progress. Optional — a server that predates the checklist omits them.
   */
  id?: string;
  sourceId?: string;
}

/**
 * How sure the backend is, and therefore what the UI is allowed to offer.
 *
 * `'board'` — we matched a BOARD: the `(ats, boardToken)` pair the resolver named, or a
 * careers host in the backend's own declared table. Exact evidence, so the notice is
 * TERMINAL — there is no plausible reading where the user meant a different company, and
 * offering a private duplicate of a board we already publish is strictly worse for them
 * (it re-scrapes the same feed and its history starts today).
 *
 * `'name'` — we matched the company NAME inside the domain (`lifeatspotify.com` →
 * Spotify). No board was resolved and no job set was compared. It is a good guess and it
 * is still a guess, so this one keeps a way out: a wrong guess with no way out would
 * hard-block somebody from adding a legitimately different company with no way to tell us
 * we got it wrong.
 *
 * Optional because the field is newer than the shape; absent means `'board'`, which is
 * the stricter reading and therefore the safe default.
 */
export type AlreadyPublicMatchKind = 'board' | 'name';

/**
 * The `200` body when the pasted URL is a company we ALREADY PUBLISH.
 *
 * Nothing was created — no private company, no scraper, no jobs — and nothing failed
 * either, which is why this arrives as a `200` body rather than an error. The user
 * asked for a company and it is already there; the UI's job is to hand them the link.
 *
 * `companyId` is a PUBLIC company id (`spotify`), not a `u-…` runtime id, so it belongs
 * on `/companies?company=…` and never on `buildMyCompanyDetailPath`.
 *
 * WHAT THIS DOES NOT MEAN: we compared job sets. We did not. Three different server-side
 * checks produce this body and none of them looks at a single job:
 *  - the URL resolved to the same ATS board (`ats` + `boardToken`) we already read;
 *  - the URL's HOST is one of the five script-scraped careers boards (Amazon, Apple,
 *    Google, Microsoft, TikTok), which have no ATS pair for the first check to compare; or
 *  - the URL's registrable DOMAIN names a company we publish (`lifeatspotify.com`).
 *
 * `matchKind` separates the first two (exact, `'board'`) from the third (a guess,
 * `'name'`) — see {@link AlreadyPublicMatchKind}. It is what stops a string match in a
 * web address from reading, and behaving, like a resolved board identifier.
 *
 * What still reaches discovery: a careers site whose domain does not name the company at
 * all. Only the job SET links those, and `published_board_match` suggests that after the
 * first harvest.
 */
export interface AlreadyPublicResponse {
  status: 'already_public';
  detail: string;
  companyId: string;
  displayName: string;
  /** What the resolver settled on — re-send this to track a private copy anyway. */
  finalUrl: string;
  matchKind?: AlreadyPublicMatchKind;
}

/** True only for the weaker, guessed match — the one branch that keeps a way out. */
export function isNameGuessMatch(result: AlreadyPublicResponse): boolean {
  return result.matchKind === 'name';
}

/**
 * `addUserCompany` resolves to a tracked `UserCompany` (201/200, ATS boards or an
 * idempotent re-add), a `DiscoveryPendingResponse` (202, a non-ATS URL routed to
 * one-time discovery), or an `AlreadyPublicResponse` (200, a board we already publish).
 * Consumers discriminate with {@link isDiscoveryPending} / {@link isAlreadyPublic}.
 */
export type AddUserCompanyResult =
  | UserCompany
  | DiscoveryPendingResponse
  | AlreadyPublicResponse;

export function isDiscoveryPending(
  result: AddUserCompanyResult,
): result is DiscoveryPendingResponse {
  return (result as DiscoveryPendingResponse).status === 'discovery_pending';
}

export function isAlreadyPublic(
  result: AddUserCompanyResult,
): result is AlreadyPublicResponse {
  return (result as AlreadyPublicResponse).status === 'already_public';
}

interface UserCompaniesApiExtra {
  getTokenOrNull: () => Promise<string | null>;
}


export const userCompaniesApi = createApi({
  reducerPath: 'userCompaniesApi',
  baseQuery: fetchBaseQuery({
    // `/api` and NOT `/api/users/companies` on purpose. This slice owns the whole
    // "companies the user brings themselves" surface, and its endpoints sit under
    // more than one path prefix — pinning the base any deeper would force the next
    // one to escape it with `../`.
    baseUrl: '/api',
    prepareHeaders: async (headers, { extra }) => {
      const { getTokenOrNull } = extra as UserCompaniesApiExtra;
      const token = await getTokenOrNull();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      return headers;
    },
  }),
  // The `users/companies` list is real server state, so the slice owns one tag.
  // Per-company job caches tag `{ type: 'MyCompanies', id }`; the list tags the bare
  // type, and add / remove invalidate the bare type (which sweeps both the list and
  // per-id job caches). One tag type keeps the invalidation graph trivial.
  tagTypes: ['MyCompanies'],
  endpoints: (builder) => ({
    /**
     * The caller's own companies, newest first, plus their monthly add quota.
     *
     * The envelope is kept whole rather than unwrapped to a bare array: `quota`
     * lives beside `companies` on the wire, and unwrapping would drop it. Consumers
     * read `data?.companies`.
     */
    getUserCompanies: builder.query<GetUserCompaniesResponse, void>({
      query: () => 'users/companies',
      providesTags: ['MyCompanies'],
    }),

    /**
     * Add a company from an already-resolved final URL. On `201` (created) or
     * an idempotent `200` (already owned) the body is the `UserCompany`; on `202`
     * a non-ATS URL was routed to one-time discovery and the body is a
     * `DiscoveryPendingResponse` (discriminate with `isDiscoveryPending`); on a
     * `200` naming a board we already publish the body is an
     * `AlreadyPublicResponse` and NOTHING was created (`isAlreadyPublic`); a `422`
     * surfaces `AddUserCompanyFailure` in `error.data` for the UI to explain.
     */
    addUserCompany: builder.mutation<AddUserCompanyResult, AddUserCompanyArgs>({
      // `trackAnyway` is omitted from the body unless it is actually set: the
      // backend model is `extra='forbid'`, so only send fields we mean, and an
      // absent field is exactly the default the server already applies.
      query: ({ url, trackAnyway }) => ({
        url: 'users/companies',
        method: 'POST',
        body: trackAnyway ? { url, trackAnyway } : { url },
      }),
      invalidatesTags: ['MyCompanies'],
    }),

    /**
     * Give one of the caller's own boards a new name (`200` with the updated row).
     *
     * `404` covers not-yours, not-found and not-a-private-board alike — the same
     * answer `DELETE` gives, so the response cannot be used to probe which company
     * ids exist. `422` carries `{ reason, detail }` (`name_empty` / `name_too_long`),
     * read by {@link asRenameFailure}.
     *
     * Invalidate rather than optimistically patch. The response IS the updated row,
     * so the refetch is a formality — but the list is also polled, carries `quota`
     * and can be reordered by an add landing in the same window, and a hand-rolled
     * optimistic patch would have to keep all of that consistent to save one request
     * the page was already making on a timer. The card holds a pending state for the
     * one round trip, which is also the only shape that cannot show a rename as
     * saved and then take it back.
     */
    renameUserCompany: builder.mutation<UserCompany, RenameUserCompanyArgs>({
      query: ({ id, displayName }) => ({
        url: `users/companies/${id}`,
        method: 'PATCH',
        body: { displayName },
      }),
      invalidatesTags: ['MyCompanies'],
    }),

    /** Drop the caller's ownership of a company (`204`; `404` if not owned). */
    removeUserCompany: builder.mutation<void, string>({
      query: (id) => ({
        url: `users/companies/${id}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['MyCompanies'],
    }),

    /**
     * Owner-scoped jobs for one custom company (`403` if the caller is not an
     * owner). The response is the SAME shape `/api/jobs` returns, so it runs
     * through the exact transform the backend-scraper client uses
     * (`transformBackendJob`) — the mapping is never duplicated here. Emits the
     * frontend `Job[]` (camelCase, with `firstSeenAt`) the trend page needs.
     */
    getUserCompanyJobs: builder.query<Job[], UserCompanyIdArg>({
      query: ({ id }) => `users/companies/${id}/jobs`,
      transformResponse: (rows: BackendJobListing[], _meta, { id }) =>
        rows.map((row) => transformBackendJob(row, id)),
      providesTags: (_result, _error, { id }) => [{ type: 'MyCompanies', id }],
    }),
  }),
});

export const {
  useGetUserCompaniesQuery,
  useAddUserCompanyMutation,
  useRenameUserCompanyMutation,
  useRemoveUserCompanyMutation,
  useGetUserCompanyJobsQuery,
} = userCompaniesApi;
