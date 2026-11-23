import { useId, useMemo, useState } from 'react';
import Autocomplete from '@mui/material/Autocomplete';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import InputAdornment from '@mui/material/InputAdornment';
import TextField from '@mui/material/TextField';
import SearchIcon from '@mui/icons-material/Search';
import { useAppDispatch } from '../../app/hooks';
import type { LocationSearchResult } from '../../features/locations/locationsApi';
import { upsertLocationDescriptors } from '../../features/locations/locationCatalogSlice';
import { useLocationSearch } from '../../features/locations/useLocationSearch';
import { VISUALLY_HIDDEN_SX } from '../../lib/visuallyHidden';
import { ChoiceChip } from './ChoiceChip';
import { LOCATION_PRESETS, displayPlace, toggleValue } from './onboardingModel';

export interface LocationQuestionProps {
  /** Canonical location names picked so far. */
  locations: string[];
  onChange: (locations: string[]) => void;
  /** Speak a short status in the flow's polite live region. */
  onAnnounce: (message: string) => void;
}

/**
 * Question 3: six common places as chips, then a search over every canonical
 * location (the same debounced `GET /api/locations/search` the filter bars
 * use). A place picked from the search becomes one more chip after the
 * presets, already picked; unpicking it removes it.
 */
export function LocationQuestion({ locations, onChange, onAnnounce }: LocationQuestionProps) {
  const dispatch = useAppDispatch();
  const inputId = useId();
  const hintId = useId();
  const [inputValue, setInputValue] = useState('');
  const { results, isFetching, errorMessage, noOptionsText } = useLocationSearch(inputValue);

  const extras = locations.filter((name) => !LOCATION_PRESETS.includes(name));
  const chips = [...LOCATION_PRESETS, ...extras];
  const options = useMemo(
    () => (results ?? []).filter((r) => !locations.includes(r.canonicalName)),
    [results, locations]
  );

  const pick = (option: LocationSearchResult) => {
    // Cache the structured descriptor (as the filter bars do on add), so the
    // client-side location filter can resolve the pick hierarchically.
    dispatch(upsertLocationDescriptors([option]));
    onChange(toggleValue(locations, option.canonicalName, true));
    setInputValue('');
    onAnnounce(`${displayPlace(option.canonicalName)} added.`);
  };

  return (
    <>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {chips.map((name) => (
          <ChoiceChip
            key={name}
            label={displayPlace(name)}
            checked={locations.includes(name)}
            onChange={(on) => onChange(toggleValue(locations, name, on))}
          />
        ))}
      </Box>
      <Box sx={{ mt: '14px' }}>
        <Box component="label" htmlFor={inputId} sx={VISUALLY_HIDDEN_SX}>
          Search for another place
        </Box>
        <Autocomplete<LocationSearchResult, false, false, false>
          id={inputId}
          options={options}
          // Always empty: a pick becomes a chip above, and the field clears for
          // the next search.
          value={null}
          inputValue={inputValue}
          onInputChange={(_event, next, reason) => setInputValue(reason === 'reset' ? '' : next)}
          onChange={(_event, option) => {
            if (option) pick(option);
          }}
          getOptionLabel={(option) => displayPlace(option.canonicalName)}
          isOptionEqualToValue={(a, b) => a.canonicalName === b.canonicalName}
          // The server already filtered; re-filtering would hide results whose
          // label differs from the typed text.
          filterOptions={(x) => x}
          autoHighlight
          forcePopupIcon={false}
          loading={isFetching}
          loadingText="Searching places…"
          noOptionsText={noOptionsText}
          renderInput={(params) => (
            <TextField
              {...params}
              placeholder="City, state or country"
              error={errorMessage !== null}
              helperText={errorMessage ?? undefined}
              slotProps={{
                input: {
                  ...params.InputProps,
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                  ),
                  endAdornment: (
                    <>
                      {isFetching ? <CircularProgress color="inherit" size={18} /> : null}
                      {params.InputProps.endAdornment}
                    </>
                  ),
                },
                htmlInput: { ...params.inputProps, 'aria-describedby': hintId },
              }}
              sx={{
                '& .MuiOutlinedInput-root': { minHeight: 48, borderRadius: '8px' },
                '& .MuiOutlinedInput-notchedOutline': { borderColor: 'grey.600' },
              }}
            />
          )}
        />
        <Box component="span" id={hintId} sx={VISUALLY_HIDDEN_SX}>
          Type to see matches. Press Enter to add the first match.
        </Box>
      </Box>
    </>
  );
}
