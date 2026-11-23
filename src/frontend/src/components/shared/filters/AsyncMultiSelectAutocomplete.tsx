import { useMemo, useState } from 'react';
import { Autocomplete, TextField, Chip, CircularProgress } from '@mui/material';
import { getArrayDiff } from '../../../features/filters/utils/filterUtils.ts';
import { type LocationSearchResult } from '../../../features/locations/locationsApi.ts';
import { useLocationSearch } from '../../../features/locations/useLocationSearch.ts';
import { upsertLocationDescriptors } from '../../../features/locations/locationCatalogSlice.ts';
import { useAppDispatch } from '../../../app/hooks.ts';

export interface AsyncMultiSelectAutocompleteProps {
  label: string;
  value: string[];
  onAdd: (item: string) => void;
  onRemove: (item: string) => void;
  placeholder?: string;
  size?: 'small' | 'medium';
  minWidth?: number;
  /** Only return locations that currently have at least one OPEN job. */
  openOnly?: boolean;
  /** Max suggestions to request from the server. */
  limit?: number;
}

/**
 * Multi-select autocomplete backed by the public server-side location search
 * endpoint. Mirrors `MultiSelectAutocomplete` (string array, add/remove
 * callbacks) but sources its options from the debounced `useLocationSearch`
 * over the FULL canonical `locations` table rather than a static `options`
 * prop. Used by the Recent Jobs + company hiring-trend filter dropdowns and the
 * Saved Filters page — so a user can pick any location, even one no currently-
 * displayed job matches.
 *
 * On selection it caches the picked location's structured descriptor
 * (`upsertLocationDescriptors`) so the job-location filter can resolve it
 * hierarchically. Seeding on selection (not per keystroke) keeps the filtered-
 * jobs selectors from recomputing while the user is merely typing.
 *
 * A failed search must never be silent: the query's error is surfaced both as
 * the dropdown's no-options text and as the field's `helperText`, so an empty
 * dropdown is distinguishable from "the request failed" or "keep typing".
 */
export function AsyncMultiSelectAutocomplete({
  label,
  value,
  onAdd,
  onRemove,
  placeholder = `Search ${label.toLowerCase()}...`,
  size = 'small',
  minWidth = 240,
  openOnly,
  limit,
}: AsyncMultiSelectAutocompleteProps) {
  const dispatch = useAppDispatch();
  const [inputValue, setInputValue] = useState('');
  const {
    results: data,
    isFetching,
    errorMessage,
    noOptionsText,
  } = useLocationSearch(inputValue, { openOnly, limit });

  // Keep already-selected values present as options so their chips render and
  // stay removable even when they aren't in the latest search results.
  const options = useMemo(() => {
    const fromSearch = (data ?? []).map((r) => r.canonicalName);
    return Array.from(new Set([...value, ...fromSearch]));
  }, [data, value]);

  const handleChange = (_: unknown, newValue: string[]) => {
    if (!Array.isArray(newValue)) return;
    const { added, removed } = getArrayDiff(value, newValue);
    // Cache the structured descriptor of each newly-added location (it's in the
    // current search results) so the job filter can resolve it even after the
    // search cache evicts or its jobs load later. Seeding here — only on add —
    // keeps the filtered-jobs selectors from recomputing while merely typing.
    if (added.length > 0 && data) {
      const byName = new Map<string, LocationSearchResult>(data.map((r) => [r.canonicalName, r]));
      const addedRows = added
        .map((name) => byName.get(name))
        .filter((r): r is LocationSearchResult => r != null);
      if (addedRows.length > 0) dispatch(upsertLocationDescriptors(addedRows));
    }
    removed.forEach((item) => onRemove(item));
    added.forEach((item) => onAdd(item));
  };

  return (
    <Autocomplete
      multiple
      size={size}
      options={options}
      value={value}
      loading={isFetching}
      loadingText="Searching locations…"
      noOptionsText={noOptionsText}
      inputValue={inputValue}
      onInputChange={(_, next) => setInputValue(next)}
      onChange={handleChange}
      // Server already filtered; don't re-filter client-side (would hide
      // results whose label differs from the typed query).
      filterOptions={(x) => x}
      renderValue={(currentValue, getItemProps) =>
        currentValue.map((option, index) => {
          const { key, ...itemProps } = getItemProps({ index });
          return <Chip key={key} label={option} size="small" {...itemProps} />;
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={placeholder}
          error={errorMessage !== null}
          helperText={errorMessage ?? undefined}
          slotProps={{
            input: {
              ...params.InputProps,
              endAdornment: (
                <>
                  {isFetching ? <CircularProgress color="inherit" size={18} /> : null}
                  {params.InputProps.endAdornment}
                </>
              ),
            },
          }}
        />
      )}
      sx={{ minWidth }}
    />
  );
}
