import { Box, Stack } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  setGraphTimeWindow,
  addGraphSearchTag,
  removeGraphSearchTag,
  toggleGraphSearchTagMode,
  addGraphLocation,
  removeGraphLocation,
  addGraphDepartment,
  removeGraphDepartment,
  addGraphRoleCategory,
  removeGraphRoleCategory,
} from '../../features/filters/graphFiltersSlice';
import { selectGraphFilters } from '../../features/filters/graphFiltersSelectors';
import {
  selectAvailableLocations,
  selectAvailableDepartments,
} from '../../features/filters/commonFiltersSelectors';
import { syncGraphToList } from '../../features/filters/filtersSyncActions';
import { SearchTagsInput } from './shared/SearchTagsInput';
import { TimeWindowSelect } from './shared/TimeWindowSelect';
import { RoleCategorySelect } from './shared/RoleCategorySelect';
import { MultiSelectAutocomplete } from './shared/MultiSelectAutocomplete';
import { SyncFiltersButton } from './shared/SyncFiltersButton';

/**
 * Filter controls for the graph visualization
 */
export function GraphFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectGraphFilters);
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

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
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
          <RoleCategorySelect
            value={filters.roleCategory || []}
            onAdd={(cat) => dispatch(addGraphRoleCategory(cat))}
            onRemove={(cat) => dispatch(removeGraphRoleCategory(cat))}
          />
        </Stack>

        <Stack direction="row" spacing={2} alignItems="center">
          <SyncFiltersButton direction="toList" onClick={() => dispatch(syncGraphToList())} />
          {/*  <SoftwareOnlyToggle*/}
          {/*  checked={filters.softwareOnly}*/}
          {/*  onChange={() => dispatch(toggleGraphSoftwareOnly())}*/}
          {/*/>*/}
        </Stack>
      </Stack>
    </Box>
  );
}
