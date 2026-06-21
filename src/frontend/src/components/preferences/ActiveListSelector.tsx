import { useId } from 'react';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import type { DraftKeywordList } from './keywordListDraft.ts';

/** Sentinel for the "no active list" (`null`) option in the select. */
const NONE_VALUE = '__none__';

export interface ActiveListSelectorProps {
  /** Lists selectable as active: persisted user lists + the built-in, builtin last. */
  selectableLists: DraftKeywordList[];
  /** The single active keyword list applied on every page (null = no filtering). */
  activeKeywordListId: string | null;
  onChange: (id: string | null) => void;
}

/**
 * Chooses the one active keyword list applied by default on **all** pages
 * (Recent Jobs and Company Trends share a single selection — they are not
 * configured separately). Only saved lists and the built-in are selectable; a
 * freshly added, unsaved list can be made active once it has been saved.
 */
export function ActiveListSelector({
  selectableLists,
  activeKeywordListId,
  onChange,
}: ActiveListSelectorProps) {
  const labelId = useId();
  return (
    <Paper sx={{ p: 4 }}>
      <Typography variant="h6" gutterBottom>
        Active keyword list
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        The keyword list applied by default on all pages. Choose &quot;None&quot; for no keyword
        filtering.
      </Typography>

      <FormControl size="small" sx={{ minWidth: 260 }}>
        <InputLabel id={labelId}>Active keyword list</InputLabel>
        <Select
          labelId={labelId}
          label="Active keyword list"
          value={activeKeywordListId ?? NONE_VALUE}
          onChange={(e) => onChange(e.target.value === NONE_VALUE ? null : e.target.value)}
        >
          <MenuItem value={NONE_VALUE}>None</MenuItem>
          {selectableLists.map((list) => (
            <MenuItem key={list.id} value={list.id}>
              {list.isBuiltin ? 'Software Engineering (default)' : list.name || '(unnamed list)'}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Paper>
  );
}
