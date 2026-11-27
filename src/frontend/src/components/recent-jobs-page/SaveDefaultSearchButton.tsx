import { useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import type { SxProps, Theme } from '@mui/material/styles';
import CheckIcon from '@mui/icons-material/Check';
import { useAppSelector } from '../../app/hooks';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';
import { trackSignInClick } from '../../features/analytics/events';
import { useAuth } from '../../features/auth/useAuth';
import {
  defaultSearchFromFilters,
  defaultSearchFromSaved,
  defaultSearchKey,
} from '../../features/defaultSearch/defaultSearch';
import {
  clearPendingDefaultSearch,
  writePendingDefaultSearch,
} from '../../features/defaultSearch/pendingDefaultSearch';
import { useSaveDefaultSearch } from '../../features/defaultSearch/useSaveDefaultSearch';
import { selectRecentJobsFilters } from '../../features/filters/selectors/recentJobsSelectors';
import { recentJobsInitialFilters } from '../../features/filters/slices/recentJobsFiltersSlice';
import {
  useGetKeywordListsQuery,
  useGetSavedFiltersQuery,
} from '../../features/savedFilters/savedFiltersApi';

const SIGN_IN_ERROR = "Couldn't open sign-in. Try again.";

/** A signed-out reader's baseline: the site defaults. */
const SIGNED_OUT_BASELINE_KEY = defaultSearchKey(defaultSearchFromFilters(recentJobsInitialFilters));

/** The inline confirmation / error beside the button, in the button's type size. */
const MESSAGE_SX = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 0.5,
  fontSize: RESPONSIVE.control.buttonFontSize,
  lineHeight: 1.4,
} as const;

/**
 * "Save default search", to the right of Reset Filters on Recent Jobs.
 *
 * Saves every current filter as the reader's default, so the page opens on it
 * next time. Grayed out while the filters equal the saved default (signed out:
 * the site defaults); enabled the moment they differ. A signed-out click stores
 * the search and sends the reader to sign in; the load they come back to saves
 * it (`useApplyPendingDefaultSearch`).
 *
 * Also disabled while auth or the saved filters are loading or failed, and while
 * a save is in flight. Not rendered when auth is not configured.
 *
 * Renders a fragment (the button, a status box, maybe an alert) so each lands
 * as its own item in the parent's wrapping row.
 */
export function SaveDefaultSearchButton({ sx }: { sx?: SxProps<Theme> }) {
  const { isEnabled, isAuthenticated, isLoading, loginWithReturnTo } = useAuth();
  const signedIn = isEnabled && isAuthenticated;
  const filters = useAppSelector(selectRecentJobsFilters);
  const hydrated = useAppSelector((state) => state.recentJobsFilters.hydrated);
  const { saving, result } = useAppSelector((state) => state.defaultSearch);
  const savedQuery = useGetSavedFiltersQuery(undefined, { skip: !signedIn });
  const listsQuery = useGetKeywordListsQuery(undefined, { skip: !signedIn });
  const { save } = useSaveDefaultSearch();
  const [signInFailedKey, setSignInFailedKey] = useState<string | null>(null);

  const live = useMemo(() => defaultSearchFromFilters(filters), [filters]);
  const liveKey = useMemo(() => defaultSearchKey(live), [live]);
  const savedFilters = savedQuery.data;
  const keywordLists = listsQuery.data;
  const baselineKey = useMemo(() => {
    if (!signedIn) return SIGNED_OUT_BASELINE_KEY;
    if (!savedFilters || !keywordLists) return null;
    return defaultSearchKey(defaultSearchFromSaved(savedFilters, keywordLists));
  }, [signedIn, savedFilters, keywordLists]);

  if (!isEnabled) return null;

  // Signed in, the slice must also have hydrated: in the render where the saved
  // filters arrive the slice still holds the site defaults, and comparing those
  // would flash the button on for a frame.
  const ready =
    !isLoading &&
    baselineKey !== null &&
    (!signedIn || (hydrated && !savedQuery.isError && !listsQuery.isError));
  const disabled = !ready || saving || liveKey === baselineKey;

  const savedShown = !saving && result?.kind === 'saved' && result.key === liveKey;
  const saveError =
    !saving && result?.kind === 'error' && result.key === liveKey ? result.message : null;
  const errorText = saveError ?? (signInFailedKey === liveKey ? SIGN_IN_ERROR : null);

  const handleClick = async () => {
    if (!signedIn) {
      setSignInFailedKey(null);
      writePendingDefaultSearch(live);
      trackSignInClick('save_default_search');
      try {
        // The bare path: the Recent URL has no specialty param, so the search
        // rides in sessionStorage instead.
        await loginWithReturnTo(ROUTES.RECENT_JOBS);
      } catch {
        clearPendingDefaultSearch();
        setSignInFailedKey(liveKey);
      }
      return;
    }
    if (!savedFilters || !keywordLists) return;
    await save(live, { current: savedFilters, lists: keywordLists });
  };

  return (
    <>
      <Button
        variant="outlined"
        size="small"
        disabled={disabled}
        onClick={() => void handleClick()}
        sx={sx}
      >
        {/* Both labels share one grid cell, so the button keeps the width of
            the longer one and nothing beside it jumps while saving. */}
        <Box component="span" sx={{ display: 'inline-grid', justifyItems: 'center' }}>
          <span style={{ gridArea: '1 / 1', visibility: saving ? 'hidden' : 'visible' }}>
            Save default search
          </span>
          <span style={{ gridArea: '1 / 1', visibility: saving ? 'visible' : 'hidden' }}>
            Saving…
          </span>
        </Box>
      </Button>
      {/* Always mounted, so the confirmation is announced when it appears. */}
      <Box role="status" sx={{ ...MESSAGE_SX, color: 'text.secondary' }}>
        {savedShown && (
          <>
            <CheckIcon aria-hidden sx={{ fontSize: '1.125rem', color: 'success.main' }} />
            Saved default search
          </>
        )}
      </Box>
      {errorText && (
        <Box role="alert" sx={{ ...MESSAGE_SX, color: 'error.main' }}>
          {errorText}
        </Box>
      )}
    </>
  );
}
