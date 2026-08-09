import { Box, IconButton, Tab, Tabs, Tooltip, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { Link as RouterLink } from 'react-router-dom';
import { ROUTES } from '../../config/routes';
import { RESPONSIVE } from '../../config/responsive';
import type { PrototypeId } from './types';
import { PROTOTYPES } from './prototypes/registry';

interface PrototypeTabStripProps {
  activeId: PrototypeId;
  onChange: (id: PrototypeId) => void;
}

/**
 * Browser-style tab strip: rounded-top tabs resting on a grey strip, the
 * active tab "raised" and fused with the content area below. MUI Tabs (not a
 * hand-rolled Box strip) so keyboard navigation, tablist semantics, and mobile
 * overflow scrolling come for free.
 */
export function PrototypeTabStrip({ activeId, onChange }: PrototypeTabStripProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: 0.5,
        px: 1,
        pt: 0.75,
        bgcolor: 'grey.100',
        borderBottom: '1px solid',
        borderColor: 'divider',
        flexShrink: 0,
      }}
    >
      <Tooltip title="Back to the app">
        <IconButton
          component={RouterLink}
          to={ROUTES.RECENT_JOBS}
          size="small"
          aria-label="Back to the app"
          sx={{ mb: 0.5 }}
        >
          <ArrowBackIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Typography
        variant="caption"
        sx={{
          color: 'text.secondary',
          mb: 1,
          mr: 1,
          display: { xs: 'none', sm: 'block' },
          whiteSpace: 'nowrap',
        }}
      >
        Landing prototypes
      </Typography>
      <Tabs
        value={activeId}
        onChange={(_event, value: PrototypeId) => onChange(value)}
        variant="scrollable"
        allowScrollButtonsMobile
        aria-label="Landing page prototypes"
        sx={{
          minHeight: RESPONSIVE.landingProto.tabMinHeight,
          '& .MuiTabs-indicator': { display: 'none' },
        }}
      >
        {PROTOTYPES.map((proto) => (
          <Tab
            key={proto.id}
            value={proto.id}
            label={proto.label}
            sx={{
              textTransform: 'none',
              minHeight: RESPONSIVE.landingProto.tabMinHeight,
              fontSize: RESPONSIVE.landingProto.tabFontSize,
              px: 2,
              py: 0.5,
              mb: '-1px',
              borderRadius: '8px 8px 0 0',
              border: '1px solid transparent',
              color: 'text.secondary',
              '&.Mui-selected': {
                bgcolor: 'background.default',
                borderColor: 'divider',
                borderBottomColor: 'background.default',
                color: 'text.primary',
                fontWeight: 600,
              },
            }}
          />
        ))}
      </Tabs>
    </Box>
  );
}
