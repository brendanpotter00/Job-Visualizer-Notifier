import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Box from '@mui/material/Box';
import AddIcon from '@mui/icons-material/Add';
import { KeywordListCard } from './KeywordListCard.tsx';
import type { DraftKeywordList } from './keywordListDraft.ts';

export interface KeywordListsEditorProps {
  /** All cards in display order: new (unsaved) first, then user lists, builtin last. */
  lists: DraftKeywordList[];
  onAddList: () => void;
  onCardCreated: (tempId: string) => void;
  onCardCancelNew: (tempId: string) => void;
  onCardDeleted: (id: string) => void;
}

/**
 * Card listing every keyword list. Each card saves itself (per-card Save /
 * Edit) — there is no global batch save here. "Add list" prepends a new draft
 * card at the top in edit mode.
 */
export function KeywordListsEditor({
  lists,
  onAddList,
  onCardCreated,
  onCardCancelNew,
  onCardDeleted,
}: KeywordListsEditorProps) {
  return (
    <Paper sx={{ p: 4 }}>
      <Typography variant="h6" gutterBottom>
        Keyword lists
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Named sets of include/exclude keywords. Each list saves on its own. Pick one as the active
        list above to apply it on all pages.
      </Typography>

      <Box sx={{ mb: 2 }}>
        <Button variant="outlined" size="small" startIcon={<AddIcon />} onClick={onAddList}>
          Add list
        </Button>
      </Box>

      <Stack spacing={2}>
        {lists.map((list) => (
          <KeywordListCard
            key={list.id}
            list={list}
            startInEdit={list.isNew}
            onCreated={onCardCreated}
            onCancelNew={onCardCancelNew}
            onDeleted={onCardDeleted}
          />
        ))}
      </Stack>
    </Paper>
  );
}
