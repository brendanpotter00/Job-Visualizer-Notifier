/**
 * Translates a failed add into display copy, for every failure that is about the URL
 * rather than about a board.
 *
 * It was written for `resolveCareersUrl`, which the Add Companies page no longer calls —
 * one press now goes straight to `addUserCompany`. The codes below did not move with it:
 * the add endpoint runs the SAME resolver and hands back the same `reason` values, so
 * this is still the single owner of their copy. `AddCompanyOutcome` tries the add
 * endpoint's own six codes first and falls through to `describeResolveError` for
 * everything else — including 401 / 429 / 502 / 503 and RTK Query's non-HTTP statuses,
 * which used to be answered by the resolve call.
 *
 * Pure and dependency-free so the whole matrix of failure shapes is testable
 * without a store, a component, or a network. The hard requirement this module
 * exists to satisfy: never render `[object Object]`, `undefined`, or a bare
 * status number at the user. Every branch produces a non-empty title AND a
 * non-empty detail, and anything unrecognized still surfaces enough raw
 * material (status, reason code) to be diagnosable from a screenshot.
 */

/** The resolver's stable, machine-readable failure codes (backend-owned). */
export const RESOLVE_FAILURE_REASONS = [
  'no_ats_detected',
  'scheme_not_https',
  'userinfo_present',
  'non_standard_port',
  'invalid_hostname',
  'dns_resolution_failed',
  'resolves_to_private_address',
  'not_an_allowed_ats_api_host',
  'too_many_redirects',
  'cross_host_redirect',
  'fetch_failed',
  'deadline_exceeded',
  'unexpected_content_encoding',
] as const;

export type ResolveFailureReason = (typeof RESOLVE_FAILURE_REASONS)[number];

export interface ResolveErrorDisplay {
  /** Short headline. Always non-empty. */
  title: string;
  /** One or two sentences of explanation plus, where possible, what to do next. Always non-empty. */
  detail: string;
  /**
   * The raw backend `reason` code, when the failure carried one. Present for
   * unknown/future codes too — that is the whole point of keeping it.
   */
  reasonCode?: string;
}

/**
 * Human-facing job boards we can read directly, no discovery required. Named in the
 * `no_ats_detected` copy — and exported because the discovery panel needs the same
 * list when a one-time setup fails: "paste a link to one of these instead" is the
 * only actionable thing left to tell the user at that point, and two hand-maintained
 * copies of the list would drift the moment a provider is added.
 */
export const SUPPORTED_BOARDS = 'Greenhouse, Ashby, Lever, Gem, Workday, and Eightfold';

/**
 * Copy for every known `reason`. Keyed by the closed union so adding a code to
 * `RESOLVE_FAILURE_REASONS` without writing copy for it is a compile error.
 */
const REASON_COPY: Record<ResolveFailureReason, { title: string; detail: string }> = {
  no_ats_detected: {
    title: "We couldn't find a job board there",
    detail:
      `That page didn't lead to a job board we support. We currently read ${SUPPORTED_BOARDS}. ` +
      'Marketing careers pages often hide the real board behind a "See open roles" button — ' +
      'try clicking through to the actual job listings and pasting that address instead.',
  },
  scheme_not_https: {
    title: 'The address must use HTTPS',
    detail:
      'Only https:// URLs can be checked. Re-enter the address starting with https:// and try again.',
  },
  userinfo_present: {
    title: 'Remove the login details from the address',
    detail:
      'That URL has a username or password embedded in it (the "user@" part before the domain), ' +
      'which we refuse to send anywhere. Paste the plain address without it.',
  },
  non_standard_port: {
    title: 'That address uses an unsupported port',
    detail:
      'The URL points at a non-standard port. Only the default HTTPS port (443) is allowed, ' +
      'so drop the ":1234" style suffix from the address.',
  },
  invalid_hostname: {
    // Covers three server-side rejections, not just malformed input: an
    // unreadable hostname, a bare IP literal (banned before DNS even runs), and
    // names like `localhost`. Pasting `https://192.168.1.1/careers` lands here,
    // so copy that only mentioned typos read as wrong — the address looked
    // perfectly well-formed to the person who typed it.
    title: "We can't use that address",
    detail:
      "We couldn't read a valid public hostname out of that URL. Use a domain name rather than " +
      'a raw IP address, and make sure it looks like https://example.com/careers.',
  },
  dns_resolution_failed: {
    title: "That domain couldn't be found",
    detail:
      "The DNS lookup for that hostname failed, so there was nothing for us to connect to. " +
      'Double-check the spelling — or the domain may no longer exist.',
  },
  resolves_to_private_address: {
    title: 'That address points inside a private network',
    detail:
      'The hostname resolves to a private or internal IP address — something like localhost, ' +
      '127.0.0.1, or a 10.x / 192.168.x range — which we will not fetch. Only publicly ' +
      'reachable careers pages can be checked.',
  },
  not_an_allowed_ats_api_host: {
    title: 'That host is not an allowed job board',
    detail:
      "The address resolved to a host that isn't on our list of permitted job-board APIs. " +
      'This usually means the link goes somewhere other than a supported ATS.',
  },
  too_many_redirects: {
    title: 'That link redirected too many times',
    detail:
      'The URL bounced through more redirects than we follow. Open it in your browser, let it ' +
      'settle, and paste the address you actually land on.',
  },
  cross_host_redirect: {
    title: 'That link redirected to a different site',
    detail:
      "The URL redirected to another host, which we don't follow at this step. Open the link in " +
      'your browser and paste the final address instead.',
  },
  fetch_failed: {
    title: "We couldn't load that page",
    detail:
      'The request failed before we could read anything back. The site may be down, may be ' +
      'blocking automated requests, or may simply have hiccuped. Trying again often works.',
  },
  deadline_exceeded: {
    title: 'That page took too long to respond',
    detail:
      'We gave up waiting before the page finished loading. Try again, or paste a more direct ' +
      'link to the job listings so there are fewer pages for us to follow.',
  },
  unexpected_content_encoding: {
    title: "We couldn't read that page's response",
    detail:
      'The server sent the page back in a content encoding we do not accept, so there was ' +
      'nothing we could inspect. Try the direct job-board URL instead.',
  },
};

const KNOWN_REASONS = new Set<string>(RESOLVE_FAILURE_REASONS);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** Narrows a wire `reason` to the closed union, or `null` for anything new. */
function asKnownReason(reason: string): ResolveFailureReason | null {
  return KNOWN_REASONS.has(reason) ? (reason as ResolveFailureReason) : null;
}

/**
 * Reads `detail` when the backend used FastAPI's default `{"detail": "..."}`
 * envelope (401 / 429 / 503 all do). Returns null when absent or not a string,
 * so callers can fall back to their own copy instead of printing `undefined`.
 */
function stringDetail(data: unknown): string | null {
  if (!isRecord(data)) return null;
  const detail = data.detail;
  return typeof detail === 'string' && detail.trim().length > 0 ? detail : null;
}

/**
 * True for FastAPI's *request-validation* 422, which is a completely different
 * shape from the resolver's flat 422: `{"detail": [{loc, msg, type}, ...]}`
 * with no `reason` key. Empty url, over-2048-char url, and a misspelled field
 * all land here.
 */
function isValidationErrorBody(data: unknown): boolean {
  return isRecord(data) && Array.isArray(data.detail);
}

/** Pulls the first readable `msg` out of a FastAPI validation-error array. */
function firstValidationMessage(data: unknown): string | null {
  if (!isRecord(data) || !Array.isArray(data.detail)) return null;
  for (const entry of data.detail) {
    if (isRecord(entry) && typeof entry.msg === 'string' && entry.msg.trim().length > 0) {
      return entry.msg;
    }
  }
  return null;
}

function describeResolverFailure(data: Record<string, unknown>): ResolveErrorDisplay {
  const reason = String(data.reason);
  const known = asKnownReason(reason);
  if (known) {
    return { ...REASON_COPY[known], reasonCode: reason };
  }
  // An unknown code means this build is older than the server. Say so honestly
  // and print the code — a screenshot then contains everything needed to fix it.
  return {
    title: "We couldn't check that URL",
    detail:
      `The server rejected it for a reason this version of the app doesn't recognize yet ` +
      `(code: ${reason}). Updating the page may help; otherwise this is worth reporting.`,
    reasonCode: reason,
  };
}

/**
 * Maps any rejection from `addUserCompany` (or `resolveCareersUrl`) to display copy.
 *
 * Accepts `unknown` because callers get either an RTK Query
 * `FetchBaseQueryError`, a `SerializedError`, or (from `.unwrap()`) a thrown
 * value — and pinning the parameter to one of those would just push the
 * casting out to every call site.
 */
export function describeResolveError(error: unknown): ResolveErrorDisplay {
  if (error == null) {
    return {
      title: "We couldn't check that URL",
      detail: 'The request failed, but no error information came back. Please try again.',
    };
  }

  if (!isRecord(error) || !('status' in error)) {
    // A SerializedError (thrown inside the pipeline) or something else entirely.
    const message = isRecord(error) && typeof error.message === 'string' ? error.message : null;
    return {
      title: 'Something went wrong',
      detail: message
        ? `The check failed before it reached the server: ${message}`
        : 'The check failed before it reached the server. Please try again.',
    };
  }

  const { status } = error as { status: unknown };
  const data = (error as { data?: unknown }).data;

  // ── Non-HTTP RTK Query statuses ────────────────────────────────────────
  if (status === 'FETCH_ERROR') {
    return {
      title: "We couldn't reach the server",
      detail:
        'The request never completed — you may be offline, or the API may be unreachable. ' +
        'Check your connection and try again.',
    };
  }
  if (status === 'TIMEOUT_ERROR') {
    return {
      title: 'The request timed out',
      detail: 'The server took too long to answer. Please try again in a moment.',
    };
  }
  if (status === 'PARSING_ERROR') {
    return {
      title: "We couldn't read the server's response",
      detail:
        'The server replied with something that was not valid JSON. This is a bug on our side ' +
        'rather than a problem with your URL.',
    };
  }
  if (status === 'CUSTOM_ERROR') {
    const message = typeof (error as { error?: unknown }).error === 'string'
      ? (error as { error: string }).error
      : null;
    return {
      title: 'Something went wrong',
      detail: message ?? 'The request failed for an unexpected reason. Please try again.',
    };
  }

  // ── HTTP statuses ──────────────────────────────────────────────────────
  switch (status) {
    case 401:
      return {
        title: 'Please sign in again',
        detail:
          'Your session is no longer valid, so the server rejected the request. Sign out and ' +
          'back in, then retry.',
      };

    case 429:
      // The server may send a Retry-After header, but RTK Query's
      // FetchBaseQueryError does not expose response headers, so we quote the
      // documented limit rather than inventing a countdown we cannot measure.
      return {
        title: "You're checking URLs too quickly",
        detail:
          'This is limited to 10 checks per minute. Wait about a minute and try again.',
      };

    case 503:
      return {
        title: 'This feature is turned off on the server',
        detail:
          'The backend has custom company sources disabled. The server-side flag is separate ' +
          'from the one that revealed this page, so both have to be on before a URL can be ' +
          'checked.',
      };

    case 502:
      // Shape comes from api/companies.ts (the Vercel proxy), not the backend:
      // `{ error, details }`. Usually means the backend isn't running locally.
      return {
        title: "We couldn't reach the backend",
        detail: (() => {
          const details = isRecord(data) && typeof data.details === 'string' ? data.details : null;
          const base =
            'The API gateway could not contact the backend service. If you are running this ' +
            'locally, check that the backend is up.';
          return details ? `${base} (${details})` : base;
        })(),
      };

    case 422: {
      // Two entirely different bodies arrive with this status.
      if (isRecord(data) && typeof data.reason === 'string') {
        return describeResolverFailure(data);
      }
      if (isValidationErrorBody(data)) {
        const msg = firstValidationMessage(data);
        return {
          title: "That doesn't look like a valid URL",
          detail: msg
            ? `The address was rejected before it was checked: ${msg}`
            : 'The address was rejected before it was checked. Enter a full URL of up to 2048 ' +
              'characters, for example https://example.com/careers.',
        };
      }
      // 422 with a shape we have never seen.
      return {
        title: "We couldn't check that URL",
        detail:
          stringDetail(data) ??
          'The server rejected the address but did not say why. Double-check the URL and try again.',
      };
    }

    default: {
      const detail = stringDetail(data);
      const statusText = typeof status === 'number' ? `HTTP ${status}` : String(status);
      return {
        title: 'Something went wrong',
        detail: detail
          ? `${detail} (${statusText})`
          : `The server responded with an unexpected error (${statusText}). Please try again.`,
      };
    }
  }
}
