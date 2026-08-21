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
  setGraphCategory,
  setGraphLevel,
  setGraphSubcategory,
} from '../../features/filters/slices/graphFiltersSlice.ts';
import { selectGraphFilters } from '../../features/filters/selectors/graphFiltersSelectors.ts';
import { useGetFacetsQuery } from '../../features/jobs/jobsApi.ts';
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS } from '../../constants/enrichment.ts';
import { useSubcategoryRevealEnabled } from '../../features/settings/subcategoryReveal.tsx';
// FacetMultiSelect STAYS — it still backs the Level control below.
import { FacetMultiSelect } from '../shared/filters/FacetMultiSelect.tsx';
import { FacetTreeMultiSelect } from '../shared/filters/FacetTreeMultiSelect.tsx';
import { KeywordFilterInput } from '../shared/filters/KeywordFilterInput.tsx';
import { TimeWindowSelect } from '../shared/filters/TimeWindowSelect.tsx';
import { AsyncMultiSelectAutocomplete } from '../shared/filters/AsyncMultiSelectAutocomplete.tsx';

/**
 * Filter controls for the company hiring-trend page.
 *
 * These are the single source of truth: they drive both the graph and the job
 * list below it.
 */
export function GraphFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectGraphFilters);
  // Facet dropdown options are data-driven (seeded dimension tables); the
  // fallback constants cover the pre-fetch frame and an endpoint outage.
  const { data: facets } = useGetFacetsQuery();
  const revealSubcategories = useSubcategoryRevealEnabled();
  const categoryOptions = facets?.categories ?? FALLBACK_CATEGORIES;
  const levelOptions = facets?.levels ?? FALLBACK_LEVELS;
  // `?? []` rather than a fallback constant — the same gate as the Recent bar:
  // an empty catalog renders no chevron, so a warm facets cache plus a freshly
  // flipped flag cannot offer a parent that expands into nothing.
  const subcategoryOptions = revealSubcategories ? (facets?.subcategories ?? []) : [];

  // THIS IS THE PAGE `matchesSubcategory` ACTUALLY SERVES: the Companies trend
  // page filters entirely in the browser through `graphFiltersSelectors`, so
  // ticking a child here narrows the chart and the list below it with NO network
  // request. It is not optional even though the brief named only the Recent
  // page: `propagateSavedFilters` dispatches `setGraphSubcategory`
  // unconditionally, so this slice carries the field regardless — and a saved
  // subcategory filtering this page with no control to see or clear it is worse
  // than not shipping the control at all.

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

          {/*
            The label says "Job category" but the data model underneath is
            "category" all the way down — the `filters.category` slice field, the
            `setGraphCategory` action, the API param, and the DB column are all
            "category". This is a deliberate UI-only rename: users engage with a
            "Job category" filter far more than a bare "Category" one. It stays a category
            under the hood because these values will subdivide over time (e.g.
            "Software Engineering" → "Frontend SWE" / "Backend SWE"), at which
            point they read as categories again. Rename the label only — never the
            data model.

            NOTE: the LABEL below now reads "Job category" — that value comes
            from FE-CP-1, the copy-rename step, which ships in a SIBLING PR. The
            heading and tooltips still carry the pre-rename copy until that PR
            merges; resolve toward it when it does.
          */}
          <FacetTreeMultiSelect
            label="Job category"
            options={categoryOptions}
            childOptions={subcategoryOptions}
            value={filters.category}
            childValue={filters.subcategory}
            onChange={({ category, subcategory }) => {
              dispatch(setGraphCategory(category));
              dispatch(setGraphSubcategory(subcategory));
            }}
            tooltip="AI-enriched job category (choose any number). Only jobs matching your selection are shown."
          />
          <FacetMultiSelect
            label="Level"
            options={levelOptions}
            value={filters.level}
            onChange={(slugs) => dispatch(setGraphLevel(slugs))}
            tooltip="Choose any number; Entry also includes New Grad. Only jobs matching your selection are shown."
          />

          <AsyncMultiSelectAutocomplete
            label="Location"
            value={filters.location || []}
            onAdd={(loc) => dispatch(addGraphLocation(loc))}
            onRemove={(loc) => dispatch(removeGraphLocation(loc))}
          />
        </Stack>
      </Stack>
    </Box>
  );
}
