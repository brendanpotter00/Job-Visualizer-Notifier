import { useEffect, useMemo, useState } from 'react';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import { useAuth } from '../../features/auth/useAuth';
import { useAppDispatch } from '../../app/hooks';
import {
  useGetSavedFiltersQuery,
  useGetKeywordListsQuery,
  useUpdateSavedFiltersMutation,
} from '../../features/savedFilters/savedFiltersApi';
import {
  savedFiltersPropagationActions,
  activeListContentPropagationActions,
  deletedListPropagationActions,
} from '../../features/savedFilters/propagateSavedFilters';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { TimeWindowDefaults } from '../../components/saved-filters/TimeWindowDefaults';
import { LocationDefaultsEditor } from '../../components/saved-filters/LocationDefaultsEditor';
import { EnabledCompaniesSection } from '../../components/saved-filters/EnabledCompaniesSection';
import { KeywordListsEditor } from '../../components/saved-filters/KeywordListsEditor';
import {
  type DraftKeywordList,
  TEMP_ID_PREFIX,
  toDraftLists,
} from '../../components/saved-filters/keywordListDraft';
import type { TimeWindow, SavedFilters, KeywordList } from '../../types';

/** Draft of the scalar saved-filter fields (everything except keyword lists). */
type SavedFiltersDraft = SavedFilters;

/** Which section's Save button is mid-flight / showing feedback. */
type SaveSection = 'timeWindows' | 'locations' | 'keywords';

/** Stable key for comparing location sets regardless of order. */
function locationsKey(locations: string[]): string {
  return [...locations].sort().join('\n');
}

function draftFromServer(p: SavedFilters): SavedFiltersDraft {
  return {
    recentTimeWindow: p.recentTimeWindow,
    trendTimeWindow: p.trendTimeWindow,
    locations: [...p.locations],
    recentActiveKeywordListId: p.recentActiveKeywordListId,
    trendActiveKeywordListId: p.trendActiveKeywordListId,
  };
}

export function SavedFiltersPage() {
  const { isAuthenticated, isLoading: authLoading, login } = useAuth();
  const dispatch = useAppDispatch();

  const prefsQuery = useGetSavedFiltersQuery(undefined, { skip: !isAuthenticated });
  const listsQuery = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });

  const [updateSavedFilters] = useUpdateSavedFiltersMutation();

  // Each settings section (time windows, locations, active keyword list) commits
  // the whole settings object via its own Save button (one request); keyword
  // list *contents* still save per-card (see KeywordListCard).
  const [draft, setDraft] = useState<SavedFiltersDraft | null>(null);
  // Not-yet-persisted keyword-list placeholders (new cards open in edit mode).
  const [newCards, setNewCards] = useState<DraftKeywordList[]>([]);
  const [nextTempId, setNextTempId] = useState(1);
  // Per-section save lifecycle: which section is saving, and where to show the
  // success/error feedback. All three buttons share one in-flight slot because
  // each issues the same full PUT.
  const [savingSection, setSavingSection] = useState<SaveSection | null>(null);
  const [successSection, setSuccessSection] = useState<SaveSection | null>(null);
  const [errorSection, setErrorSection] = useState<SaveSection | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const serverPrefs = prefsQuery.data;
  const serverLists = listsQuery.data;

  // Seed the scalar draft from the server saved filters whenever they (re)load.
  // serverPrefs only changes on initial load and after a scalar save (keyword
  // create/update/delete invalidate the KeywordLists tag only), so this never
  // clobbers in-progress scalar edits.
  useEffect(() => {
    if (serverPrefs) {
      setDraft(draftFromServer(serverPrefs));
      setErrorSection(null);
      setErrorMessage(null);
    }
  }, [serverPrefs]);

  const patchDraft = (patch: Partial<SavedFiltersDraft>) => {
    // Any edit clears stale save feedback so a "Saved" chip never lingers over
    // unsaved changes.
    setSuccessSection(null);
    setErrorSection(null);
    setErrorMessage(null);
    setDraft((d) => (d ? { ...d, ...patch } : d));
  };

  // Persisted lists in display order (user lists by position, builtin last).
  const persistedLists = useMemo(
    () => (serverLists ? toDraftLists(serverLists) : []),
    [serverLists]
  );
  // New (unsaved) cards first so a freshly added list appears at the top.
  const displayLists = useMemo(() => [...newCards, ...persistedLists], [newCards, persistedLists]);

  const handleAddList = () => {
    setSuccessSection(null);
    const id = `${TEMP_ID_PREFIX}${nextTempId}`;
    setNextTempId((n) => n + 1);
    setNewCards((cards) => [
      { id, name: '', tags: [], isBuiltin: false, position: 0, isNew: true },
      ...cards,
    ]);
  };

  const dropNewCard = (tempId: string) =>
    setNewCards((cards) => cards.filter((c) => c.id !== tempId));

  // A deleted list's id must not linger as the active pointer; clear it locally
  // (the backend already NULLs it server-side in the same delete transaction).
  // Mirror the content-edit fix: clear the deleted list's tags from whichever
  // live pages were filtering by it (the persisted pointers — what each page
  // actually applies), so the graph/recent views don't keep filtering by the
  // gone list until a refresh. The deleteKeywordList mutation invalidates the
  // SavedFilters cache too, so the refetched pointers agree with this clear.
  const handleCardDeleted = (id: string) => {
    if (serverPrefs) {
      deletedListPropagationActions(id, serverPrefs).forEach((action) => dispatch(action));
    }
    setDraft((d) => {
      if (!d) return d;
      if (d.recentActiveKeywordListId !== id && d.trendActiveKeywordListId !== id) {
        return d;
      }
      setSuccessSection(null);
      return {
        ...d,
        recentActiveKeywordListId:
          d.recentActiveKeywordListId === id ? null : d.recentActiveKeywordListId,
        trendActiveKeywordListId:
          d.trendActiveKeywordListId === id ? null : d.trendActiveKeywordListId,
      };
    });
  };

  // The single active list applies to all pages, so set both per-page pointers.
  const handleActiveListChange = (id: string | null) =>
    patchDraft({ recentActiveKeywordListId: id, trendActiveKeywordListId: id });

  // Per-section dirty: enables each section's Save button independently.
  const timeWindowsDirty = useMemo(() => {
    if (!draft || !serverPrefs) return false;
    return (
      draft.recentTimeWindow !== serverPrefs.recentTimeWindow ||
      draft.trendTimeWindow !== serverPrefs.trendTimeWindow
    );
  }, [draft, serverPrefs]);

  const locationsDirty = useMemo(() => {
    if (!draft || !serverPrefs) return false;
    return locationsKey(draft.locations) !== locationsKey(serverPrefs.locations);
  }, [draft, serverPrefs]);

  const keywordsDirty = useMemo(() => {
    if (!draft || !serverPrefs) return false;
    return (
      draft.recentActiveKeywordListId !== serverPrefs.recentActiveKeywordListId ||
      draft.trendActiveKeywordListId !== serverPrefs.trendActiveKeywordListId
    );
  }, [draft, serverPrefs]);

  // Snap the Recent Jobs and Company pages to the just-saved defaults without a
  // refresh, using the authoritative server response (see
  // savedFiltersPropagationActions for why this is push-on-save, not re-hydrate).
  const propagateToPages = (saved: SavedFilters) => {
    savedFiltersPropagationActions(saved, serverLists ?? []).forEach((action) => dispatch(action));
  };

  // A per-card content edit (PATCH) doesn't change the active *selection*, so the
  // section Save buttons never run. Re-push the freshly-saved tags to whichever
  // pages have this list active (against the persisted pointers — what each page
  // is actually filtering by) so the live pages don't keep using the stale set.
  const handleCardContentSaved = (saved: KeywordList) => {
    if (!serverPrefs) return;
    activeListContentPropagationActions(saved, serverPrefs).forEach((action) => dispatch(action));
  };

  const handleSave = async (section: SaveSection) => {
    if (!draft) return;
    setSavingSection(section);
    setSuccessSection(null);
    setErrorSection(null);
    setErrorMessage(null);
    try {
      const saved = await updateSavedFilters({
        recentTimeWindow: draft.recentTimeWindow,
        trendTimeWindow: draft.trendTimeWindow,
        locations: draft.locations,
        recentActiveKeywordListId: draft.recentActiveKeywordListId,
        trendActiveKeywordListId: draft.trendActiveKeywordListId,
      }).unwrap();
      setDraft(draftFromServer(saved));
      propagateToPages(saved);
      setSuccessSection(section);
    } catch (err) {
      setErrorSection(section);
      setErrorMessage(extractErrorMessage(err, 'Failed to save your saved filters'));
    } finally {
      setSavingSection(null);
    }
  };

  // ── auth ladder (mirrors AccountPage) ────────────────────────────────────
  if (authLoading) {
    return <LoadingState fullPage />;
  }

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ py: 4 }}>
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="h5" gutterBottom>
            Saved Filters
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
            Sign in to manage your saved filters.
          </Typography>
          <Button variant="contained" onClick={login}>
            Sign In
          </Button>
        </Paper>
      </Container>
    );
  }

  // Progressive rendering: each section shows its own loading / error state so a
  // slow (or cold-started) request never blocks the whole page behind one
  // spinner. The scalar sections and the keyword lists load independently.
  const prefsLoading = !draft && !prefsQuery.isError;
  const listsReady = Boolean(serverLists);

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Saved Filters
      </Typography>

      <Stack spacing={3}>
        {prefsQuery.isError ? (
          <ErrorState
            inline
            message={extractErrorMessage(prefsQuery.error, 'Failed to load saved filters')}
            onRetry={() => prefsQuery.refetch()}
          />
        ) : prefsLoading || !draft ? (
          <Paper sx={{ p: 4 }}>
            <LoadingState minHeight={140} caption="Loading your saved filters…" />
          </Paper>
        ) : (
          <LocationDefaultsEditor
            locations={draft.locations}
            onAdd={(loc) =>
              patchDraft({
                locations: draft.locations.includes(loc)
                  ? draft.locations
                  : [...draft.locations, loc],
              })
            }
            onRemove={(loc) => patchDraft({ locations: draft.locations.filter((l) => l !== loc) })}
            dirty={locationsDirty}
            saving={savingSection === 'locations'}
            success={successSection === 'locations'}
            error={errorSection === 'locations' ? errorMessage : null}
            onSave={() => handleSave('locations')}
          />
        )}

        <EnabledCompaniesSection />

        {listsQuery.isError ? (
          <ErrorState
            inline
            message={extractErrorMessage(listsQuery.error, 'Failed to load keyword lists')}
            onRetry={() => listsQuery.refetch()}
          />
        ) : !listsReady ? (
          <Paper sx={{ p: 4 }}>
            <LoadingState minHeight={140} caption="Loading keyword lists…" />
          </Paper>
        ) : (
          <KeywordListsEditor
            lists={displayLists}
            onAddList={handleAddList}
            onCardCreated={dropNewCard}
            onCardCancelNew={dropNewCard}
            onCardDeleted={handleCardDeleted}
            onCardContentSaved={handleCardContentSaved}
            activeKeywordListId={draft?.recentActiveKeywordListId ?? null}
            onActiveChange={handleActiveListChange}
            activeDirty={keywordsDirty}
            activeSaving={savingSection === 'keywords'}
            activeSuccess={successSection === 'keywords'}
            activeError={errorSection === 'keywords' ? errorMessage : null}
            onSaveActive={() => handleSave('keywords')}
          />
        )}

        {/* Default time windows sit last per design. They read from the same
            prefs draft as the Locations section above, which already surfaces
            the prefs loading/error state, so they render once the draft is in
            rather than repeating a spinner/error here. */}
        {draft && (
          <TimeWindowDefaults
            recentTimeWindow={draft.recentTimeWindow}
            trendTimeWindow={draft.trendTimeWindow}
            onChangeRecent={(tw: TimeWindow) => patchDraft({ recentTimeWindow: tw })}
            onChangeTrend={(tw: TimeWindow) => patchDraft({ trendTimeWindow: tw })}
            dirty={timeWindowsDirty}
            saving={savingSection === 'timeWindows'}
            success={successSection === 'timeWindows'}
            error={errorSection === 'timeWindows' ? errorMessage : null}
            onSave={() => handleSave('timeWindows')}
          />
        )}
      </Stack>
    </Container>
  );
}
