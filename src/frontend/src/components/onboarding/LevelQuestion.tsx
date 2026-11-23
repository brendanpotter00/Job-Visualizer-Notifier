import Box from '@mui/material/Box';
import type { FacetOption } from '../../types';
import { ChoiceChip } from './ChoiceChip';
import { toggleValue } from './onboardingModel';

export interface LevelQuestionProps {
  /** The levels, in the app's order (facets, or the fallback set). */
  levels: FacetOption[];
  level: string[];
  onChange: (level: string[]) => void;
}

/**
 * Question 2: one chip per level. Entry also matches New Grad jobs when it
 * filters (the existing `entry ⊃ new_grad` expansion), so the answer is saved
 * unexpanded, exactly as the Level filter stores it.
 */
export function LevelQuestion({ levels, level, onChange }: LevelQuestionProps) {
  const toggle = (slug: string, on: boolean) => {
    const picked = new Set(toggleValue(level, slug, on));
    onChange(levels.filter((l) => picked.has(l.slug)).map((l) => l.slug));
  };
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
      {levels.map((option) => (
        <ChoiceChip
          key={option.slug}
          label={option.label}
          checked={level.includes(option.slug)}
          onChange={(on) => toggle(option.slug, on)}
        />
      ))}
    </Box>
  );
}
