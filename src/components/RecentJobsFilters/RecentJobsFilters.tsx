import { Box, Stack, Button } from '@mui/material';
import { useMemo, useCallback } from 'react';
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

  /**
   * Memoized company options for dropdown
   * Avoids recreating array on every render
   */
  const companyOptions = useMemo(
    () => availableCompanies.map((c) => c.name),
    [availableCompanies]
  );

  /**
   * Memoized selected company names
   * Converts company IDs to names for display
   */
  const selectedCompanyNames = useMemo(
    () =>
      (filters.company || []).map((id) => {
        const company = availableCompanies.find((c) => c.id === id);
        return company?.name || id;
      }),
    [filters.company, availableCompanies]
  );

  /**
   * Memoized handler for adding company filter
   * Avoids recreating function on every render
   */
  const handleAddCompany = useCallback(
    (name: string) => {
      const company = availableCompanies.find((c) => c.name === name);
      if (company) dispatch(addRecentJobsCompany(company.id));
    },
    [availableCompanies, dispatch]
  );

  /**
   * Memoized handler for removing company filter
   * Avoids recreating function on every render
   */
  const handleRemoveCompany = useCallback(
    (name: string) => {
      const company = availableCompanies.find((c) => c.name === name);
      if (company) dispatch(removeRecentJobsCompany(company.id));
    },
    [availableCompanies, dispatch]
  );

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
              options={companyOptions}
              value={selectedCompanyNames}
              onAdd={handleAddCompany}
              onRemove={handleRemoveCompany}
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
