/**
 * Extracts a human-readable error message from an unknown error value.
 *
 * Handles (in priority order):
 *   1. `Error` instances → `err.message`
 *   2. string errors → the string as-is
 *   3. RTK Query shape `{ data: string | { detail?: string; message?: string } }`
 *      → `data.detail`, `data.message`, or `data` (string) — first non-empty wins
 *   4. Generic `{ message: string }` objects → `err.message`
 *   5. RTK Query `CUSTOM_ERROR` / `FETCH_ERROR` shapes carry the message on
 *      `err.error` (string) or `err.error.message`. The runtime guards in
 *      `adminApi.ts` throw via `transformResponse`, which RTK Query wraps
 *      as `{ status: 'CUSTOM_ERROR', error: '...' }`. Without reading
 *      `.error`, those messages never surface and the consumer sees a
 *      generic fallback.
 *   6. Anything else (including `null` / `undefined`) → `fallback`
 *
 * Centralizes `err instanceof Error` / RTK Query `'data' in err` decoding in
 * one place so call sites can stay a single expression.
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

    // RTK Query CUSTOM_ERROR / FETCH_ERROR shapes carry the message on
    // ``err.error``. CUSTOM_ERROR (raised by transformResponse guards in
    // adminApi.ts) uses ``error: string``; some adapters nest it as
    // ``error: { message: string }`` (mirroring SerializedError). Read both.
    if ('error' in err) {
      const errorField = (err as { error: unknown }).error;
      if (typeof errorField === 'string' && errorField.length > 0) {
        return errorField;
      }
      if (errorField != null && typeof errorField === 'object') {
        const nestedMessage = (errorField as { message?: unknown }).message;
        if (typeof nestedMessage === 'string' && nestedMessage.length > 0) {
          return nestedMessage;
        }
      }
    }
  }

  return fallback;
}
