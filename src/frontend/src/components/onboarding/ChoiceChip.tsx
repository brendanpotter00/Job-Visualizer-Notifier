import Box from '@mui/material/Box';
import CheckIcon from '@mui/icons-material/Check';

/** The check drawn on a picked chip, and the gap after it (px). */
const CHECK_SIZE = 12;
const CHECK_GAP = 4;

interface ChipSize {
  minHeight: number;
  /** Side padding of an unpicked chip (px). */
  paddingX: number;
  fontSize: string;
}

/** The answer chips: 44px tall, the touch-target floor. */
const REGULAR: ChipSize = { minHeight: 44, paddingX: 24, fontSize: '0.9375rem' };
/** The specialty chips under Software Engineering: 40px, a denser set of 17. */
const COMPACT: ChipSize = { minHeight: 40, paddingX: 20, fontSize: '0.875rem' };

export interface ChoiceChipProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** The smaller chip used for the SWE specialties. */
  compact?: boolean;
}

/**
 * A native checkbox drawn as a chip.
 *
 * A chip keeps ONE width, picked or not: the check (12px + a 4px gap) takes
 * the place of left padding, so a tap never pushes the next chip to a new
 * line. The real `<input type="checkbox">` covers the chip at zero opacity,
 * so the browser owns keyboard, focus and the checked state a screen reader
 * hears; the chip only draws it.
 */
export function ChoiceChip({ label, checked, onChange, compact = false }: ChoiceChipProps) {
  const size = compact ? COMPACT : REGULAR;
  return (
    <Box
      component="label"
      sx={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        gap: `${CHECK_GAP}px`,
        minHeight: size.minHeight,
        pl: `${checked ? size.paddingX - CHECK_SIZE - CHECK_GAP : size.paddingX}px`,
        pr: `${size.paddingX}px`,
        border: '1px solid',
        borderColor: checked ? 'text.primary' : 'grey.600',
        borderRadius: '4px',
        bgcolor: checked ? 'text.primary' : 'common.white',
        color: checked ? 'common.white' : 'text.primary',
        fontSize: size.fontSize,
        lineHeight: 1.2,
        cursor: 'pointer',
        userSelect: 'none',
        '&:hover': { borderColor: 'text.primary' },
        '&:has(input:focus-visible)': {
          outline: '2px solid',
          outlineColor: 'text.primary',
          outlineOffset: '2px',
        },
      }}
    >
      <Box
        component="input"
        type="checkbox"
        checked={checked}
        onChange={(event: React.ChangeEvent<HTMLInputElement>) => onChange(event.target.checked)}
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
      {checked && <CheckIcon sx={{ width: CHECK_SIZE, height: CHECK_SIZE, flex: 'none' }} />}
      <span>{label}</span>
    </Box>
  );
}
