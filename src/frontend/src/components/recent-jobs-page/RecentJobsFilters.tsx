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
  setRecentJobsCompanyCategory,
} from '../../features/filters/slices/recentJobsFiltersSlice.ts';
import { selectRecentJobsFilters } from '../../features/filters/selectors/recentJobsSelectors.ts';
import { useGetFacetsQuery } from '../../features/jobs/jobsApi.ts';
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS } from '../../constants/enrichment.ts';
import { companyCategoryOptions } from '../../config/companyCategories.ts';
import { useSubcategoryRevealEnabled } from '../../features/settings/subcategoryReveal.tsx';
// FacetMultiSelect backs the Level and Company type controls below.
import { FacetMultiSelect } from '../shared/filters/FacetMultiSelect.tsx';
import { FacetTreeMultiSelect } from '../shared/filters/FacetTreeMultiSelect.tsx';
import { KeywordFilterInput } from '../shared/filters/KeywordFilterInput.tsx';
import { TimeWindowSelect } from '../shared/filters/TimeWindowSelect.tsx';
import { AsyncMultiSelectAutocomplete } from '../shared/filters/AsyncMultiSelectAutocomplete.tsx';
import { SaveDefaultSearchButton } from './SaveDefaultSearchButton.tsx';

/**
 * Reset Filters and Save default search share one look: outlined, small, and
 * shrunk on mobile (kept >= 36px so each stays an easy tap target). The `sm`
 * slots restate the theme's 44px floor, 16px horizontal padding and the small
 * button's 0.8125rem font. The keyboard focus ring is drawn as an outline,
 * because the default focus ripple is faint on a white outlined button.
 */
const FILTER_ACTION_BUTTON_SX = {
  minHeight: RESPONSIVE.control.minHeight,
  px: { xs: 1.5, sm: 2 },
  fontSize: RESPONSIVE.control.buttonFontSize,
  '&.Mui-focusVisible': { outline: '2px solid', outlineColor: 'text.primary', outlineOffset: '2px' },
} as const;

/**
 * Filter controls for Recent Job Postings page.
 *
 * What is actually rendered: keywords (free text + saved keyword lists), time
 * window, job category, level, company type, location, Reset, and Save default
 * search. The slice
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
  // Never empty: the server's list, else the bundled one (an older backend or
  // a stale facets cache omits it). A selected type always keeps its label.
  const companyTypeOptions = companyCategoryOptions(facets);

  return (
    <Box sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
      <Stack
        spacing={RESPONSIVE.spacing.filterSpacing}
        sx={{
          // Mobile-only compaction of every filter control (search input + the
          // five selects/autocompletes). The theme floors form controls at 44px
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

        {/* Wraps instead of overflowing. Five controls need about 964px in one
            row, so from 600px up to about 1280px the row used to run off the
            right edge and scroll the whole page sideways. `useFlexGap` keeps
            the spacing right on a wrapped line. In the xs column, wrap does
            nothing. */}
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={RESPONSIVE.spacing.filterSpacing}
          useFlexGap
          flexWrap="wrap"
          data-testid="recent-jobs-filter-row"
        >
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
          />
          <FacetMultiSelect
            label="Level"
            options={levelOptions}
            value={filters.level}
            onChange={(slugs) => dispatch(setRecentJobsLevel(slugs))}
          />
          {/* Sentence case, unlike its "Job Category" neighbour: house style.
              Renaming that label is out of scope. */}
          <FacetMultiSelect
            label="Company type"
            options={companyTypeOptions}
            value={filters.companyCategory}
            onChange={(slugs) => dispatch(setRecentJobsCompanyCategory(slugs))}
          />

          <AsyncMultiSelectAutocomplete
            label="Location"
            value={filters.location || []}
            onAdd={(loc) => dispatch(addRecentJobsLocation(loc))}
            onRemove={(loc) => dispatch(removeRecentJobsLocation(loc))}
          />
        </Stack>

        {/* Wraps on a phone: a confirmation beside the buttons drops to the
            next line instead of squeezing them. */}
        <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center' }}>
          <Button
            variant="outlined"
            size="small"
            onClick={() => dispatch(resetRecentJobsFilters())}
            sx={FILTER_ACTION_BUTTON_SX}
          >
            Reset Filters
          </Button>
          <SaveDefaultSearchButton sx={FILTER_ACTION_BUTTON_SX} />
        </Stack>
      </Stack>
    </Box>
  );
}
