import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { SectionWrapper } from '../components/SectionWrapper';
import { SubsectionTitle } from '../components/SubsectionTitle';
import { DS_BUTTONS, DS_FONT_FAMILY } from '../designTokens';

const BADGES = [
  { label: 'Thinking', color: '#dfa88f' },
  { label: 'Grep', color: '#9fc9a2' },
  { label: 'Read', color: '#9fbbe0' },
  { label: 'Edit', color: '#c0a8dd' },
];

const CARD_TITLE_SX = {
  fontSize: '1.38rem',
  fontWeight: 700,
  letterSpacing: '-0.25px',
  color: '#26251e',
  mb: 1,
} as const;

const CARD_BODY_SX = {
  color: 'rgba(38, 37, 30, 0.55)',
  lineHeight: 1.5,
} as const;

export function ComponentsSection() {
  return (
    <SectionWrapper title="Components" subtitle="Buttons, cards, badges, code blocks, and inputs styled with the design system tokens.">
      <ButtonsSubsection />
      <CardsSubsection />
      <BadgesSubsection />
      <CodeBlockSubsection />
      <InputSubsection />
    </SectionWrapper>
  );
}

function ButtonsSubsection() {
  return (
    <Box sx={{ mt: 5 }}>
      <SubsectionTitle>Buttons</SubsectionTitle>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center' }}>
        {DS_BUTTONS.map((btn) => (
          <Box
            key={btn.name}
            component="button"
            sx={{
              fontSize: btn.fontSize,
              fontWeight: btn.fontWeight,
              backgroundColor: btn.bg,
              color: btn.text,
              padding: btn.padding,
              borderRadius: btn.borderRadius,
              border: 'none',
              cursor: 'pointer',
              transition: 'color 150ms ease',
              lineHeight: 1.33,
              '&:hover': { color: btn.hoverText },
            }}
          >
            {btn.name}
          </Box>
        ))}
      </Box>
      <Box sx={{ mt: 2, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {DS_BUTTONS.map((btn) => (
          <Typography
            key={btn.name}
            sx={{
              fontFamily: DS_FONT_FAMILY.mono,
              fontSize: '0.69rem',
              color: 'rgba(38, 37, 30, 0.4)',
              backgroundColor: 'rgba(38, 37, 30, 0.04)',
              px: 1,
              py: 0.5,
              borderRadius: '4px',
            }}
          >
            {btn.name}: {btn.fontSize}/{btn.fontWeight}, radius {btn.borderRadius}
          </Typography>
        ))}
      </Box>
    </Box>
  );
}

function CardsSubsection() {
  return (
    <Box sx={{ mt: 5 }}>
      <SubsectionTitle>Cards</SubsectionTitle>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
          gap: 3,
        }}
      >
        <Box
          sx={{
            backgroundColor: '#e6e5e0',
            border: '1px solid rgba(38, 37, 30, 0.1)',
            borderRadius: '8px',
            p: 3,
          }}
        >
          <Typography sx={CARD_TITLE_SX}>Standard Card</Typography>
          <Typography sx={CARD_BODY_SX}>
            Surface 400 background with 10% warm brown border. 8px radius with standard padding.
          </Typography>
        </Box>

        <Box
          sx={{
            backgroundColor: '#f2f1ed',
            borderRadius: '10px',
            p: 3,
            boxShadow: 'rgba(0,0,0,0.14) 0px 28px 70px, rgba(0,0,0,0.1) 0px 14px 32px, rgba(38, 37, 30, 0.1) 0px 0px 0px 1px',
          }}
        >
          <Typography sx={CARD_TITLE_SX}>Elevated Card</Typography>
          <Typography sx={CARD_BODY_SX}>
            Featured 10px radius with atmospheric depth shadow. Large blur values create diffused lift.
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}

function BadgesSubsection() {
  return (
    <Box sx={{ mt: 5 }}>
      <SubsectionTitle>Pill Badges</SubsectionTitle>
      <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
        {BADGES.map((badge) => (
          <Box
            key={badge.label}
            sx={{
              backgroundColor: `${badge.color}26`,
              color: badge.color,
              fontSize: '0.75rem',
              fontWeight: 600,
              letterSpacing: '0.125px',
              lineHeight: 1.33,
              px: 1,
              py: 0.5,
              borderRadius: '9999px',
            }}
          >
            {badge.label}
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function CodeBlockSubsection() {
  return (
    <Box sx={{ mt: 5 }}>
      <SubsectionTitle>Code Block</SubsectionTitle>
      <Box
        sx={{
          backgroundColor: '#26251e',
          borderRadius: '8px',
          border: '1px solid rgba(38, 37, 30, 0.1)',
          p: 3,
          overflow: 'auto',
        }}
      >
        <Typography
          component="pre"
          sx={{
            fontFamily: DS_FONT_FAMILY.mono,
            fontSize: '0.75rem',
            lineHeight: 1.67,
            color: '#f2f1ed',
            m: 0,
          }}
        >
{`const theme = {
  canvas: '#f2f1ed',
  text: '#26251e',
  accent: '#f54e00',
  error: '#cf2d56',
  success: '#1f8a65',
};`}
        </Typography>
      </Box>

      <Typography
        sx={{
          color: '#26251e',
          lineHeight: 1.5,
          mt: 2,
        }}
      >
        Use{' '}
        <Box
          component="code"
          sx={{
            fontFamily: DS_FONT_FAMILY.mono,
            fontSize: '0.69rem',
            backgroundColor: '#f7f7f4',
            border: '1px solid rgba(38, 37, 30, 0.1)',
            borderRadius: '3px',
            px: 0.75,
            py: 0.25,
            letterSpacing: '-0.275px',
          }}
        >
          oklab(0.263 / 0.1)
        </Box>{' '}
        for perceptually uniform borders.
      </Typography>
    </Box>
  );
}

function InputSubsection() {
  return (
    <Box sx={{ mt: 5 }}>
      <SubsectionTitle>Input</SubsectionTitle>
      <Box
        component="input"
        placeholder="Placeholder text..."
        sx={{
          fontFamily: 'inherit',
          fontSize: '1rem',
          color: '#26251e',
          backgroundColor: 'transparent',
          border: '1px solid rgba(38, 37, 30, 0.1)',
          borderRadius: '8px',
          padding: '8px 8px 6px',
          outline: 'none',
          width: '100%',
          maxWidth: 400,
          transition: 'border-color 150ms ease',
          '&:focus': {
            borderColor: 'rgba(38, 37, 30, 0.2)',
          },
          '&::placeholder': {
            color: 'rgba(38, 37, 30, 0.4)',
          },
        }}
      />
    </Box>
  );
}
