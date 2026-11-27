import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import type { SxProps, Theme } from '@mui/material/styles';
import CheckIcon from '@mui/icons-material/Check';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';
import { trackSignInClick } from '../../features/analytics/events';
import { useAuth } from '../../features/auth/useAuth';
import {
  defaultSearchFromFilters,
  defaultSearchFromSaved,
  defaultSearchKey,
  toRecentFiltersPatch,
} from '../../features/defaultSearch/defaultSearch';
import {
  clearPendingDefaultSearch,
  writePendingDefaultSearch,
} from '../../features/defaultSearch/pendingDefaultSearch';
import { useSaveDefaultSearch } from '../../features/defaultSearch/useSaveDefaultSearch';
import { selectRecentJobsFilters } from '../../features/filters/selectors/recentJobsSelectors';
import {
  recentJobsInitialFilters,
  resetRecentJobsFilters,
} from '../../features/filters/slices/recentJobsFiltersSlice';
import {
  useGetKeywordListsQuery,
  useGetSavedFiltersQuery,
} from '../../features/savedFilters/savedFiltersApi';
import { VISUALLY_HIDDEN_SX } from '../../lib/visuallyHidden';

const SIGN_IN_ERROR = "Couldn't open sign-in. Try again.";

/** The site defaults: the default search of a reader with nothing saved (signed out). */
const SITE_DEFAULT_SEARCH = defaultSearchFromFilters(recentJobsInitialFilters);

/** The error beside the buttons, in the buttons' type size. */
const ERROR_SX = {
  display: 'inline-flex',
  alignItems: 'center',
  fontSize: RESPONSIVE.control.buttonFontSize,
  lineHeight: 1.4,
  color: 'error.main',
} as const;

/**
 * On the saved default the grayed-out button IS the confirmation, so it reads
 * as a status (secondary text, a green check), not as a dead control.
 */
const SAVED_SX = { '&.Mui-disabled': { color: 'text.secondary' } } as const;

type SaveLabel = 'save' | 'update' | 'saved' | 'saving';

const SAVE_LABELS: Record<SaveLabel, ReactNode> = {
  save: 'Save default search',
  update: 'Update default search',
  saved: (
    <>
      <CheckIcon aria-hidden sx={{ fontSize: '1.125rem', color: 'success.main' }} />
      Default search saved
    </>
  ),
  saving: 'Saving…',
};

/**
 * The default-search buttons on Recent Jobs, left to right:
 *
 * 1. Save / Update default search. Saves every current filter as the reader's
 *    default, so the page opens on it next time.
 *    - Signed in, on the saved default: grayed out, "✓ Default search saved".
 *      The button is the confirmation; there is no message beside it.
 *    - Signed in, filters changed: "Update default search".
 *    - Signed out: "Save default search", never the check (nothing is saved).
 *      Grayed out on the site defaults. A click stores the search and sends the
 *      reader to sign in; the load they come back to saves it
 *      (`useApplyPendingDefaultSearch`).
 *    - Invisible (its space kept) while auth or the saved filters are loading,
 *      grayed out if they failed, and "Saving…" while a save is in flight. Not
 *      rendered when auth is not configured.
 * 2. Reset to default search. Shown only while the filters differ from the
 *    default (signed in: the saved default; otherwise the site defaults), and
 *    puts it back on screen. It sits on the right, so nothing moves when it
 *    appears.
 *
 * Renders a fragment so each piece lands as its own item in the parent's
 * wrapping row.
 */
export function DefaultSearchButtons({ sx }: { sx?: SxProps<Theme> }) {
  const dispatch = useAppDispatch();
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
  const defaultSearch = useMemo(() => {
    if (!signedIn) return SITE_DEFAULT_SEARCH;
    if (!savedFilters || !keywordLists) return null;
    return defaultSearchFromSaved(savedFilters, keywordLists);
  }, [signedIn, savedFilters, keywordLists]);
  const defaultKey = useMemo(
    () => (defaultSearch ? defaultSearchKey(defaultSearch) : null),
    [defaultSearch]
  );

  // Signed in, the slice must also have hydrated: in the render where the saved
  // filters arrive the slice still holds the site defaults, and comparing those
  // would flash the buttons for a frame.
  const failed = signedIn && (savedQuery.isError || listsQuery.isError);
  const ready = !isLoading && defaultKey !== null && (!signedIn || (hydrated && !failed));
  // Auth or the saved default is still loading: the label would be a guess
  // ("Save" before auth knows the reader, "Update" before the default arrives,
  // then "Default search saved"). The button keeps its space but stays
  // invisible until it can say the right thing. A failed load shows it grayed out.
  const settling = !ready && !failed;
  const onDefault = ready && liveKey === defaultKey;
  const showReset = ready && !saving && !onDefault;

  const label: SaveLabel = saving ? 'saving' : !signedIn ? 'save' : onDefault ? 'saved' : 'update';
  // Every label this reader can see shares one grid cell, so the button keeps
  // the width of the longest and nothing beside it jumps when the label changes.
  const labels: SaveLabel[] = signedIn ? ['update', 'saved', 'saving'] : ['save', 'saving'];

  const justSaved = !saving && result?.kind === 'saved' && result.key === liveKey;
  const saveError =
    !saving && result?.kind === 'error' && result.key === liveKey ? result.message : null;
  const errorText = saveError ?? (signInFailedKey === liveKey ? SIGN_IN_ERROR : null);

  const handleSave = async () => {
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

  const handleReset = () => {
    if (defaultSearch) dispatch(resetRecentJobsFilters(toRecentFiltersPatch(defaultSearch)));
  };

  return (
    <>
      {isEnabled && (
        <Button
          variant="outlined"
          size="small"
          disabled={saving || !ready || onDefault}
          onClick={() => void handleSave()}
          sx={[
            ...(Array.isArray(sx) ? sx : [sx]),
            label === 'saved' && SAVED_SX,
            settling && { visibility: 'hidden' },
          ]}
        >
          <Box component="span" sx={{ display: 'inline-grid', justifyItems: 'center' }}>
            {labels.map((key) => (
              <Box
                component="span"
                key={key}
                sx={{
                  gridArea: '1 / 1',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 0.5,
                  // A visible child would show through a hidden button.
                  visibility: !settling && key === label ? 'visible' : 'hidden',
                }}
              >
                {SAVE_LABELS[key]}
              </Box>
            ))}
          </Box>
        </Button>
      )}
      {showReset && (
        <Button variant="outlined" size="small" onClick={handleReset} sx={sx}>
          Reset to default search
        </Button>
      )}
      {/* Screen readers only. A save grays the button out, which drops its
          keyboard focus, so a sighted reader sees the check but a screen
          reader would hear nothing; this says it. Always mounted, so the
          change is announced. */}
      <Box role="status" sx={VISUALLY_HIDDEN_SX}>
        {justSaved ? 'Default search saved' : ''}
      </Box>
      {errorText && (
        <Box role="alert" sx={ERROR_SX}>
          {errorText}
        </Box>
      )}
    </>
  );
}
