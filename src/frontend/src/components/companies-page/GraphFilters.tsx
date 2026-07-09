import { Box, Stack } from '@mui/material';
import { RESPONSIVE } from '../../config/responsive';
import { useAppDispatch, useAppSelector } from '../../app/hooks.ts';
import {
  setGraphTimeWindow,
  addGraphSearchTag,
  removeGraphSearchTag,
  toggleGraphSearchTagMode,
  setGraphSearchTags,
  addGraphLocation,
  removeGraphLocation,
  addGraphDepartment,
  removeGraphDepartment,
  setGraphCategory,
  setGraphLevel,
} from '../../features/filters/slices/graphFiltersSlice.ts';
import { selectGraphFilters } from '../../features/filters/selectors/graphFiltersSelectors.ts';
import {
  selectAvailableLocations,
  selectAvailableDepartments,
} from '../../features/filters/selectors/commonFiltersSelectors.ts';
import { useGetFacetsQuery } from '../../features/jobs/jobsApi.ts';
import {
  FALLBACK_CATEGORIES,
  FALLBACK_LEVELS,
} from '../../constants/enrichment.ts';
import { SearchTagsInput } from '../shared/filters/SearchTagsInput.tsx';
import { FacetSelect } from '../shared/filters/FacetSelect.tsx';
import { TimeWindowSelect } from '../shared/filters/TimeWindowSelect.tsx';
import { MultiSelectAutocomplete } from '../shared/filters/MultiSelectAutocomplete.tsx';
import { KeywordListSelect } from '../shared/filters/KeywordListSelect.tsx';
import type { SearchTag } from '../../types';

/**
 * Filter controls for the company hiring-trend page.
 *
 * These are the single source of truth: they drive both the graph and the job
 * list below it.
 */
export function GraphFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectGraphFilters);
  const availableLocations = useAppSelector(selectAvailableLocations);
  const availableDepartments = useAppSelector(selectAvailableDepartments);
  // Facet dropdown options are data-driven (seeded dimension tables); the
  // fallback constants cover the pre-fetch frame and an endpoint outage.
  const { data: facets } = useGetFacetsQuery();
  const categoryOptions = facets?.categories ?? FALLBACK_CATEGORIES;
  const levelOptions = facets?.levels ?? FALLBACK_LEVELS;

  return (
    <Box sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
      <Stack
        spacing={RESPONSIVE.spacing.filterSpacing}
        sx={{
          // Mobile-only compaction of every filter control, mirroring the Recent
          // page (RecentJobsFilters). These xs-scoped descendant overrides shrink
          // the theme's 44px / 1rem controls to ~36px / 0.8125rem; every `sm` slot
          // restates the current desktop value, so it's a no-op at >= 600px and
          // never leaks to the shared controls' other consumers.
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
          onAdd={(tag) => dispatch(addGraphSearchTag(tag))}
          onRemove={(text) => dispatch(removeGraphSearchTag(text))}
          onToggleMode={(text) => dispatch(toggleGraphSearchTagMode(text))}
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={RESPONSIVE.spacing.filterSpacing}>
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
          <KeywordListSelect
            value={filters.searchTags}
            onChange={(tags: SearchTag[] | undefined) => dispatch(setGraphSearchTags(tags))}
          />
          <FacetSelect
            label="Category"
            options={categoryOptions}
            value={filters.category}
            onChange={(slug) => dispatch(setGraphCategory(slug))}
            tooltip="AI-enriched job category. Only enriched jobs match while a category is selected."
          />
          <FacetSelect
            label="Level"
            options={levelOptions}
            value={filters.level}
            onChange={(slug) => dispatch(setGraphLevel(slug))}
            tooltip="Entry includes New Grad roles. Only enriched jobs match while a level is selected."
          />
        </Stack>
      </Stack>
    </Box>
  );
}
