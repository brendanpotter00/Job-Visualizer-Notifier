import { Box, Stack, Button } from '@mui/material';
import { useMemo, useCallback } from 'react';
import { RESPONSIVE } from '../../config/responsive';
import { useAppDispatch, useAppSelector } from '../../app/hooks.ts';
import {
  setRecentJobsTimeWindow,
  addRecentJobsLocation,
  removeRecentJobsLocation,
  addRecentJobsSearchTag,
  removeRecentJobsSearchTag,
  toggleRecentJobsSearchTagMode,
  setRecentJobsSearchTags,
  resetRecentJobsFilters,
  addRecentJobsCompany,
  removeRecentJobsCompany,
} from '../../features/filters/slices/recentJobsFiltersSlice.ts';
import {
  selectRecentJobsFilters,
  selectRecentAvailableLocations,
  selectRecentAvailableCompanies,
} from '../../features/filters/selectors/recentJobsSelectors.ts';
import { SearchTagsInput } from '../shared/filters/SearchTagsInput.tsx';
import { TimeWindowSelect } from '../shared/filters/TimeWindowSelect.tsx';
import { MultiSelectAutocomplete } from '../shared/filters/MultiSelectAutocomplete.tsx';
import { KeywordListSelect } from '../shared/filters/KeywordListSelect.tsx';
import type { SearchTag } from '../../types';

/**
 * Filter controls for Recent Job Postings page
 * Subset of filters: time window, location, search tags, software-only
 * Excludes: department, role category
 */
export function RecentJobsFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectRecentJobsFilters);
  const availableLocations = useAppSelector(selectRecentAvailableLocations);
  const availableCompanies = useAppSelector(selectRecentAvailableCompanies);

  /**
   * Memoized company options for dropdown
   * Avoids recreating array on every render
   */
  const companyOptions = useMemo(() => availableCompanies.map((c) => c.name), [availableCompanies]);

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
    <Box sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
      <Stack
        spacing={RESPONSIVE.spacing.filterSpacing}
        sx={{
          // Mobile-only compaction of every filter control (search input + the
          // four selects/autocompletes). The theme floors form controls at 44px
          // (on .MuiTextField-root / the Select root) with 1rem text; these
          // xs-scoped descendant overrides shrink them to ~36px / 0.8125rem.
          // Every `sm` slot restates the current desktop value, so this is a
          // no-op at >= 600px and never leaks to the shared components' other
          // consumers (companies-page GraphFilters, saved-filters, etc.) — the
          // overrides live only on this Stack's subtree.
          '& .MuiTextField-root': { minHeight: RESPONSIVE.control.minHeight },
          '& .MuiOutlinedInput-root': { minHeight: RESPONSIVE.control.minHeight },
          '& .MuiInputBase-input': {
            fontSize: RESPONSIVE.control.fontSize,
            paddingTop: RESPONSIVE.control.inputPaddingY,
            paddingBottom: RESPONSIVE.control.inputPaddingY,
          },
          '& .MuiInputLabel-root': { fontSize: RESPONSIVE.control.fontSize },
        }}
      >
        <SearchTagsInput
          value={filters.searchTags || []}
          onAdd={(tag) => dispatch(addRecentJobsSearchTag(tag))}
          onRemove={(text) => dispatch(removeRecentJobsSearchTag(text))}
          onToggleMode={(text) => dispatch(toggleRecentJobsSearchTagMode(text))}
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={RESPONSIVE.spacing.filterSpacing}>
          <TimeWindowSelect
            value={filters.timeWindow}
            onChange={(tw) => dispatch(setRecentJobsTimeWindow(tw))}
          />

          <MultiSelectAutocomplete
            label="Company"
            options={companyOptions}
            value={selectedCompanyNames}
            onAdd={handleAddCompany}
            onRemove={handleRemoveCompany}
          />

          <MultiSelectAutocomplete
            label="Location"
            options={availableLocations}
            value={filters.location || []}
            onAdd={(loc) => dispatch(addRecentJobsLocation(loc))}
            onRemove={(loc) => dispatch(removeRecentJobsLocation(loc))}
          />

          <KeywordListSelect
            value={filters.searchTags}
            onChange={(tags: SearchTag[] | undefined) => dispatch(setRecentJobsSearchTags(tags))}
          />
        </Stack>

        <Stack direction="row" spacing={2}>
          <Button
            variant="outlined"
            size="small"
            onClick={() => dispatch(resetRecentJobsFilters())}
            sx={{
              // Shrink the Reset button on mobile too (kept >= 36px so it stays
              // an easy tap target); sm restates the theme's 44px floor, 16px
              // horizontal padding, and small-button 0.8125rem font.
              minHeight: RESPONSIVE.control.minHeight,
              px: { xs: 1.5, sm: 2 },
              fontSize: RESPONSIVE.control.buttonFontSize,
            }}
          >
            Reset Filters
          </Button>
        </Stack>
      </Stack>
    </Box>
  );
}
