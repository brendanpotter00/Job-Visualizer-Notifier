import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { FacetMultiSelect } from '../shared/filters/FacetMultiSelect.tsx';
import { SectionSaveButton } from './SectionSaveButton.tsx';
import { useGetFacetsQuery } from '../../features/jobs/jobsApi.ts';
import { companyCategoryOptions } from '../../config/companyCategories.ts';

export interface CompanyTypeDefaultsProps {
  companyCategory: string[];
  onChange: (slugs: string[]) => void;
  /** Section-save state/handlers (the per-section Save button). */
  dirty: boolean;
  saving: boolean;
  success: boolean;
  error: string | null;
  onSave: () => void;
}

/**
 * Default company types for Recent Job Postings. Unlike job category and level,
 * this one applies to the Recent page only: the trend page shows one company.
 * Same options as the live filter (facets, else the bundled list). An empty
 * selection means "no filter".
 *
 * The page renders this only when the saved-filters GET carried
 * `companyCategory`; an older backend does not know the field, and would 422 a
 * PUT that carried it.
 */
export function CompanyTypeDefaults({
  companyCategory,
  onChange,
  dirty,
  saving,
  success,
  error,
  onSave,
}: CompanyTypeDefaultsProps) {
  const { data: facets } = useGetFacetsQuery();
  const options = companyCategoryOptions(facets);

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
        <Typography variant="h6">Default company types</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 4, pb: 4, pt: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Applied when you open Recent Job Postings. Only jobs at these kinds of companies are
          shown.
        </Typography>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
          <FacetMultiSelect
            label="Company type"
            options={options}
            value={companyCategory}
            onChange={onChange}
          />
        </Stack>

        <SectionSaveButton
          dirty={dirty}
          saving={saving}
          success={success}
          error={error}
          onSave={onSave}
          label="Save company types"
        />
      </AccordionDetails>
    </Accordion>
  );
}
