import { useEffect, useMemo, useState } from 'react';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import { useAuth } from '../../features/auth/useAuth';
import {
  useGetSavedFiltersQuery,
  useGetKeywordListsQuery,
  useUpdateSavedFiltersMutation,
} from '../../features/savedFilters/savedFiltersApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { TimeWindowDefaults } from '../../components/saved-filters/TimeWindowDefaults';
import { LocationDefaultsEditor } from '../../components/saved-filters/LocationDefaultsEditor';
import { ActiveListSelector } from '../../components/saved-filters/ActiveListSelector';
import { KeywordListsEditor } from '../../components/saved-filters/KeywordListsEditor';
import { SavedFiltersSaveBar } from '../../components/saved-filters/SavedFiltersSaveBar';
import {
  type DraftKeywordList,
  TEMP_ID_PREFIX,
  toDraftLists,
} from '../../components/saved-filters/keywordListDraft';
import type { TimeWindow, SavedFilters } from '../../types';

/** Draft of the scalar saved-filter fields (everything except keyword lists). */
type SavedFiltersDraft = SavedFilters;

function canonicalSavedFilters(p: SavedFiltersDraft): string {
  return JSON.stringify({
    recentTimeWindow: p.recentTimeWindow,
    trendTimeWindow: p.trendTimeWindow,
    locations: [...p.locations].sort(),
    recentActiveKeywordListId: p.recentActiveKeywordListId,
    trendActiveKeywordListId: p.trendActiveKeywordListId,
  });
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

  const prefsQuery = useGetSavedFiltersQuery(undefined, { skip: !isAuthenticated });
  const listsQuery = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });

  const [updateSavedFilters] = useUpdateSavedFiltersMutation();

  // Scalar prefs (time windows, locations, active list) are committed by the
  // single Save bar; keyword lists save per-card (see KeywordListCard).
  const [draft, setDraft] = useState<SavedFiltersDraft | null>(null);
  // Not-yet-persisted keyword-list placeholders (new cards open in edit mode).
  const [newCards, setNewCards] = useState<DraftKeywordList[]>([]);
  const [nextTempId, setNextTempId] = useState(1);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const serverPrefs = prefsQuery.data;
  const serverLists = listsQuery.data;

  // Seed the scalar draft from the server saved filters whenever they (re)load.
  // serverPrefs only changes on initial load and after a scalar save (keyword
  // create/update/delete invalidate the KeywordLists tag only), so this never
  // clobbers in-progress scalar edits.
  useEffect(() => {
    if (serverPrefs) {
      setDraft(draftFromServer(serverPrefs));
      setSaveError(null);
    }
  }, [serverPrefs]);

  const patchDraft = (patch: Partial<SavedFiltersDraft>) => {
    setSaveSuccess(false);
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
    setSaveSuccess(false);
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
  const handleCardDeleted = (id: string) => {
    setDraft((d) => {
      if (!d) return d;
      if (d.recentActiveKeywordListId !== id && d.trendActiveKeywordListId !== id) {
        return d;
      }
      setSaveSuccess(false);
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

  const isDirty = useMemo(() => {
    if (!draft || !serverPrefs) return false;
    return canonicalSavedFilters(draft) !== canonicalSavedFilters(serverPrefs);
  }, [draft, serverPrefs]);

  const handleSave = async () => {
    if (!draft) return;
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    try {
      const saved = await updateSavedFilters({
        recentTimeWindow: draft.recentTimeWindow,
        trendTimeWindow: draft.trendTimeWindow,
        locations: draft.locations,
        recentActiveKeywordListId: draft.recentActiveKeywordListId,
        trendActiveKeywordListId: draft.trendActiveKeywordListId,
      }).unwrap();
      setDraft(draftFromServer(saved));
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(extractErrorMessage(err, 'Failed to save your saved filters'));
    } finally {
      setIsSaving(false);
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
          <>
            <TimeWindowDefaults
              recentTimeWindow={draft.recentTimeWindow}
              trendTimeWindow={draft.trendTimeWindow}
              onChangeRecent={(tw: TimeWindow) => patchDraft({ recentTimeWindow: tw })}
              onChangeTrend={(tw: TimeWindow) => patchDraft({ trendTimeWindow: tw })}
            />

            <LocationDefaultsEditor
              locations={draft.locations}
              onAdd={(loc) =>
                patchDraft({
                  locations: draft.locations.includes(loc)
                    ? draft.locations
                    : [...draft.locations, loc],
                })
              }
              onRemove={(loc) =>
                patchDraft({ locations: draft.locations.filter((l) => l !== loc) })
              }
            />

            {listsReady ? (
              <ActiveListSelector
                selectableLists={persistedLists}
                activeKeywordListId={draft.recentActiveKeywordListId}
                onChange={handleActiveListChange}
              />
            ) : (
              <Paper sx={{ p: 4 }}>
                <LoadingState minHeight={80} />
              </Paper>
            )}
          </>
        )}

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
          />
        )}

        {draft && !prefsQuery.isError && (
          <SavedFiltersSaveBar
            isDirty={isDirty}
            isSaving={isSaving}
            saveSuccess={saveSuccess}
            saveError={saveError}
            onSave={handleSave}
          />
        )}
      </Stack>
    </Container>
  );
}
