/**
 * Persistence for "I've seen this suggestion, stop showing it."
 *
 * Its own module for the same reason `NewFeatureCallout/dismissalStorage.ts` is: exporting
 * non-components beside a component breaks Fast Refresh, and the storage is worth testing
 * on its own anyway.
 *
 * localStorage, not the server. The suggestion itself is server-side (it rides the row on
 * the poll the list already runs), but the dismissal is a UI preference about one banner —
 * and keeping it here means the whole published-board-match path stays incapable of writing
 * anything the user could later have to undo. The cost, stated plainly: a dismissal does
 * not follow the user to another browser, so the banner reappears there once. That is the
 * cheaper mistake than a server-side write on a path whose entire premise is that it never
 * changes anything.
 */

/**
 * Keyed on BOTH ids, not just the board's.
 *
 * If a board later matches a *different* public company that is a different claim and
 * deserves to be seen — the user dismissed "this is Spotify", not "never tell me anything".
 * And the same claim about a *different* board is also different: two private boards that
 * both look like Spotify are two decisions.
 */
function storageKey(companyId: string, matchedCompanyId: string): string {
  return `publicBoardMatch:${companyId}:${matchedCompanyId}:dismissed`;
}

/** Has this exact suggestion already been dismissed? Never throws. */
export function isPublicMatchDismissed(companyId: string, matchedCompanyId: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const raw = window.localStorage.getItem(storageKey(companyId, matchedCompanyId));
    return typeof raw === 'string' && raw.length > 0;
  } catch {
    return false;
  }
}

/**
 * Persist the dismissal. Never throws — storage can be disabled or full, and the caller has
 * already hidden the banner for this session, so losing the persistence is the acceptable
 * failure while throwing out of a click handler is not.
 */
export function markPublicMatchDismissed(companyId: string, matchedCompanyId: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      storageKey(companyId, matchedCompanyId),
      new Date().toISOString(),
    );
  } catch {
    // Deliberately silent — see above.
  }
}
