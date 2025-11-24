import { Box, Stack } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  setListTimeWindow,
  addListLocation,
  removeListLocation,
  addListDepartment,
  removeListDepartment,
  addListRoleCategory,
  removeListRoleCategory,
  addListSearchTag,
  removeListSearchTag,
  toggleListSearchTagMode,
} from '../../features/filters/listFiltersSlice';
import { selectListFilters } from '../../features/filters/listFiltersSelectors';
import {
  selectAvailableLocations,
  selectAvailableDepartments,
} from '../../features/filters/commonFiltersSelectors';
import { syncListToGraph } from '../../features/filters/filtersSyncActions';
import { SearchTagsInput } from './shared/SearchTagsInput';
import { TimeWindowSelect } from './shared/TimeWindowSelect';
import { RoleCategorySelect } from './shared/RoleCategorySelect';
import { MultiSelectAutocomplete } from './shared/MultiSelectAutocomplete';
import { SyncFiltersButton } from './shared/SyncFiltersButton';

/**
 * Filter controls for the job list
 */
export function ListFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectListFilters);
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

          <RoleCategorySelect
            value={filters.roleCategory || []}
            onAdd={(cat) => dispatch(addListRoleCategory(cat))}
            onRemove={(cat) => dispatch(removeListRoleCategory(cat))}
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
        </Stack>

        <Stack direction="row" spacing={2} alignItems="center">
            <SyncFiltersButton direction="toGraph" onClick={() => dispatch(syncListToGraph())} />
          {/*  <SoftwareOnlyToggle*/}
          {/*  checked={filters.softwareOnly}*/}
          {/*  onChange={() => dispatch(toggleListSoftwareOnly())}*/}
          {/*/>*/}
        </Stack>
      </Stack>
    </Box>
  );
}
