import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';
import DeleteIcon from '@mui/icons-material/Delete';
import LockIcon from '@mui/icons-material/Lock';
import { Add as AddIcon, Remove as RemoveIcon } from '@mui/icons-material';
import { SearchTagsInput } from '../shared/filters/SearchTagsInput.tsx';
import type { SearchTag } from '../../types';
import type { DraftKeywordList } from './keywordListDraft.ts';

export interface KeywordListCardProps {
  list: DraftKeywordList;
  onRename: (id: string, name: string) => void;
  onAddTag: (id: string, tag: SearchTag) => void;
  onRemoveTag: (id: string, text: string) => void;
  onToggleTagMode: (id: string, text: string) => void;
  onDelete: (id: string) => void;
}

/**
 * One keyword-list editor card. User lists are fully editable (rename, add /
 * remove / toggle tags, delete). The built-in "Software Engineering (default)"
 * list is read-only: its name is locked and its tags render as static chips.
 */
export function KeywordListCard({
  list,
  onRename,
  onAddTag,
  onRemoveTag,
  onToggleTagMode,
  onDelete,
}: KeywordListCardProps) {
  if (list.isBuiltin) {
    return (
      <Box sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}>
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

  return (
    <Box sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <TextField
          label="List name"
          value={list.name}
          onChange={(e) => onRename(list.id, e.target.value)}
          size="small"
          fullWidth
          slotProps={{ htmlInput: { maxLength: 100 } }}
        />
        <Tooltip title="Delete list">
          <IconButton
            aria-label={`Delete ${list.name || 'list'}`}
            onClick={() => onDelete(list.id)}
            color="error"
          >
            <DeleteIcon />
          </IconButton>
        </Tooltip>
      </Stack>

      <SearchTagsInput
        value={list.tags}
        onAdd={(tag) => onAddTag(list.id, tag)}
        onRemove={(text) => onRemoveTag(list.id, text)}
        onToggleMode={(text) => onToggleTagMode(list.id, text)}
      />
    </Box>
  );
}
