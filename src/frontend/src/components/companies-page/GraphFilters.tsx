import { Box, Stack } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks.ts';
import {
  setGraphTimeWindow,
  addGraphSearchTag,
  removeGraphSearchTag,
  toggleGraphSearchTagMode,
  addGraphLocation,
  removeGraphLocation,
  addGraphDepartment,
  removeGraphDepartment,
  toggleGraphSoftwareOnly,
  toggleGraphRoleGroup,
  clearGraphRoleGroups,
} from '../../features/filters/slices/graphFiltersSlice.ts';
import {
  selectGraphFilters,
  selectGraphSoftwareOnlyState,
  selectGraphActiveRoleGroups,
} from '../../features/filters/selectors/graphFiltersSelectors.ts';
import {
  selectAvailableLocations,
  selectAvailableDepartments,
} from '../../features/filters/selectors/commonFiltersSelectors.ts';
import { syncGraphToList } from '../../features/filters/syncActions.ts';
import { SearchTagsInput } from '../shared/filters/SearchTagsInput.tsx';
import { TimeWindowSelect } from '../shared/filters/TimeWindowSelect.tsx';
import { MultiSelectAutocomplete } from '../shared/filters/MultiSelectAutocomplete.tsx';
import { SyncFiltersButton } from '../shared/filters/SyncFiltersButton.tsx';
import { SoftwareOnlyToggle } from '../shared/filters/SoftwareOnlyToggle.tsx';
import { RoleTagGroupFilter } from '../shared/filters/RoleTagGroupFilter.tsx';

/**
 * Filter controls for the graph visualization
 */
export function GraphFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectGraphFilters);
  const softwareOnlyChecked = useAppSelector(selectGraphSoftwareOnlyState);
  const activeRoleGroups = useAppSelector(selectGraphActiveRoleGroups);
  const availableLocations = useAppSelector(selectAvailableLocations);
  const availableDepartments = useAppSelector(selectAvailableDepartments);

  return (
    <Box sx={{ mb: 3 }}>
      <Stack spacing={2}>
        <SearchTagsInput
          value={filters.searchTags || []}
          onAdd={(tag) => dispatch(addGraphSearchTag(tag))}
          onRemove={(text) => dispatch(removeGraphSearchTag(text))}
          onToggleMode={(text) => dispatch(toggleGraphSearchTagMode(text))}
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} flexWrap="wrap">
          <TimeWindowSelect
            value={filters.timeWindow}
            onChange={(tw) => dispatch(setGraphTimeWindow(tw))}
          />

          {availableLocations.length > 0 && (
            <MultiSelectAutocomplete
              label="Location"
              options={availableLocations}
              value={filters.location || []}
              onAdd={(loc) => dispatch(addGraphLocation(loc))}
              onRemove={(loc) => dispatch(removeGraphLocation(loc))}
            />
          )}
          {availableDepartments.length > 0 && (
            <MultiSelectAutocomplete
              label="Department"
              options={availableDepartments}
              value={filters.department || []}
              onAdd={(dept) => dispatch(addGraphDepartment(dept))}
              onRemove={(dept) => dispatch(removeGraphDepartment(dept))}
            />
          )}
          <RoleTagGroupFilter
            activeGroups={activeRoleGroups}
            onToggle={(groupId) => dispatch(toggleGraphRoleGroup(groupId))}
            onClear={() => dispatch(clearGraphRoleGroups())}
          />
          <SoftwareOnlyToggle
            checked={softwareOnlyChecked}
            onChange={() => dispatch(toggleGraphSoftwareOnly())}
            label="Software engineering roles only"
          />
        </Stack>

        <Stack direction="row" spacing={2} alignItems="center">
          <SyncFiltersButton direction="toList" onClick={() => dispatch(syncGraphToList())} />
        </Stack>
      </Stack>
    </Box>
  );
}
