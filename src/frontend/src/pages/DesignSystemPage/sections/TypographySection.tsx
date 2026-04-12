import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import { SectionWrapper } from '../components/SectionWrapper';
import { DS_TYPOGRAPHY, DS_FONT_FAMILY } from '../designTokens';

const SAMPLE_TEXT = 'The quick brown fox jumps over the lazy dog';

export function TypographySection() {
  return (
    <SectionWrapper title="Typography Scale" subtitle="Inter with aggressive negative letter-spacing at display sizes. Four-weight hierarchy: 400 body, 500 UI, 600 emphasis, 700 display.">
      <Box sx={{ display: 'flex', flexDirection: 'column' }}>
        {DS_TYPOGRAPHY.map((entry, index) => (
          <Box key={entry.role}>
            {index > 0 && (
              <Divider sx={{ borderColor: 'rgba(38, 37, 30, 0.08)', my: 3 }} />
            )}
            <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, gap: { xs: 1, md: 3 }, alignItems: { md: 'baseline' } }}>
              <Box sx={{ minWidth: 200, flexShrink: 0 }}>
                <Typography
                  sx={{
                    fontFamily: DS_FONT_FAMILY.mono,
                    fontSize: '0.75rem',
                    lineHeight: 1.67,
                    color: 'rgba(38, 37, 30, 0.55)',
                  }}
                >
                  {entry.role}
                </Typography>
                <Typography
                  sx={{
                    fontFamily: DS_FONT_FAMILY.mono,
                    fontSize: '0.69rem',
                    color: 'rgba(38, 37, 30, 0.4)',
                    lineHeight: 1.5,
                  }}
                >
                  {entry.sizePx}px / {entry.weight} / {entry.letterSpacing}
                </Typography>
              </Box>

              <Typography
                sx={{
                  fontFamily: entry.role.startsWith('Mono') ? DS_FONT_FAMILY.mono : undefined,
                  fontSize: entry.size,
                  fontWeight: entry.weight,
                  lineHeight: entry.lineHeight,
                  letterSpacing: entry.letterSpacing,
                  color: '#26251e',
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: entry.sizePx >= 40 ? 'normal' : 'nowrap',
                }}
              >
                {SAMPLE_TEXT}
              </Typography>
            </Box>
          </Box>
        ))}
      </Box>
    </SectionWrapper>
  );
}
