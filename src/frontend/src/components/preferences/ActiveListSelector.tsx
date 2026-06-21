import { useId } from 'react';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import type { DraftKeywordList } from './keywordListDraft.ts';

/** Sentinel for the "no active list" (`null`) option in the selects. */
const NONE_VALUE = '__none__';

export interface ActiveListSelectorProps {
  /** Lists selectable as active: persisted user lists + the built-in, builtin last. */
  selectableLists: DraftKeywordList[];
  recentActiveKeywordListId: string | null;
  trendActiveKeywordListId: string | null;
  onChangeRecent: (id: string | null) => void;
  onChangeTrend: (id: string | null) => void;
}

function ActiveSelect({
  label,
  value,
  lists,
  onChange,
}: {
  label: string;
  value: string | null;
  lists: DraftKeywordList[];
  onChange: (id: string | null) => void;
}) {
  const labelId = useId();
  return (
    <FormControl size="small" sx={{ minWidth: 220 }}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select
        labelId={labelId}
        label={label}
        value={value ?? NONE_VALUE}
        onChange={(e) => onChange(e.target.value === NONE_VALUE ? null : e.target.value)}
      >
        <MenuItem value={NONE_VALUE}>None</MenuItem>
        {lists.map((list) => (
          <MenuItem key={list.id} value={list.id}>
            {list.isBuiltin ? 'Software Engineering (default)' : list.name || '(unnamed list)'}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

/**
 * Chooses the active keyword list for each page (Recent vs Trend). Only saved
 * lists and the built-in are selectable — a freshly added, unsaved list can be
 * made active after it is saved (it has no server id yet).
 */
export function ActiveListSelector({
  selectableLists,
  recentActiveKeywordListId,
  trendActiveKeywordListId,
  onChangeRecent,
  onChangeTrend,
}: ActiveListSelectorProps) {
  return (
    <Paper sx={{ p: 4 }}>
      <Typography variant="h6" gutterBottom>
        Active list per page
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        The keyword list applied by default on each page. Choose &quot;None&quot;
        for no keyword filtering.
      </Typography>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
        <ActiveSelect
          label="Recent Jobs active list"
          value={recentActiveKeywordListId}
          lists={selectableLists}
          onChange={onChangeRecent}
        />
        <ActiveSelect
          label="Company Trends active list"
          value={trendActiveKeywordListId}
          lists={selectableLists}
          onChange={onChangeTrend}
        />
      </Stack>
    </Paper>
  );
}
