import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { SectionWrapper } from '../components/SectionWrapper';
import { DS_BORDER_RADIUS, DS_FONT_FAMILY } from '../designTokens';

export function BorderRadiusSection() {
  return (
    <SectionWrapper title="Border Radius" subtitle="From micro detail elements to full-pill shapes for badges and tags.">
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 3,
          alignItems: 'flex-end',
        }}
      >
        {DS_BORDER_RADIUS.map((entry) => (
          <Box
            key={entry.name}
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 1,
            }}
          >
            <Box
              sx={{
                width: entry.name === 'Full Pill' ? 96 : 64,
                height: 64,
                border: '2px solid #26251e',
                borderRadius: entry.value,
                backgroundColor: '#e6e5e0',
              }}
            />
            <Typography
              sx={{
                fontSize: '0.875rem',
                fontWeight: 600,
                color: '#26251e',
              }}
            >
              {entry.name}
            </Typography>
            <Typography
              sx={{
                fontFamily: DS_FONT_FAMILY.mono,
                fontSize: '0.69rem',
                color: 'rgba(38, 37, 30, 0.55)',
              }}
            >
              {entry.label}
            </Typography>
          </Box>
        ))}
      </Box>
    </SectionWrapper>
  );
}
