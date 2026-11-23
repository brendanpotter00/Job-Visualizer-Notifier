import { Fragment, useId, useState } from 'react';
import Box from '@mui/material/Box';
import { keyframes } from '@mui/material/styles';
import CheckIcon from '@mui/icons-material/Check';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { SUBCATEGORY_PARENT_SLUG } from '../../constants/enrichment';
import { VISUALLY_HIDDEN_SX } from '../../lib/visuallyHidden';
import type { FacetOption } from '../../types';
import { ChoiceChip } from './ChoiceChip';
import { toggleValue } from './onboardingModel';

const reveal = keyframes`
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
`;

const FIELDSET_RESET_SX = { border: 0, m: 0, p: 0, minWidth: 0 } as const;

export interface RoleQuestionProps {
  /** The six categories, in the app's order (facets, or the fallback set). */
  categories: FacetOption[];
  /**
   * The SWE specialties. Empty when the reveal flag is off or the catalog is
   * empty: Software Engineering is then a plain row with no accordion.
   */
  subcategories: FacetOption[];
  category: string[];
  subcategory: string[];
  onChange: (next: { category: string[]; subcategory: string[] }) => void;
  /** Speak a short status in the flow's polite live region. */
  onAnnounce: (message: string) => void;
}

/** Keep the picked slugs in the options' order, whatever order they were ticked in. */
function inOptionOrder(options: FacetOption[], picked: string[]): string[] {
  const set = new Set(picked);
  return options.filter((o) => set.has(o.slug)).map((o) => o.slug);
}

/**
 * Question 1: a checkbox list of the categories. Checking Software
 * Engineering opens its specialties right below it, in place (an accordion in
 * its own fieldset, named by its legend), so one more tap narrows the field.
 * Unchecking it clears them. Every other role is just that role.
 */
export function RoleQuestion({
  categories,
  subcategories,
  category,
  subcategory,
  onChange,
  onAnnounce,
}: RoleQuestionProps) {
  const specialtiesId = useId();
  const hintId = useId();
  // Animate the reveal only when the reader opens it, not when Back returns to
  // a step that already had it open.
  const [animateReveal, setAnimateReveal] = useState(false);
  const hasSpecialties = subcategories.length > 0;

  const toggleCategory = (slug: string, on: boolean) => {
    const isSwe = slug === SUBCATEGORY_PARENT_SLUG;
    onChange({
      category: inOptionOrder(categories, toggleValue(category, slug, on)),
      subcategory: isSwe && !on ? [] : subcategory,
    });
    if (isSwe && hasSpecialties) {
      setAnimateReveal(on);
      onAnnounce(
        on
          ? `${subcategories.length} specialties shown under Software Engineering.`
          : 'Specialties hidden.'
      );
    }
  };

  const toggleSpecialty = (slug: string, on: boolean) => {
    onChange({
      category,
      subcategory: inOptionOrder(subcategories, toggleValue(subcategory, slug, on)),
    });
  };

  return (
    <Box sx={{ borderTop: '1px solid', borderColor: 'divider' }}>
      {categories.map((option) => {
        const checked = category.includes(option.slug);
        const accordion = option.slug === SUBCATEGORY_PARENT_SLUG && hasSpecialties;
        const open = accordion && checked;
        return (
          <Fragment key={option.slug}>
            <Box
              component="label"
              sx={{
                position: 'relative',
                display: 'flex',
                alignItems: 'center',
                gap: '14px',
                minHeight: 56,
                px: '4px',
                borderBottom: '1px solid',
                borderColor: 'divider',
                cursor: 'pointer',
                '&:has(input:focus-visible) [data-box]': {
                  outline: '2px solid',
                  outlineColor: 'text.primary',
                  outlineOffset: '3px',
                },
              }}
            >
              <Box
                component="input"
                type="checkbox"
                checked={checked}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
                  toggleCategory(option.slug, event.target.checked)
                }
                aria-controls={open ? specialtiesId : undefined}
                aria-describedby={accordion ? hintId : undefined}
                sx={{
                  position: 'absolute',
                  inset: 0,
                  width: '100%',
                  height: '100%',
                  m: 0,
                  opacity: 0,
                  cursor: 'pointer',
                }}
              />
              <Box
                data-box
                aria-hidden
                sx={{
                  width: 22,
                  height: 22,
                  flex: 'none',
                  border: '2px solid',
                  borderColor: checked ? 'text.primary' : 'grey.600',
                  borderRadius: '4px',
                  bgcolor: checked ? 'text.primary' : 'transparent',
                  color: 'common.white',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {checked && <CheckIcon sx={{ fontSize: 16 }} />}
              </Box>
              <Box component="span" sx={{ flex: 1, fontSize: '1.0625rem' }}>
                {option.label}
                {accordion && (
                  <Box component="span" sx={VISUALLY_HIDDEN_SX}>
                    , {subcategories.length} specialties
                  </Box>
                )}
              </Box>
              {accordion && (
                // Only a chevron: it turns when the row opens. The count is in
                // the label for screen readers.
                <Box
                  component="span"
                  aria-hidden
                  data-testid="swe-chevron"
                  sx={{
                    display: 'inline-flex',
                    color: 'text.secondary',
                    transition: 'transform .18s ease',
                    transform: open ? 'rotate(180deg)' : 'none',
                    '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
                  }}
                >
                  <ExpandMoreIcon fontSize="small" />
                </Box>
              )}
            </Box>
            {accordion && (
              <Box component="span" id={hintId} sx={VISUALLY_HIDDEN_SX}>
                Checking it shows the specialties right below it.
              </Box>
            )}
            {open && (
              <Box
                id={specialtiesId}
                sx={{
                  position: 'relative',
                  borderBottom: '1px solid',
                  borderColor: 'divider',
                  pt: '12px',
                  pb: '16px',
                  pl: '40px',
                  '&::before': {
                    content: '""',
                    position: 'absolute',
                    left: '14px',
                    top: 0,
                    bottom: '14px',
                    borderLeft: '2px solid',
                    borderColor: 'text.primary',
                  },
                  animation: animateReveal ? `${reveal} .2s ease-out` : 'none',
                  '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
                }}
              >
                <Box component="fieldset" sx={FIELDSET_RESET_SX}>
                  <Box
                    component="legend"
                    sx={{ p: 0, mb: '10px', fontSize: '0.875rem', color: 'text.secondary' }}
                  >
                    <Box component="span" sx={VISUALLY_HIDDEN_SX}>
                      Software Engineering specialties.{' '}
                    </Box>
                    Select for more specific roles
                  </Box>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {subcategories.map((sub) => (
                      <ChoiceChip
                        key={sub.slug}
                        compact
                        label={sub.label}
                        checked={subcategory.includes(sub.slug)}
                        onChange={(on) => toggleSpecialty(sub.slug, on)}
                      />
                    ))}
                  </Box>
                </Box>
              </Box>
            )}
          </Fragment>
        );
      })}
    </Box>
  );
}
