import Box from '@mui/material/Box';
import type { FacetOption } from '../../types';
import { ChoiceChip } from './ChoiceChip';
import { toggleValue } from './onboardingModel';

export interface CompanyTypeQuestionProps {
  /** The company types, in display order (facets, or the bundled list). */
  options: FacetOption[];
  companyCategory: string[];
  onChange: (companyCategory: string[]) => void;
}

/**
 * Question 4: one chip per company type (Big Tech, AI Labs, ...). Saved as the
 * Recent page's Company type filter, which shows jobs at companies in ANY
 * picked type.
 */
export function CompanyTypeQuestion({ options, companyCategory, onChange }: CompanyTypeQuestionProps) {
  const toggle = (slug: string, on: boolean) => {
    const picked = new Set(toggleValue(companyCategory, slug, on));
    onChange(options.filter((o) => picked.has(o.slug)).map((o) => o.slug));
  };
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
      {options.map((option) => (
        <ChoiceChip
          key={option.slug}
          label={option.label}
          checked={companyCategory.includes(option.slug)}
          onChange={(on) => toggle(option.slug, on)}
        />
      ))}
    </Box>
  );
}
