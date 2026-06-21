import { useEffect, useMemo, useState } from 'react';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import { useAuth } from '../../features/auth/useAuth';
import {
  useGetPreferencesQuery,
  useGetKeywordListsQuery,
  useUpdatePreferencesMutation,
  useCreateKeywordListMutation,
  useUpdateKeywordListMutation,
  useDeleteKeywordListMutation,
} from '../../features/preferences/preferencesApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { TimeWindowDefaults } from '../../components/preferences/TimeWindowDefaults';
import { LocationDefaultsEditor } from '../../components/preferences/LocationDefaultsEditor';
import { ActiveListSelector } from '../../components/preferences/ActiveListSelector';
import { KeywordListsEditor } from '../../components/preferences/KeywordListsEditor';
import { PreferencesSaveBar } from '../../components/preferences/PreferencesSaveBar';
import {
  type DraftKeywordList,
  TEMP_ID_PREFIX,
  toDraftLists,
  canonicalListSet,
  diffKeywordLists,
  addTagToList,
  removeTagFromList,
  toggleTagModeInList,
} from '../../components/preferences/keywordListDraft';
import type { SearchTag, TimeWindow, UserPreferences } from '../../types';

/** Draft of the scalar preference fields (everything except keyword lists). */
type PreferencesDraft = UserPreferences;

function canonicalPreferences(p: PreferencesDraft): string {
  return JSON.stringify({
    recentTimeWindow: p.recentTimeWindow,
    trendTimeWindow: p.trendTimeWindow,
    locations: [...p.locations].sort(),
    recentActiveKeywordListId: p.recentActiveKeywordListId,
    trendActiveKeywordListId: p.trendActiveKeywordListId,
  });
}

export function PreferencesPage() {
  const { isAuthenticated, isLoading: authLoading, login } = useAuth();

  const prefsQuery = useGetPreferencesQuery(undefined, { skip: !isAuthenticated });
  const listsQuery = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });

  const [updatePreferences] = useUpdatePreferencesMutation();
  const [createKeywordList] = useCreateKeywordListMutation();
  const [updateKeywordList] = useUpdateKeywordListMutation();
  const [deleteKeywordList] = useDeleteKeywordListMutation();

  const [draft, setDraft] = useState<PreferencesDraft | null>(null);
  const [draftLists, setDraftLists] = useState<DraftKeywordList[]>([]);
  const [nextTempId, setNextTempId] = useState(1);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const serverPrefs = prefsQuery.data;
  const serverLists = listsQuery.data;

  // Seed the scalar draft from the server preferences whenever they (re)load.
  useEffect(() => {
    if (serverPrefs) {
      setDraft({
        recentTimeWindow: serverPrefs.recentTimeWindow,
        trendTimeWindow: serverPrefs.trendTimeWindow,
        locations: [...serverPrefs.locations],
        recentActiveKeywordListId: serverPrefs.recentActiveKeywordListId,
        trendActiveKeywordListId: serverPrefs.trendActiveKeywordListId,
      });
      setSaveError(null);
    }
  }, [serverPrefs]);

  // Seed the keyword-list draft from the server lists whenever they (re)load.
  useEffect(() => {
    if (serverLists) {
      setDraftLists(toDraftLists(serverLists));
      setSaveError(null);
    }
  }, [serverLists]);

  const patchDraft = (patch: Partial<PreferencesDraft>) => {
    setSaveSuccess(false);
    setDraft((d) => (d ? { ...d, ...patch } : d));
  };

  // ── keyword-list draft mutators (immutable) ──────────────────────────────
  const mutateList = (id: string, fn: (list: DraftKeywordList) => void) => {
    setSaveSuccess(false);
    setDraftLists((lists) =>
      lists.map((list) => {
        if (list.id !== id) return list;
        const copy: DraftKeywordList = { ...list, tags: list.tags.map((t) => ({ ...t })) };
        fn(copy);
        return copy;
      })
    );
  };

  const handleAddList = () => {
    setSaveSuccess(false);
    const id = `${TEMP_ID_PREFIX}${nextTempId}`;
    setNextTempId((n) => n + 1);
    // Insert before the read-only built-in so it stays last.
    setDraftLists((lists) => {
      const builtinIndex = lists.findIndex((l) => l.isBuiltin);
      const newList: DraftKeywordList = {
        id,
        name: '',
        tags: [],
        isBuiltin: false,
        position: lists.filter((l) => !l.isBuiltin).length,
        isNew: true,
      };
      if (builtinIndex === -1) return [...lists, newList];
      return [...lists.slice(0, builtinIndex), newList, ...lists.slice(builtinIndex)];
    });
  };

  const handleRename = (id: string, name: string) => mutateList(id, (l) => (l.name = name));
  const handleAddTag = (id: string, tag: SearchTag) => mutateList(id, (l) => addTagToList(l, tag));
  const handleRemoveTag = (id: string, text: string) =>
    mutateList(id, (l) => removeTagFromList(l, text));
  const handleToggleTagMode = (id: string, text: string) =>
    mutateList(id, (l) => toggleTagModeInList(l, text));

  const handleDeleteList = (id: string) => {
    setSaveSuccess(false);
    setDraftLists((lists) => lists.filter((l) => l.id !== id));
    // Clear any active-list reference to the just-removed list.
    setDraft((d) => {
      if (!d) return d;
      return {
        ...d,
        recentActiveKeywordListId: d.recentActiveKeywordListId === id ? null : d.recentActiveKeywordListId,
        trendActiveKeywordListId: d.trendActiveKeywordListId === id ? null : d.trendActiveKeywordListId,
      };
    });
  };

  // Lists selectable as "active": persisted (non-new) ones, built-in last.
  const selectableLists = useMemo(
    () => draftLists.filter((l) => !l.isNew),
    [draftLists]
  );

  // ── dirty check ──────────────────────────────────────────────────────────
  const isDirty = useMemo(() => {
    if (!draft || !serverPrefs || !serverLists) return false;
    const prefsDirty = canonicalPreferences(draft) !== canonicalPreferences(serverPrefs);
    const listsDirty =
      canonicalListSet(draftLists) !== canonicalListSet(toDraftLists(serverLists));
    return prefsDirty || listsDirty;
  }, [draft, serverPrefs, serverLists, draftLists]);

  // ── save ───────────────────────────────────────────────────────────────
  const handleSave = async () => {
    if (!draft || !serverLists) return;
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    try {
      const { toCreate, toUpdate, toDeleteIds } = diffKeywordLists(serverLists, draftLists);

      // Apply keyword-list changes first so the active-list ids the PUT
      // references already exist server-side (creates) / no longer dangle
      // (deletes). Deletes are dropped from the active-list ids below.
      for (const list of toCreate) {
        await createKeywordList({ name: list.name.trim(), tags: list.tags }).unwrap();
      }
      for (const list of toUpdate) {
        await updateKeywordList({ id: list.id, name: list.name.trim(), tags: list.tags }).unwrap();
      }
      for (const id of toDeleteIds) {
        await deleteKeywordList(id).unwrap();
      }

      const deleted = new Set(toDeleteIds);
      await updatePreferences({
        recentTimeWindow: draft.recentTimeWindow,
        trendTimeWindow: draft.trendTimeWindow,
        locations: draft.locations,
        recentActiveKeywordListId: deleted.has(draft.recentActiveKeywordListId ?? '')
          ? null
          : draft.recentActiveKeywordListId,
        trendActiveKeywordListId: deleted.has(draft.trendActiveKeywordListId ?? '')
          ? null
          : draft.trendActiveKeywordListId,
      }).unwrap();

      setSaveSuccess(true);
      // RTK Query cache invalidation (Preferences / KeywordLists tags) refetches
      // both queries; the seeding effects above then re-sync the drafts (new
      // lists pick up their server ids, isNew clears).
    } catch (err) {
      setSaveError(extractErrorMessage(err, 'Failed to save preferences'));
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
            Preferences
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
            Sign in to manage your preferences.
          </Typography>
          <Button variant="contained" onClick={login}>
            Sign In
          </Button>
        </Paper>
      </Container>
    );
  }

  if (prefsQuery.isLoading || listsQuery.isLoading || !draft) {
    return <LoadingState fullPage />;
  }

  if (prefsQuery.isError || listsQuery.isError) {
    const message = extractErrorMessage(
      prefsQuery.error ?? listsQuery.error,
      'Failed to load preferences'
    );
    return (
      <Container maxWidth="md" sx={{ py: 4 }}>
        <ErrorState
          inline
          message={message}
          onRetry={() => {
            prefsQuery.refetch();
            listsQuery.refetch();
          }}
        />
      </Container>
    );
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Preferences
      </Typography>

      <Stack spacing={3}>
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

        <ActiveListSelector
          selectableLists={selectableLists}
          recentActiveKeywordListId={draft.recentActiveKeywordListId}
          trendActiveKeywordListId={draft.trendActiveKeywordListId}
          onChangeRecent={(id) => patchDraft({ recentActiveKeywordListId: id })}
          onChangeTrend={(id) => patchDraft({ trendActiveKeywordListId: id })}
        />

        <KeywordListsEditor
          lists={draftLists}
          onAddList={handleAddList}
          onRename={handleRename}
          onAddTag={handleAddTag}
          onRemoveTag={handleRemoveTag}
          onToggleTagMode={handleToggleTagMode}
          onDelete={handleDeleteList}
        />

        <PreferencesSaveBar
          isDirty={isDirty}
          isSaving={isSaving}
          saveSuccess={saveSuccess}
          saveError={saveError}
          onSave={handleSave}
        />
      </Stack>
    </Container>
  );
}
