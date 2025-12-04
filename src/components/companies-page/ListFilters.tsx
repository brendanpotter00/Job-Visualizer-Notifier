import { Box, Stack } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks.ts';
import {
  setListTimeWindow,
  addListLocation,
  removeListLocation,
  addListDepartment,
  removeListDepartment,
  addListSearchTag,
  removeListSearchTag,
  toggleListSearchTagMode,
  toggleListSoftwareOnly,
} from '../../features/filters/slices/listFiltersSlice.ts';
import {
  selectListFilters,
  selectListSoftwareOnlyState,
} from '../../features/filters/selectors/listFiltersSelectors.ts';
import {
  selectAvailableLocations,
  selectAvailableDepartments,
} from '../../features/filters/selectors/commonFiltersSelectors.ts';
import { syncListToGraph } from '../../features/filters/syncActions.ts';
import { SearchTagsInput } from '../shared/filters/SearchTagsInput.tsx';
import { TimeWindowSelect } from '../shared/filters/TimeWindowSelect.tsx';
import { MultiSelectAutocomplete } from '../shared/filters/MultiSelectAutocomplete.tsx';
import { SyncFiltersButton } from '../shared/filters/SyncFiltersButton.tsx';
import { SoftwareOnlyToggle } from '../shared/filters/SoftwareOnlyToggle.tsx';

/**
 * Filter controls for the job list
 */
export function ListFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectListFilters);
  const softwareOnlyChecked = useAppSelector(selectListSoftwareOnlyState);
  const availableLocations = useAppSelector(selectAvailableLocations);
  const availableDepartments = useAppSelector(selectAvailableDepartments);

  return (
    <Box sx={{ mb: 3 }}>
      <Stack spacing={2}>
        <SearchTagsInput
          value={filters.searchTags || []}
          onAdd={(tag) => dispatch(addListSearchTag(tag))}
          onRemove={(text) => dispatch(removeListSearchTag(text))}
          onToggleMode={(text) => dispatch(toggleListSearchTagMode(text))}
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TimeWindowSelect
            value={filters.timeWindow}
            onChange={(tw) => dispatch(setListTimeWindow(tw))}
          />

          {availableLocations.length > 0 && (
            <MultiSelectAutocomplete
              label="Location"
              options={availableLocations}
              value={filters.location || []}
              onAdd={(loc) => dispatch(addListLocation(loc))}
              onRemove={(loc) => dispatch(removeListLocation(loc))}
            />
          )}

          {availableDepartments.length > 0 && (
            <MultiSelectAutocomplete
              label="Department"
              options={availableDepartments}
              value={filters.department || []}
              onAdd={(dept) => dispatch(addListDepartment(dept))}
              onRemove={(dept) => dispatch(removeListDepartment(dept))}
            />
          )}
          <SoftwareOnlyToggle
            checked={softwareOnlyChecked}
            onChange={() => dispatch(toggleListSoftwareOnly())}
            label="Software engineering roles only"
          />
        </Stack>

        <Stack direction="row" spacing={2} alignItems="center">
          <SyncFiltersButton direction="toGraph" onClick={() => dispatch(syncListToGraph())} />
        </Stack>
      </Stack>
    </Box>
  );
}
