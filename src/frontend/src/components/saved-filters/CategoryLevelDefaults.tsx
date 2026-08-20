import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { FacetMultiSelect } from '../shared/filters/FacetMultiSelect.tsx';
import { FacetTreeMultiSelect } from '../shared/filters/FacetTreeMultiSelect.tsx';
import { SectionSaveButton } from './SectionSaveButton.tsx';
import { useGetFacetsQuery } from '../../features/jobs/jobsApi.ts';
import { useSubcategoryRevealEnabled } from '../../features/settings/subcategoryReveal.tsx';
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS } from '../../constants/enrichment.ts';

export interface CategoryLevelDefaultsProps {
  category: string[];
  level: string[];
  onChangeCategory: (slugs: string[]) => void;
  onChangeLevel: (slugs: string[]) => void;
  /**
   * SWE subcategory defaults. OPTIONAL, and that is deliberate rather than
   * lazy: it lets this component land and typecheck on its own, before the
   * Saved Filters page has a `subcategory` field to give it and before the
   * backend column exists. With no handler the control degrades to exactly
   * today's flat select — no chevron, no children, nothing new on screen.
   *
   * Required props here would have forced this change and the page's into one
   * indivisible commit gated on a backend migration.
   */
  subcategory?: string[];
  onChangeSubcategory?: (slugs: string[]) => void;
  /** Section-save state/handlers (the per-section Save button). */
  dirty: boolean;
  saving: boolean;
  success: boolean;
  error: string | null;
  onSave: () => void;
}

/**
 * Shared default enrichment facets (category + level). Unlike time windows, a
 * single category list and a single level list apply to BOTH the Recent Jobs
 * and Company Hiring Trends pages (mirrors how default locations are shared).
 * Options are the data-driven facet catalog (GET /api/jobs/facets); the fallback
 * constants cover the pre-fetch frame and an endpoint outage, exactly as the
 * live filter bars do. An empty selection means "no filter" on that page.
 *
 * NAMING: the "category" facet is surfaced to users as "Job title" (heading,
 * label, save button). The data model — the `category` prop/field, the API
 * param, the DB column — stays "category"; this is a UI-only rename because
 * users click a "Job title" filter far more than a "Category" one, and the
 * values will subdivide over time (e.g. "Software Engineering" → "Frontend
 * SWE" / "Backend SWE") and read as categories again. Matches the live filter
 * bars in GraphFilters.tsx / RecentJobsFilters.tsx. Rename copy only — never
 * the data model.
 */
export function CategoryLevelDefaults({
  category,
  level,
  subcategory,
  onChangeCategory,
  onChangeLevel,
  onChangeSubcategory,
  dirty,
  saving,
  success,
  error,
  onSave,
}: CategoryLevelDefaultsProps) {
  const { data: facets } = useGetFacetsQuery();
  const revealSubcategories = useSubcategoryRevealEnabled();
  const categoryOptions = facets?.categories ?? FALLBACK_CATEGORIES;
  const levelOptions = facets?.levels ?? FALLBACK_LEVELS;
  // THREE conditions, all of them load-bearing:
  //   - no handler       -> the caller has nothing to store, so offering the
  //                         control would silently discard the selection;
  //   - flag off         -> the feature is not revealed yet;
  //   - `?? []`, NOT the fallback constant -> an empty facets catalog must
  //                         render NO chevron. This single expression IS the
  //                         shared contract's `flag && facets.length > 0` gate:
  //                         the facets query is cached for an hour with no
  //                         tags, so a warm pre-seed cache plus a freshly
  //                         flipped flag would otherwise render a parent row
  //                         that expands into nothing.
  const subcategoryOptions =
    onChangeSubcategory && revealSubcategories ? (facets?.subcategories ?? []) : [];

  return (
    <Accordion
      defaultExpanded
      disableGutters
      sx={{
        borderRadius: 1,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 4, py: 1 }}>
        <Typography variant="h6">Default job title &amp; level</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 4, pb: 4, pt: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Applied when you open either page. Both pages share these defaults. Jobs
          not yet enriched still appear.
        </Typography>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
          <FacetTreeMultiSelect
            label="Job category"
            options={categoryOptions}
            childOptions={subcategoryOptions}
            value={category}
            childValue={subcategory}
            onChange={({ category: nextCategory, subcategory: nextSubcategory }) => {
              onChangeCategory(nextCategory);
              onChangeSubcategory?.(nextSubcategory);
            }}
            tooltip="AI-enriched job category (choose any number). Jobs not yet enriched still appear."
          />
          <FacetMultiSelect
            label="Level"
            options={levelOptions}
            value={level}
            onChange={onChangeLevel}
            tooltip="Choose any number; Entry also includes New Grad. Jobs not yet enriched still appear."
          />
        </Stack>

        <SectionSaveButton
          dirty={dirty}
          saving={saving}
          success={success}
          error={error}
          onSave={onSave}
          label="Save job title & level"
        />
      </AccordionDetails>
    </Accordion>
  );
}
