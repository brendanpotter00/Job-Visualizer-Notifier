import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Box from '@mui/material/Box';
import AddIcon from '@mui/icons-material/Add';
import { KeywordListCard } from './KeywordListCard.tsx';
import type { SearchTag } from '../../types';
import type { DraftKeywordList } from './keywordListDraft.ts';

export interface KeywordListsEditorProps {
  lists: DraftKeywordList[];
  onAddList: () => void;
  onRename: (id: string, name: string) => void;
  onAddTag: (id: string, tag: SearchTag) => void;
  onRemoveTag: (id: string, text: string) => void;
  onToggleTagMode: (id: string, text: string) => void;
  onDelete: (id: string) => void;
}

/**
 * Card listing every keyword list: user lists (editable, by position) first,
 * then the read-only built-in "Software Engineering (default)" last. An "Add
 * list" button appends a new empty draft list.
 */
export function KeywordListsEditor({
  lists,
  onAddList,
  onRename,
  onAddTag,
  onRemoveTag,
  onToggleTagMode,
  onDelete,
}: KeywordListsEditorProps) {
  return (
    <Paper sx={{ p: 4 }}>
      <Typography variant="h6" gutterBottom>
        Keyword lists
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Named sets of include/exclude keywords. Pick one as the active list per
        page below; select it from the &quot;Keyword list&quot; dropdown on each
        page.
      </Typography>

      <Stack spacing={2}>
        {lists.map((list) => (
          <KeywordListCard
            key={list.id}
            list={list}
            onRename={onRename}
            onAddTag={onAddTag}
            onRemoveTag={onRemoveTag}
            onToggleTagMode={onToggleTagMode}
            onDelete={onDelete}
          />
        ))}
      </Stack>

      <Box sx={{ mt: 2 }}>
        <Button variant="outlined" size="small" startIcon={<AddIcon />} onClick={onAddList}>
          Add list
        </Button>
      </Box>
    </Paper>
  );
}
