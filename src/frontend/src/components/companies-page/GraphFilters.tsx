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
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS } from '../../constants/enrichment.ts';
import { FacetMultiSelect } from '../shared/filters/FacetMultiSelect.tsx';
import { KeywordFilterInput } from '../shared/filters/KeywordFilterInput.tsx';
import { TimeWindowSelect } from '../shared/filters/TimeWindowSelect.tsx';
import { MultiSelectAutocomplete } from '../shared/filters/MultiSelectAutocomplete.tsx';

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
        <KeywordFilterInput
          value={filters.searchTags}
          onAdd={(tag) => dispatch(addGraphSearchTag(tag))}
          onRemove={(text) => dispatch(removeGraphSearchTag(text))}
          onToggleMode={(text) => dispatch(toggleGraphSearchTagMode(text))}
          onClear={() => dispatch(setGraphSearchTags(undefined))}
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
          <FacetMultiSelect
            label="Category"
            options={categoryOptions}
            value={filters.category}
            onChange={(slugs) => dispatch(setGraphCategory(slugs))}
            tooltip="AI-enriched job category (choose any number). Jobs not yet enriched still appear."
          />
          <FacetMultiSelect
            label="Level"
            options={levelOptions}
            value={filters.level}
            onChange={(slugs) => dispatch(setGraphLevel(slugs))}
            tooltip="Choose any number; Entry also includes New Grad. Jobs not yet enriched still appear."
          />
        </Stack>
      </Stack>
    </Box>
  );
}
