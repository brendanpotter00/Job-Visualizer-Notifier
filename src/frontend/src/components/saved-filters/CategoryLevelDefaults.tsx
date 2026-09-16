import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { FacetMultiSelect } from '../shared/filters/FacetMultiSelect.tsx';
import { SectionSaveButton } from './SectionSaveButton.tsx';
import { useGetFacetsQuery } from '../../features/jobs/jobsApi.ts';
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS } from '../../constants/enrichment.ts';

export interface CategoryLevelDefaultsProps {
  category: string[];
  level: string[];
  onChangeCategory: (slugs: string[]) => void;
  onChangeLevel: (slugs: string[]) => void;
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
 * NAMING: the "category" facet is surfaced to users as "Job Category"
 * (heading, label, save button). It previously read "Job title", which was
 * wrong on its face: these values subdivide (e.g. "Software Engineering" →
 * "Frontend" / "Backend"), so they read as categories, not titles. The data
 * model — the `category` prop/field, the API param, the DB column — stays
 * "category". Matches the live filter bars in GraphFilters.tsx /
 * RecentJobsFilters.tsx. Rename copy only — never the data model.
 */
export function CategoryLevelDefaults({
  category,
  level,
  onChangeCategory,
  onChangeLevel,
  dirty,
  saving,
  success,
  error,
  onSave,
}: CategoryLevelDefaultsProps) {
  const { data: facets } = useGetFacetsQuery();
  const categoryOptions = facets?.categories ?? FALLBACK_CATEGORIES;
  const levelOptions = facets?.levels ?? FALLBACK_LEVELS;

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
        <Typography variant="h6">Default job category &amp; level</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 4, pb: 4, pt: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Applied when you open either page. Both pages share these defaults. Only jobs matching
          your selection are shown.
        </Typography>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
          <FacetMultiSelect
            label="Job Category"
            options={categoryOptions}
            value={category}
            onChange={onChangeCategory}
            tooltip="AI-enriched job category (choose any number). Only jobs matching your selection are shown."
          />
          <FacetMultiSelect
            label="Level"
            options={levelOptions}
            value={level}
            onChange={onChangeLevel}
            tooltip="Choose any number; Entry also includes New Grad. Only jobs matching your selection are shown."
          />
        </Stack>

        <SectionSaveButton
          dirty={dirty}
          saving={saving}
          success={success}
          error={error}
          onSave={onSave}
          label="Save job category & level"
        />
      </AccordionDetails>
    </Accordion>
  );
}
