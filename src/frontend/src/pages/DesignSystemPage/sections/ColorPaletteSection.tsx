import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { SectionWrapper } from '../components/SectionWrapper';
import { SubsectionTitle } from '../components/SubsectionTitle';
import { ColorSwatch } from '../components/ColorSwatch';
import { DS_COLORS, DS_FONT_FAMILY } from '../designTokens';

const SURFACE_GRADIENT = ['#f7f7f4', '#f2f1ed', '#ebeae5', '#e6e5e0', '#e1e0db'];

export function ColorPaletteSection() {
  return (
    <SectionWrapper title="Color Palette" subtitle="Warm-shifted colors with oklab-space borders and perceptually uniform edge treatment.">
      {DS_COLORS.map((group) => (
        <Box key={group.groupName} sx={{ mb: 5 }}>
          <Typography
            component="h3"
            sx={{
              fontSize: '1.63rem',
              fontWeight: 700,
              lineHeight: 1.23,
              letterSpacing: '-0.625px',
              color: '#26251e',
              mb: 2,
            }}
          >
            {group.groupName}
          </Typography>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: {
                xs: 'repeat(2, 1fr)',
                sm: 'repeat(3, 1fr)',
                md: 'repeat(4, 1fr)',
                lg: 'repeat(5, 1fr)',
              },
              gap: 2,
            }}
          >
            {group.colors.map((color) => (
              <ColorSwatch key={color.name} {...color} />
            ))}
          </Box>
        </Box>
      ))}

      <Box sx={{ mt: 4 }}>
        <SubsectionTitle>Surface Gradient</SubsectionTitle>
        <Box
          sx={{
            display: 'flex',
            borderRadius: '8px',
            overflow: 'hidden',
            border: '1px solid rgba(38, 37, 30, 0.1)',
            height: 48,
          }}
        >
          {SURFACE_GRADIENT.map((color, i) => (
            <Box
              key={color}
              sx={{
                flex: 1,
                backgroundColor: color,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Typography
                sx={{
                  fontFamily: DS_FONT_FAMILY.mono,
                  fontSize: '0.625rem',
                  color: '#26251e',
                  opacity: 0.6,
                }}
              >
                {100 + i * 100}
              </Typography>
            </Box>
          ))}
        </Box>
      </Box>
    </SectionWrapper>
  );
}
