/**
 * Extracts a human-readable error message from an unknown error value.
 *
 * Handles (in priority order):
 *   1. `Error` instances → `err.message`
 *   2. string errors → the string as-is
 *   3. RTK Query shape `{ data: string | { detail?: string; message?: string } }`
 *      → `data.detail`, `data.message`, or `data` (string) — first non-empty wins
 *   4. Generic `{ message: string }` objects → `err.message`
 *   5. Anything else (including `null` / `undefined`) → `fallback`
 *
 * This utility consolidates the `err instanceof Error ? err.message : '...'`
 * boilerplate and the RTK Query `'data' in err` decode that previously lived
 * inline at call sites.
 *
 * @param err - The unknown error value to decode
 * @param fallback - Message returned when no branch matches. Defaults to `'Unknown error'`.
 * @returns A non-empty string suitable for display to the user.
 */
export function extractErrorMessage(err: unknown, fallback: string = 'Unknown error'): string {
  if (err == null) {
    return fallback;
  }

  if (err instanceof Error) {
    return err.message || fallback;
  }

  if (typeof err === 'string') {
    return err;
  }

  if (typeof err === 'object') {
    // RTK Query shape: { data: ... }
    if ('data' in err) {
      const data = (err as { data: unknown }).data;
      if (typeof data === 'string') {
        return data;
      }
      if (data != null && typeof data === 'object') {
        const detail = (data as { detail?: unknown }).detail;
        if (typeof detail === 'string' && detail.length > 0) {
          return detail;
        }
        const message = (data as { message?: unknown }).message;
        if (typeof message === 'string' && message.length > 0) {
          return message;
        }
      }
    }

    // Generic { message: string } shape (covers plain object errors like fetch rejections)
    if ('message' in err) {
      const message = (err as { message: unknown }).message;
      if (typeof message === 'string' && message.length > 0) {
        return message;
      }
    }
  }

  return fallback;
}
