import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';

export interface CompanyChipGridItem {
  id: string;
  name: string;
}

export interface CompanyChipGridProps {
  companies: CompanyChipGridItem[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
}

/**
 * Flex-wrapping grid of Chip toggles, one per company. Filled+primary when
 * selected, outlined+default otherwise. Parent decides via `onToggle`
 * whether the click should add or remove.
 */
export function CompanyChipGrid({
  companies,
  selectedIds,
  onToggle,
}: CompanyChipGridProps) {
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
      {companies.map((c) => {
        const selected = selectedIds.has(c.id);
        return (
          <Chip
            key={c.id}
            label={c.name}
            onClick={() => onToggle(c.id)}
            color={selected ? 'primary' : 'default'}
            variant={selected ? 'filled' : 'outlined'}
            size="small"
            data-testid={`browse-chip-${c.name}`}
            aria-pressed={selected}
            clickable
          />
        );
      })}
    </Box>
  );
}
