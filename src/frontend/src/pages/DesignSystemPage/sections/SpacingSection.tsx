import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { SectionWrapper } from '../components/SectionWrapper';
import { SubsectionTitle } from '../components/SubsectionTitle';
import { DS_SPACING_FINE, DS_SPACING_STANDARD, DS_FONT_FAMILY } from '../designTokens';

interface SpacingScaleProps {
  title: string;
  entries: { label: string; value: number }[];
}

function SpacingScale({ title, entries }: SpacingScaleProps) {
  return (
    <Box sx={{ mb: 4 }}>
      <SubsectionTitle>{title}</SubsectionTitle>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {entries.map((entry) => (
          <Box
            key={entry.label}
            sx={{ display: 'flex', alignItems: 'center', gap: 2 }}
          >
            <Typography
              sx={{
                fontFamily: DS_FONT_FAMILY.mono,
                fontSize: '0.75rem',
                color: 'rgba(38, 37, 30, 0.55)',
                width: 48,
                textAlign: 'right',
                flexShrink: 0,
              }}
            >
              {entry.label}
            </Typography>
            <Box
              sx={{
                height: 16,
                width: Math.max(entry.value * 3, 4),
                backgroundColor: '#f54e00',
                borderRadius: '2px',
                opacity: 0.7,
                transition: 'opacity 150ms ease',
                '&:hover': { opacity: 1 },
              }}
            />
          </Box>
        ))}
      </Box>
    </Box>
  );
}

export function SpacingSection() {
  return (
    <SectionWrapper title="Spacing System" subtitle="8px base unit with fine-grained sub-8px increments for micro-adjustments.">
      <SpacingScale title="Fine Scale (Sub-8px)" entries={DS_SPACING_FINE} />
      <SpacingScale title="Standard Scale" entries={DS_SPACING_STANDARD} />
    </SectionWrapper>
  );
}
