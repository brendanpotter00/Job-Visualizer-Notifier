import type { ReactNode } from 'react';
import { Box, Button, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';
import { PRICING_CONTENT } from './content';
import type { ProCta } from './proCta';

const CARD_RADIUS = 4.5; // × theme.shape.borderRadius (4px) = 18px

interface PlanCardShellProps {
  inverted?: boolean;
  labelledBy: string;
  children: ReactNode;
}

function PlanCardShell({ inverted = false, labelledBy, children }: PlanCardShellProps) {
  return (
    <Box
      component="section"
      aria-labelledby={labelledBy}
      sx={{
        display: 'flex',
        flexDirection: 'column',
        gap: 1.5,
        p: RESPONSIVE.pricing.cardPadding,
        borderRadius: CARD_RADIUS,
        border: '1px solid',
        // Pro is the only inverted (black) surface on the page — the one bold
        // move; everything else stays in the monochrome landing language.
        borderColor: inverted ? 'text.primary' : 'divider',
        bgcolor: inverted ? 'text.primary' : 'background.default',
        color: inverted ? 'background.default' : 'text.primary',
      }}
    >
      {children}
    </Box>
  );
}

function PlanName({
  id,
  children,
  inverted = false,
}: {
  id: string;
  children: ReactNode;
  inverted?: boolean;
}) {
  return (
    <Typography
      component="h2"
      id={id}
      sx={{
        fontSize: '0.9375rem',
        fontWeight: 400,
        color: inverted ? 'grey.500' : 'text.secondary',
      }}
    >
      {children}
    </Typography>
  );
}

function Price({
  amount,
  period,
  inverted = false,
}: {
  amount: string;
  period?: string;
  inverted?: boolean;
}) {
  return (
    <Typography
      component="p"
      sx={{
        fontSize: RESPONSIVE.pricing.priceFontSize,
        fontWeight: 400,
        lineHeight: 1,
        letterSpacing: '-0.04em',
      }}
    >
      {amount}
      {period && (
        <Box
          component="span"
          sx={{
            fontSize: '0.9375rem',
            letterSpacing: 0,
            ml: 0.75,
            color: inverted ? 'grey.500' : 'text.secondary',
          }}
        >
          {period}
        </Box>
      )}
    </Typography>
  );
}

export function FreePlanCard() {
  const { free } = PRICING_CONTENT;
  return (
    <PlanCardShell labelledBy="plan-free">
      <PlanName id="plan-free">{free.name}</PlanName>
      <Price amount={free.price} />
      {/* Ruled rows, no bullets (owner, 2026-11-15). */}
      <Box component="ul" sx={{ listStyle: 'none', p: 0, m: 0, mt: 1, mb: 3 }}>
        {free.rows.map((row) => (
          <Box
            component="li"
            key={row}
            sx={{
              py: 1.25,
              borderTop: '1px solid',
              borderColor: 'divider',
              fontSize: RESPONSIVE.pricing.rowFontSize,
            }}
          >
            {row}
          </Box>
        ))}
      </Box>
      <Button
        component={RouterLink}
        to={free.cta.to}
        variant="outlined"
        sx={{
          mt: 'auto',
          alignSelf: 'flex-start',
          borderRadius: 999,
          px: 2.5,
          color: 'text.primary',
          borderColor: 'divider',
        }}
      >
        {free.cta.label}
      </Button>
    </PlanCardShell>
  );
}

interface ProPlanCardProps {
  cta: ProCta;
  busy: boolean;
  authEnabled: boolean;
  onSignIn: () => void;
  onUpgrade: () => void;
  onManage: () => void;
}

function proCtaLabel(cta: ProCta): string {
  const labels = PRICING_CONTENT.pro.cta;
  switch (cta.kind) {
    case 'signin':
      return labels.signedOut;
    case 'manage':
      return labels.manage;
    case 'included':
      return labels.included;
    case 'activating':
      return labels.activating;
    case 'loading':
    case 'upgrade':
      return labels.upgrade;
  }
}

export function ProPlanCard({
  cta,
  busy,
  authEnabled,
  onSignIn,
  onUpgrade,
  onManage,
}: ProPlanCardProps) {
  const { pro } = PRICING_CONTENT;
  const disabled =
    busy ||
    cta.kind === 'loading' ||
    cta.kind === 'included' ||
    cta.kind === 'activating' ||
    (cta.kind === 'upgrade' && cta.disabled);
  const onClick =
    cta.kind === 'signin'
      ? onSignIn
      : cta.kind === 'manage'
        ? onManage
        : cta.kind === 'upgrade'
          ? onUpgrade
          : undefined;

  const buttonSx = {
    mt: 'auto',
    alignSelf: 'flex-start',
    borderRadius: 999,
    px: 2.5,
    bgcolor: 'background.default',
    color: 'text.primary',
    boxShadow: 'none',
    '&:hover': { bgcolor: 'grey.200', boxShadow: 'none' },
    '&.Mui-disabled': { bgcolor: 'grey.800', color: 'grey.500' },
  } as const;

  return (
    <PlanCardShell inverted labelledBy="plan-pro">
      <PlanName id="plan-pro" inverted>
        {pro.name}
      </PlanName>
      <Price amount={pro.price} period={pro.period} inverted />
      <Typography sx={{ mt: 2, fontSize: '0.9375rem', color: 'grey.500' }}>{pro.plus}</Typography>
      {/* Option B (owner, 2026-11-15): the one feature, set large, in place of a list. */}
      <Typography
        component="p"
        sx={{
          fontSize: RESPONSIVE.pricing.proHeadlineFontSize,
          lineHeight: 1.05,
          letterSpacing: '-0.03em',
          fontWeight: 400,
          maxWidth: 300,
          mb: 3,
        }}
      >
        {pro.headline}
      </Typography>
      {/* With Auth0 unconfigured (local Vite without env), there is no sign-in to
          start; fall back to the account route like AuthEntryButton does. */}
      {cta.kind === 'signin' && !authEnabled ? (
        <Button component={RouterLink} to={ROUTES.ACCOUNT} variant="contained" sx={buttonSx}>
          {proCtaLabel(cta)}
        </Button>
      ) : (
        <Button variant="contained" disabled={disabled} onClick={onClick} sx={buttonSx}>
          {proCtaLabel(cta)}
        </Button>
      )}
      {cta.kind === 'upgrade' && cta.disabled && (
        <Typography sx={{ fontSize: '0.8125rem', color: 'grey.500' }}>{pro.unavailable}</Typography>
      )}
    </PlanCardShell>
  );
}
