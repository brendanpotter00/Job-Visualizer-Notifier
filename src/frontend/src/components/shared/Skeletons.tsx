import type { ReactNode } from 'react';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Container from '@mui/material/Container';
import Grid from '@mui/material/Grid';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Paper from '@mui/material/Paper';
import Skeleton from '@mui/material/Skeleton';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import type { Breakpoint, SxProps, Theme } from '@mui/material';
import type { GridProps } from '@mui/material/Grid';
import { RESPONSIVE, TABLE_SCROLL_SX } from '../../config/responsive';
import { useIsMobile } from '../../hooks/useIsMobile';

export const SKELETON_DEFAULT_LABEL = 'Loading…';

export const MAX_SKELETON_ITEMS = 12;

export const SKELETON_CONTROL_HEIGHT = 44;

const SKELETON_CHIP_HEIGHT = 24;

const TABLE_PAGINATION_HEIGHT = 52;

type Responsive<T> = T | Partial<Record<Breakpoint, T>>;

const CELL_WIDTHS = ['80%', '60%', '70%', '45%', '65%'] as const;
const VISUALLY_HIDDEN_SX = {
  border: 0,
  clip: 'rect(0 0 0 0)',
  height: '1px',
  margin: '-1px',
  overflow: 'hidden',
  padding: 0,
  position: 'absolute',
  whiteSpace: 'nowrap',
  width: '1px',
} as const;

function clampSkeletonCount(count: number): number {
  if (!Number.isFinite(count) || count <= 0) return 0;
  return Math.min(Math.floor(count), MAX_SKELETON_ITEMS);
}

function indices(count: number): number[] {
  return Array.from({ length: clampSkeletonCount(count) }, (_, i) => i);
}

function mergeSx(base: SxProps<Theme>, sx?: SxProps<Theme>): SxProps<Theme> {
  if (!sx) return base;
  return [
    ...(Array.isArray(base) ? base : [base]),
    ...(Array.isArray(sx) ? sx : [sx]),
  ] as SxProps<Theme>;
}

export interface SkeletonRegionProps {
  label?: string;
  children: ReactNode;
  sx?: SxProps<Theme>;
}

export function SkeletonRegion({
  label = SKELETON_DEFAULT_LABEL,
  children,
  sx,
}: SkeletonRegionProps) {
  return (
    <Box role="status" aria-busy="true" aria-label={label} sx={sx}>
      <Box component="span" sx={VISUALLY_HIDDEN_SX}>
        {label}
      </Box>
      {children}
    </Box>
  );
}

type TextVariant = 'h3' | 'h4' | 'h5' | 'h6' | 'body1' | 'body2' | 'caption' | 'overline';

export interface TextSkeletonProps {
  lines?: number;
  variant?: TextVariant;
  lastLineWidth?: string | number;
  sx?: SxProps<Theme>;
}

export function TextSkeleton({
  lines = 3,
  variant = 'body2',
  lastLineWidth = '60%',
  sx,
}: TextSkeletonProps) {
  const rows = indices(lines);
  return (
    <Box sx={sx}>
      {rows.map((i) => (
        <Typography key={i} variant={variant} component="div">
          <Skeleton width={i === rows.length - 1 && rows.length > 1 ? lastLineWidth : '100%'} />
        </Typography>
      ))}
    </Box>
  );
}

export interface PageHeaderSkeletonProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  titleVariant?: 'h3' | 'h4';
  titleSx?: SxProps<Theme>;
  subtitleLines?: number;
  actions?: number;
  sx?: SxProps<Theme>;
}

export function PageHeaderSkeleton({
  title,
  subtitle: subtitleText,
  titleVariant = 'h4',
  titleSx,
  subtitleLines = 1,
  actions = 0,
  sx,
}: PageHeaderSkeletonProps) {
  const subtitle = subtitleText ? [] : indices(subtitleLines);
  const hasSubtitle = Boolean(subtitleText) || subtitle.length > 0;
  const buttons = indices(actions);
  return (
    <Box
      data-testid="page-header-skeleton"
      sx={mergeSx(
        {
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 2,
          mb: 3,
        },
        sx
      )}
    >
      <Box sx={{ flex: '1 1 240px', minWidth: 0 }}>
        <Typography variant={titleVariant} component="div" gutterBottom={hasSubtitle} sx={titleSx}>
          {title ?? <Skeleton width="45%" />}
        </Typography>
        {subtitleText && (
          <Typography variant="body2" color="text.secondary" component="div">
            {subtitleText}
          </Typography>
        )}
        {subtitle.map((i) => (
          <Typography key={i} variant="body2" component="div">
            <Skeleton width={i === subtitle.length - 1 ? '55%' : '85%'} />
          </Typography>
        ))}
      </Box>
      {buttons.length > 0 && (
        <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center' }}>
          {buttons.map((i) => (
            <Skeleton key={i} variant="rounded" width={104} height={SKELETON_CONTROL_HEIGHT} />
          ))}
        </Box>
      )}
    </Box>
  );
}

export interface ControlsRowSkeletonProps {
  count?: number;
  width?: Responsive<number | string>;
  height?: Responsive<number | string>;
  sx?: SxProps<Theme>;
}

export function ControlsRowSkeleton({
  count = 2,
  width = { xs: '100%', sm: 200 },
  height = SKELETON_CONTROL_HEIGHT,
  sx,
}: ControlsRowSkeletonProps) {
  return (
    <Box sx={mergeSx({ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }, sx)}>
      {indices(count).map((i) => (
        <Skeleton key={i} variant="rounded" sx={{ width, height }} />
      ))}
    </Box>
  );
}

export interface SectionSkeletonProps {
  title?: ReactNode;
  children?: ReactNode;
  lines?: number;
  variant?: 'outlined' | 'elevation';
  padding?: Responsive<number | string>;
  sx?: SxProps<Theme>;
}

export function SectionSkeleton({
  title,
  children,
  lines = 3,
  variant = 'outlined',
  padding = RESPONSIVE.spacing.paperPadding,
  sx,
}: SectionSkeletonProps) {
  return (
    <Paper
      variant={variant}
      sx={mergeSx({ p: padding, mb: RESPONSIVE.spacing.sectionMarginB }, sx)}
    >
      <Typography variant="h6" component="div" gutterBottom>
        {title ?? <Skeleton width="30%" />}
      </Typography>
      {children ?? <TextSkeleton lines={lines} />}
    </Paper>
  );
}

export function StatusBannerSkeleton({ sx }: { sx?: SxProps<Theme> }) {
  return (
    <Paper
      variant="outlined"
      sx={mergeSx(
        {
          p: 2.5,
          mb: RESPONSIVE.spacing.sectionMarginB,
          borderLeft: 6,
          borderLeftColor: 'text.disabled',
        },
        sx
      )}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', mb: 1 }}>
        <Skeleton variant="rounded" width={96} height={32} />
        <Typography variant="h6" component="div" sx={{ flex: '1 1 200px' }}>
          <Skeleton width="60%" />
        </Typography>
      </Box>
      <Typography variant="body2" component="div">
        <Skeleton width="45%" />
      </Typography>
    </Paper>
  );
}

export function StatTileSkeleton() {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: RESPONSIVE.statTile.padding,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        gap: RESPONSIVE.statTile.gap,
      }}
    >
      <Typography variant="overline" component="div" sx={{ lineHeight: 1.2 }}>
        <Skeleton width="55%" />
      </Typography>
      <Typography variant="h4" component="div">
        <Skeleton width="40%" />
      </Typography>
      <Box sx={{ minHeight: 24 }}>
        <Typography variant="body2" component="div">
          <Skeleton width="65%" />
        </Typography>
      </Box>
    </Paper>
  );
}

export interface StatTilesSkeletonProps {
  count?: number;
  size?: GridProps['size'];
  sx?: SxProps<Theme>;
}

export function StatTilesSkeleton({
  count = 4,
  size = { xs: 6, sm: 3 },
  sx,
}: StatTilesSkeletonProps) {
  return (
    <Grid container spacing={2} sx={sx}>
      {indices(count).map((i) => (
        <Grid key={i} size={size}>
          <StatTileSkeleton />
        </Grid>
      ))}
    </Grid>
  );
}

export interface TableSkeletonProps {
  columns: number | readonly string[];
  rows?: number;
  surface?: 'outlined' | 'elevation' | 'none';
  title?: ReactNode;
  toolbarControls?: number;
  pagination?: boolean;
  mobileVariant?: 'table' | 'list';
}

export function TableSkeleton({
  columns,
  rows = 5,
  surface = 'outlined',
  title,
  toolbarControls = 0,
  pagination = false,
  mobileVariant = 'table',
}: TableSkeletonProps) {
  const isMobile = useIsMobile();
  const asList = mobileVariant === 'list' && isMobile;
  const headers: readonly (string | null)[] =
    typeof columns === 'number' ? indices(columns).map(() => null) : columns;
  const bodyRows = indices(rows);
  const controls = indices(toolbarControls);

  const table = (
    <>
      {(title || controls.length > 0) && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 2,
            p: 2,
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h6" component="div">
              {title ?? <Skeleton width={140} />}
            </Typography>
            <Typography variant="body2" component="div">
              <Skeleton width={80} />
            </Typography>
          </Box>
          {controls.length > 0 && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
              {controls.map((i) => (
                <Skeleton
                  key={i}
                  variant="rounded"
                  sx={{ width: { xs: 200, sm: 280 }, height: SKELETON_CONTROL_HEIGHT }}
                />
              ))}
            </Box>
          )}
        </Box>
      )}
      {asList ? (
        <Stack
          data-testid="table-skeleton-mobile-list"
          divider={<Box sx={{ borderBottom: 1, borderColor: 'divider' }} />}
        >
          {bodyRows.map((r) => (
            <Box key={r} sx={{ p: 1.5 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, mb: 0.5 }}>
                <Typography variant="body2" component="div" sx={{ flex: 1 }}>
                  <Skeleton width={CELL_WIDTHS[r % CELL_WIDTHS.length]} />
                </Typography>
                <Typography variant="caption" component="div">
                  <Skeleton width={64} />
                </Typography>
              </Box>
              <TextSkeleton lines={2} />
            </Box>
          ))}
        </Stack>
      ) : (
        <TableContainer sx={TABLE_SCROLL_SX}>
          <Table size="small">
            <TableHead>
              <TableRow>
                {headers.map((label, c) => (
                  <TableCell key={c}>{label ?? <Skeleton width="60%" />}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {bodyRows.map((r) => (
                <TableRow key={r}>
                  {headers.map((_, c) => (
                    <TableCell key={c}>
                      <Skeleton width={CELL_WIDTHS[(r + c) % CELL_WIDTHS.length]} />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {pagination && (
        <Box
          data-testid="table-skeleton-pagination"
          sx={{
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            gap: 3,
            px: 2,
            minHeight: TABLE_PAGINATION_HEIGHT,
          }}
        >
          <Skeleton width={120} />
          <Skeleton width={64} />
        </Box>
      )}
    </>
  );

  if (surface === 'none') return <Box>{table}</Box>;
  return <Paper variant={surface}>{table}</Paper>;
}

export interface ListSkeletonProps {
  rows?: number;
  dense?: boolean;
}

export function ListSkeleton({ rows = 6, dense = true }: ListSkeletonProps) {
  return (
    <List dense={dense} disablePadding>
      {indices(rows).map((i) => (
        <ListItem key={i} divider>
          <ListItemText primary={<Skeleton width={CELL_WIDTHS[i % CELL_WIDTHS.length]} />} />
        </ListItem>
      ))}
    </List>
  );
}

export interface CardListSkeletonProps {
  count?: number;
  lines?: number;
  leading?: boolean;
  trailing?: boolean;
  spacing?: number;
}

export function CardListSkeleton({
  count = 3,
  lines = 2,
  leading = false,
  trailing = false,
  spacing = 2,
}: CardListSkeletonProps) {
  return (
    <Stack spacing={spacing}>
      {indices(count).map((i) => (
        <Card key={i} variant="outlined">
          <CardContent
            sx={{
              p: RESPONSIVE.spacing.cardPadding,
              '&:last-child': { pb: RESPONSIVE.spacing.cardPaddingBottom },
            }}
          >
            <Stack direction="row" spacing={2} sx={{ alignItems: 'flex-start' }}>
              {leading && (
                <Box
                  sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 0.5,
                    minWidth: 48,
                  }}
                >
                  <Skeleton variant="circular" width={34} height={34} />
                  <Typography variant="body2" component="div">
                    <Skeleton width={20} />
                  </Typography>
                </Box>
              )}
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="h6" component="div" gutterBottom>
                  <Skeleton width={CELL_WIDTHS[i % CELL_WIDTHS.length]} />
                </Typography>
                <TextSkeleton lines={lines} />
              </Box>
              {trailing && <Skeleton variant="circular" width={32} height={32} />}
            </Stack>
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}

export interface CardSkeletonProps {
  mediaHeight?: Responsive<number | string>;
  lines?: number;
  action?: boolean;
  contentPadding?: Responsive<number | string>;
}

export function CardSkeleton({
  mediaHeight,
  lines = 3,
  action = false,
  contentPadding = 2,
}: CardSkeletonProps) {
  return (
    <Card variant="outlined" sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1, p: contentPadding }}>
        {mediaHeight !== undefined && (
          <Skeleton variant="rounded" sx={{ width: '45%', height: mediaHeight, mb: 1.5 }} />
        )}
        <TextSkeleton lines={lines} />
        {action && (
          <Typography variant="body2" component="div" sx={{ mt: 1.5 }}>
            <Skeleton width="55%" />
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

export interface CardGridSkeletonProps extends CardSkeletonProps {
  count?: number;
  itemSize?: GridProps['size'];
  spacing?: GridProps['spacing'];
}

export function CardGridSkeleton({
  count = 6,
  itemSize = { xs: 12, sm: 6, md: 4 },
  spacing = 2,
  ...cardProps
}: CardGridSkeletonProps) {
  return (
    <Grid container spacing={spacing}>
      {indices(count).map((i) => (
        <Grid key={i} size={itemSize}>
          <CardSkeleton {...cardProps} />
        </Grid>
      ))}
    </Grid>
  );
}

export function ChipRowSkeleton({ count = 3 }: { count?: number }) {
  return (
    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
      {indices(count).map((i) => (
        <Skeleton
          key={i}
          variant="rounded"
          width={[72, 96, 64][i % 3]}
          height={SKELETON_CHIP_HEIGHT}
        />
      ))}
    </Box>
  );
}

export interface PageSkeletonProps {
  label?: string;
  fullPage?: boolean;
  maxWidth?: Breakpoint;
  sections?: number;
}

export function PageSkeleton({
  label = 'Loading page…',
  fullPage = false,
  maxWidth = 'lg',
  sections = 2,
}: PageSkeletonProps) {
  return (
    <Container
      maxWidth={maxWidth}
      sx={{
        py: RESPONSIVE.spacing.pageMarginY,
        ...(fullPage && { minHeight: '100vh', bgcolor: 'background.default' }),
      }}
    >
      <SkeletonRegion label={label}>
        <PageHeaderSkeleton />
        {indices(sections).map((i) => (
          <SectionSkeleton key={i} lines={i === 0 ? 2 : 4} />
        ))}
      </SkeletonRegion>
    </Container>
  );
}
