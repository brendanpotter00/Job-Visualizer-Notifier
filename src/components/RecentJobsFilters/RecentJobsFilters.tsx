import { Box, Stack, Button } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  setRecentJobsTimeWindow,
  addRecentJobsLocation,
  removeRecentJobsLocation,
  addRecentJobsSearchTag,
  removeRecentJobsSearchTag,
  toggleRecentJobsSearchTagMode,
  toggleRecentJobsSoftwareOnly,
  resetRecentJobsFilters,
  addRecentJobsCompany,
  removeRecentJobsCompany,
} from '../../features/filters/recentJobsFiltersSlice';
import {
  selectRecentJobsFilters,
  selectRecentAvailableLocations,
  selectRecentSoftwareOnlyState,
  selectRecentAvailableCompanies,
} from '../../features/filters/recentJobsSelectors';
import { SearchTagsInput } from '../filters/shared/SearchTagsInput';
import { TimeWindowSelect } from '../filters/shared/TimeWindowSelect';
import { MultiSelectAutocomplete } from '../filters/shared/MultiSelectAutocomplete';
import { SoftwareOnlyToggle } from '../filters/shared/SoftwareOnlyToggle';

/**
 * Filter controls for Recent Job Postings page
 * Subset of filters: time window, location, search tags, software-only
 * Excludes: department, role category
 */
export function RecentJobsFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectRecentJobsFilters);
  const softwareOnlyChecked = useAppSelector(selectRecentSoftwareOnlyState);
  const availableLocations = useAppSelector(selectRecentAvailableLocations);
  const availableCompanies = useAppSelector(selectRecentAvailableCompanies);

  return (
    <Box sx={{ mb: 3 }}>
      <Stack spacing={2}>
        <SearchTagsInput
          value={filters.searchTags || []}
          onAdd={(tag) => dispatch(addRecentJobsSearchTag(tag))}
          onRemove={(text) => dispatch(removeRecentJobsSearchTag(text))}
          onToggleMode={(text) => dispatch(toggleRecentJobsSearchTagMode(text))}
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TimeWindowSelect
            value={filters.timeWindow}
            onChange={(tw) => dispatch(setRecentJobsTimeWindow(tw))}
          />

          {availableCompanies.length > 0 && (
            <MultiSelectAutocomplete
              label="Company"
              options={availableCompanies.map((c) => c.name)}
              value={(filters.company || []).map((companyId) => {
                const company = availableCompanies.find((c) => c.id === companyId);
                return company?.name || companyId;
              })}
              onAdd={(companyName) => {
                const company = availableCompanies.find((c) => c.name === companyName);
                if (company) dispatch(addRecentJobsCompany(company.id));
              }}
              onRemove={(companyName) => {
                const company = availableCompanies.find((c) => c.name === companyName);
                if (company) dispatch(removeRecentJobsCompany(company.id));
              }}
            />
          )}

          {availableLocations.length > 0 && (
            <MultiSelectAutocomplete
              label="Location"
              options={availableLocations}
              value={filters.location || []}
              onAdd={(loc) => dispatch(addRecentJobsLocation(loc))}
              onRemove={(loc) => dispatch(removeRecentJobsLocation(loc))}
            />
          )}

          <SoftwareOnlyToggle
            checked={softwareOnlyChecked}
            onChange={() => dispatch(toggleRecentJobsSoftwareOnly())}
            label="Software engineering roles only"
          />
        </Stack>

        <Stack direction="row" spacing={2}>
          <Button
            variant="outlined"
            size="small"
            onClick={() => dispatch(resetRecentJobsFilters())}
          >
            Reset Filters
          </Button>
        </Stack>
      </Stack>
    </Box>
  );
}
