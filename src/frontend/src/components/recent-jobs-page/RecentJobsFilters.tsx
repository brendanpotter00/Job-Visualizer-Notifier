import { Box, Stack, Button } from '@mui/material';
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
  setRecentJobsCategory,
  setRecentJobsLevel,
  setRecentJobsSubcategory,
} from '../../features/filters/slices/recentJobsFiltersSlice.ts';
import { selectRecentJobsFilters } from '../../features/filters/selectors/recentJobsSelectors.ts';
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
 * Filter controls for Recent Job Postings page.
 *
 * What is actually rendered: keywords (free text + saved keyword lists), time
 * window, job category, level, location, and Reset. The slice
 * also generates `toggle/setRecentJobsSoftwareOnly`, but
 * NOTHING dispatches them — there is no software-only control on this page; the
 * built-in "Software Engineering" keyword list in the keywords input is how a
 * reader gets that filter now.
 */
export function RecentJobsFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectRecentJobsFilters);
  // Facet dropdown options are data-driven (seeded dimension tables); the
  // fallback constants cover the pre-fetch frame and an endpoint outage.
  const { data: facets } = useGetFacetsQuery();
  const revealSubcategories = useSubcategoryRevealEnabled();
  const categoryOptions = facets?.categories ?? FALLBACK_CATEGORIES;
  const levelOptions = facets?.levels ?? FALLBACK_LEVELS;
  // `?? []` and NOT the fallback constant, deliberately. THIS SINGLE EXPRESSION
  // IS the shared contract's `flag && (facets?.subcategories?.length ?? 0) > 0`
  // gate: an empty catalog renders no child rows at all, so a warm one-hour facets
  // cache plus a freshly flipped flag cannot produce a parent row that expands
  // into nothing.
  const subcategoryOptions = revealSubcategories ? (facets?.subcategories ?? []) : [];

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
        <KeywordFilterInput
          value={filters.searchTags}
          onAdd={(tag) => dispatch(addRecentJobsSearchTag(tag))}
          onRemove={(text) => dispatch(removeRecentJobsSearchTag(text))}
          onToggleMode={(text) => dispatch(toggleRecentJobsSearchTagMode(text))}
          onClear={() => dispatch(setRecentJobsSearchTags(undefined))}
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={RESPONSIVE.spacing.filterSpacing}>
          <TimeWindowSelect
            value={filters.timeWindow}
            onChange={(tw) => dispatch(setRecentJobsTimeWindow(tw))}
          />

          {/*
            The label reads "Job Category" and the data model underneath is
            "category" all the way down — the `filters.category` slice field, the
            `setRecentJobsCategory` action, the API param, and the DB column are
            all "category". It previously read "Job title", which was wrong on its
            face and is about to get worse: these values subdivide (e.g.
            "Software Engineering" → "Frontend" / "Backend"), so they read as
            categories, not titles. Rename the copy only — never the data model.
          */}
          <FacetTreeMultiSelect
            label="Job Category"
            options={categoryOptions}
            childOptions={subcategoryOptions}
            value={filters.category}
            childValue={filters.subcategory}
            onChange={({ category, subcategory }) => {
              dispatch(setRecentJobsCategory(category));
              dispatch(setRecentJobsSubcategory(subcategory));
            }}
            tooltip="AI-enriched job category (choose any number). Only jobs matching your selection are shown."
          />
          <FacetMultiSelect
            label="Level"
            options={levelOptions}
            value={filters.level}
            onChange={(slugs) => dispatch(setRecentJobsLevel(slugs))}
            tooltip="Choose any number; Entry also includes New Grad. Only jobs matching your selection are shown."
          />

          <AsyncMultiSelectAutocomplete
            label="Location"
            value={filters.location || []}
            onAdd={(loc) => dispatch(addRecentJobsLocation(loc))}
            onRemove={(loc) => dispatch(removeRecentJobsLocation(loc))}
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
