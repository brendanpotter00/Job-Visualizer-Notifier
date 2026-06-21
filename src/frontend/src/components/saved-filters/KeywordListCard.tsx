import { useState } from 'react';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';
import Alert from '@mui/material/Alert';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import LockIcon from '@mui/icons-material/Lock';
import { Add as AddIcon, Remove as RemoveIcon } from '@mui/icons-material';
import { SearchTagsInput } from '../shared/filters/SearchTagsInput.tsx';
import { extractErrorMessage } from '../../lib/errors.ts';
import {
  useCreateKeywordListMutation,
  useUpdateKeywordListMutation,
  useDeleteKeywordListMutation,
} from '../../features/savedFilters/savedFiltersApi.ts';
import {
  addTagToList,
  removeTagFromList,
  toggleTagModeInList,
  cloneDraftList,
  type DraftKeywordList,
} from './keywordListDraft.ts';

export interface KeywordListCardProps {
  list: DraftKeywordList;
  /** New (unsaved) cards open straight into edit mode. */
  startInEdit?: boolean;
  /** Called after a brand-new list is persisted (page drops the placeholder). */
  onCreated?: (tempId: string) => void;
  /** Called when a never-saved new card is cancelled (page drops the placeholder). */
  onCancelNew?: (tempId: string) => void;
  /** Called after a persisted list is deleted (page clears any active pointer to it). */
  onDeleted?: (id: string) => void;
}

const CARD_SX = { p: 2, border: 1, borderColor: 'divider', borderRadius: 1 } as const;

/**
 * One keyword-list editor card. Each non-builtin card owns its own save
 * lifecycle: a per-card **Save** persists immediately (POST for new, PATCH for
 * existing) and flips the card to a finalized read-only state with an **Edit**
 * button — there is no global batch save for lists. The built-in "Software
 * Engineering (default)" list is always read-only.
 */
export function KeywordListCard({
  list,
  startInEdit = false,
  onCreated,
  onCancelNew,
  onDeleted,
}: KeywordListCardProps) {
  const [createKeywordList, createState] = useCreateKeywordListMutation();
  const [updateKeywordList, updateState] = useUpdateKeywordListMutation();
  const [deleteKeywordList, deleteState] = useDeleteKeywordListMutation();

  const [mode, setMode] = useState<'view' | 'edit'>(startInEdit ? 'edit' : 'view');
  const [draft, setDraft] = useState<DraftKeywordList>(() => cloneDraftList(list));
  const [error, setError] = useState<string | null>(null);

  const saving = createState.isLoading || updateState.isLoading;
  const deleting = deleteState.isLoading;

  // ── Built-in: always read-only (name locked, tags static) ─────────────────
  if (list.isBuiltin) {
    return (
      <Box sx={CARD_SX}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
          <LockIcon fontSize="small" color="disabled" />
          <Typography variant="subtitle1">Software Engineering (default)</Typography>
          <Typography variant="caption" color="text.secondary">
            Built-in · read-only
          </Typography>
        </Stack>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
          {list.tags.map((tag) => (
            <Chip
              key={tag.text}
              size="small"
              color={tag.mode === 'include' ? 'success' : 'error'}
              icon={tag.mode === 'include' ? <AddIcon /> : <RemoveIcon />}
              label={tag.text}
            />
          ))}
        </Box>
      </Box>
    );
  }

  const mutateDraft = (fn: (d: DraftKeywordList) => void) => {
    setDraft((d) => {
      const copy = cloneDraftList(d);
      fn(copy);
      return copy;
    });
  };

  const enterEdit = () => {
    setDraft(cloneDraftList(list)); // reseed from the latest server state
    setError(null);
    setMode('edit');
  };

  const handleSave = async () => {
    const name = draft.name.trim();
    setError(null);
    try {
      if (list.isNew) {
        await createKeywordList({ name, tags: draft.tags }).unwrap();
        onCreated?.(list.id); // refetch will surface the persisted card
      } else {
        await updateKeywordList({ id: list.id, name, tags: draft.tags }).unwrap();
        setMode('view');
      }
    } catch (err) {
      setError(extractErrorMessage(err, 'Failed to save list'));
    }
  };

  const handleCancel = () => {
    if (list.isNew) {
      onCancelNew?.(list.id);
      return;
    }
    setDraft(cloneDraftList(list));
    setError(null);
    setMode('view');
  };

  const handleDelete = async () => {
    setError(null);
    try {
      await deleteKeywordList(list.id).unwrap();
      onDeleted?.(list.id);
    } catch (err) {
      setError(extractErrorMessage(err, 'Failed to delete list'));
    }
  };

  // ── Edit mode: Add-to-List input at the top, full width ───────────────────
  if (mode === 'edit') {
    return (
      <Box sx={CARD_SX}>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        <Box sx={{ width: '100%', mb: 2 }}>
          <SearchTagsInput
            value={draft.tags}
            placeholder="Add a keyword and press Enter — prefix with - to exclude"
            onAdd={(tag) => mutateDraft((d) => addTagToList(d, tag))}
            onRemove={(text) => mutateDraft((d) => removeTagFromList(d, text))}
            onToggleMode={(text) => mutateDraft((d) => toggleTagModeInList(d, text))}
          />
        </Box>
        <TextField
          label="List name"
          value={draft.name}
          onChange={(e) =>
            mutateDraft((d) => {
              d.name = e.target.value;
            })
          }
          size="small"
          fullWidth
          slotProps={{ htmlInput: { maxLength: 100 } }}
        />
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }}>
          <Button variant="contained" onClick={handleSave} disabled={saving || !draft.name.trim()}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
          <Button variant="text" onClick={handleCancel} disabled={saving}>
            Cancel
          </Button>
          <Box sx={{ flexGrow: 1 }} />
          {!list.isNew && (
            <Tooltip title="Delete list">
              <span>
                <IconButton
                  aria-label={`Delete ${list.name || 'list'}`}
                  onClick={handleDelete}
                  color="error"
                  disabled={deleting}
                >
                  <DeleteIcon />
                </IconButton>
              </span>
            </Tooltip>
          )}
        </Stack>
      </Box>
    );
  }

  // ── View (finalized) mode: read-only with an Edit button ──────────────────
  return (
    <Box sx={CARD_SX}>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
          {list.name || '(unnamed list)'}
        </Typography>
        <Button size="small" startIcon={<EditIcon />} onClick={enterEdit}>
          Edit
        </Button>
        <Tooltip title="Delete list">
          <span>
            <IconButton
              aria-label={`Delete ${list.name || 'list'}`}
              onClick={handleDelete}
              color="error"
              disabled={deleting}
            >
              <DeleteIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {list.tags.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No keywords yet — click Edit to add some.
          </Typography>
        ) : (
          list.tags.map((tag) => (
            <Chip
              key={tag.text}
              size="small"
              color={tag.mode === 'include' ? 'success' : 'error'}
              icon={tag.mode === 'include' ? <AddIcon /> : <RemoveIcon />}
              label={tag.text}
            />
          ))
        )}
      </Box>
    </Box>
  );
}
