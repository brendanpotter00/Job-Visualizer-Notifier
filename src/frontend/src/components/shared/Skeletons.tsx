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

/**
 * Shared skeleton building blocks for first-load states.
 *
 * Every page that waits on data renders a skeleton shaped like its loaded
 * content instead of a centered spinner, so the layout does not jump when the
 * data lands. Pages compose these pieces (and the older `ChartSkeleton` /
 * `JobListSkeleton` in `LoadingIndicator.tsx`) rather than hand-rolling
 * `<Skeleton>` stacks.
 *
 * Three rules every piece here follows:
 *
 *  - **Bounded.** A skeleton is a stand-in, not a list. Every repeated piece
 *    (rows, cards, tiles, lines) is clamped to {@link MAX_SKELETON_ITEMS} no
 *    matter what the caller passes — see the "never render unbounded lists"
 *    gotcha in the root CLAUDE.md.
 *  - **Visual only.** None of these carries a role. Wrap a skeleton (or a whole
 *    page of them) in ONE {@link SkeletonRegion}, which supplies the accessible
 *    loading signal: `role="status"`, `aria-busy`, and a visually hidden label.
 *    Nesting regions would announce the same wait several times.
 *  - **Static copy is text, never a heading.** A title that is known up front
 *    (a page title, a section name, a table header label) renders as real text
 *    so it does not shift when the data lands — but as a plain `div`, not an
 *    `h1`/`h2`. The page's heading outline appears with the loaded content, so
 *    "the heading is there" keeps meaning "the page has loaded" for screen
 *    reader users and for tests alike.
 *
 * Colors come from MUI's `Skeleton` (a translucent `text.primary`), so the
 * pieces follow the theme palette rather than hard-coding a gray.
 */

/** Label used by {@link SkeletonRegion} when the caller does not name the wait. */
export const SKELETON_DEFAULT_LABEL = 'Loading…';

/** Upper bound on any repeated skeleton piece (rows, cards, tiles, lines). */
export const MAX_SKELETON_ITEMS = 12;

/**
 * Height of a skeleton standing in for a button, text field or select. Restates
 * the theme's 44px `minHeight` floor on `MuiButton` / `MuiTextField` /
 * `MuiSelect` (`config/theme.ts`), which applies at every width.
 */
export const SKELETON_CONTROL_HEIGHT = 44;

/** MUI's small `<Chip>` height, for chip-shaped placeholders. */
const SKELETON_CHIP_HEIGHT = 24;

/**
 * MUI `TablePagination`'s toolbar min-height, so a paginated table's footer
 * placeholder occupies the same band as the real footer.
 */
const TABLE_PAGINATION_HEIGHT = 52;

/** A plain value or a per-breakpoint object, as MUI `sx` accepts it. */
type Responsive<T> = T | Partial<Record<Breakpoint, T>>;

/** Text widths cycled across rows/cells so a skeleton doesn't read as a grid of bars. */
const CELL_WIDTHS = ['80%', '60%', '70%', '45%', '65%'] as const;
/** Screen-reader-only text (the standard clip pattern MUI's `visuallyHidden` uses). */
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

/**
 * Clamps a requested repeat count into `[0, MAX_SKELETON_ITEMS]`. Non-finite or
 * negative input yields 0, so a bad prop can never ask for an unbounded loop.
 */
function clampSkeletonCount(count: number): number {
  if (!Number.isFinite(count) || count <= 0) return 0;
  return Math.min(Math.floor(count), MAX_SKELETON_ITEMS);
}

/** Indices `0..n-1` after clamping. Tiny (<= 12 entries), so no memo needed. */
function indices(count: number): number[] {
  return Array.from({ length: clampSkeletonCount(count) }, (_, i) => i);
}

/** Merges a base sx object with an optional caller sx (object, array or function). */
function mergeSx(base: SxProps<Theme>, sx?: SxProps<Theme>): SxProps<Theme> {
  if (!sx) return base;
  return [
    ...(Array.isArray(base) ? base : [base]),
    ...(Array.isArray(sx) ? sx : [sx]),
  ] as SxProps<Theme>;
}

// ─── Accessibility wrapper ──────────────────────────────────────────────────

export interface SkeletonRegionProps {
  /**
   * What is loading, e.g. "Loading feedback…". Used as the region's accessible
   * name and as visually hidden text inside it.
   */
  label?: string;
  children: ReactNode;
  sx?: SxProps<Theme>;
}

/**
 * The accessible loading signal for a skeleton. Exactly one per wait: it is a
 * polite live region (`role="status"`) marked `aria-busy`, named by `label`,
 * and carries the same label as visually hidden text so it reads the same in
 * every screen reader.
 */
export function SkeletonRegion({ label = SKELETON_DEFAULT_LABEL, children, sx }: SkeletonRegionProps) {
  return (
    <Box role="status" aria-busy="true" aria-label={label} sx={sx}>
      <Box component="span" sx={VISUALLY_HIDDEN_SX}>
        {label}
      </Box>
      {children}
    </Box>
  );
}

// ─── Text ───────────────────────────────────────────────────────────────────

type TextVariant = 'h3' | 'h4' | 'h5' | 'h6' | 'body1' | 'body2' | 'caption' | 'overline';

export interface TextSkeletonProps {
  /** Number of lines (clamped). The last line is shorter, like a paragraph. */
  lines?: number;
  /** Typography variant the real text uses, so line height matches exactly. */
  variant?: TextVariant;
  /** Width of the final line of a multi-line block (a single line is full width). */
  lastLineWidth?: string | number;
  sx?: SxProps<Theme>;
}

/**
 * Lines of text placeholder. Each line is a `Skeleton` inside the same
 * `Typography` variant the real copy uses — MUI's recommended way to inherit
 * the exact line height, so swapping in the text causes no vertical shift.
 */
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

// ─── Page header ────────────────────────────────────────────────────────────

export interface PageHeaderSkeletonProps {
  /**
   * The page's real title, when it is static copy. Renders as text in the
   * title's Typography variant (not as a heading — see the file header); a
   * skeleton bar stands in when omitted.
   */
  title?: ReactNode;
  /**
   * The page's real subtitle, when it is static copy. Replaces the
   * `subtitleLines` placeholders.
   */
  subtitle?: ReactNode;
  /** Typography variant of the real page title (`h4` on most pages). */
  titleVariant?: 'h3' | 'h4';
  /** Extra sx for the title line, e.g. `{ fontSize: RESPONSIVE.fontSize.pageTitle }`. */
  titleSx?: SxProps<Theme>;
  /** Subtitle lines under the title (0 hides them). */
  subtitleLines?: number;
  /** Button-shaped placeholders on the right (e.g. a Refresh button). */
  actions?: number;
  sx?: SxProps<Theme>;
}

/**
 * A page title + subtitle + optional trailing actions, laid out like the admin
 * pages' header row (title block left, buttons right, `mb: 3`). Static title and
 * subtitle copy can be passed in as text; anything unknown is a placeholder.
 */
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

// ─── Controls ───────────────────────────────────────────────────────────────

export interface ControlsRowSkeletonProps {
  /** Number of control placeholders (selects / inputs / buttons). */
  count?: number;
  /** Width of each control. A responsive value is allowed. */
  width?: Responsive<number | string>;
  /** Height of each control; defaults to the theme's 44px control floor. */
  height?: Responsive<number | string>;
  sx?: SxProps<Theme>;
}

/** A wrapping row of control-shaped placeholders (filter selects, search box, buttons). */
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

// ─── Sections ───────────────────────────────────────────────────────────────

export interface SectionSkeletonProps {
  /**
   * The section's real title, rendered as text when known (static titles like
   * "Health overview") — as a plain `div`, not the `h2` it becomes once loaded.
   * A skeleton bar stands in when omitted.
   */
  title?: ReactNode;
  /** Body placeholder. Defaults to {@link TextSkeleton} with `lines` lines. */
  children?: ReactNode;
  /** Lines in the default body (ignored when `children` is given). */
  lines?: number;
  /** `outlined` for admin sections, `elevation` for the default Paper. */
  variant?: 'outlined' | 'elevation';
  /** Paper padding; defaults to `RESPONSIVE.spacing.paperPadding`. */
  padding?: Responsive<number | string>;
  sx?: SxProps<Theme>;
}

/**
 * A titled `<Paper>` section placeholder, matching the `Paper` + `h6` title
 * shape the admin pages use for every section.
 */
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

/**
 * The left-bordered verdict banner the admin oversight pages lead with (chip +
 * one-line summary + a detail line), in its neutral "unknown" color.
 */
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

// ─── Stat tiles ─────────────────────────────────────────────────────────────

/** One admin `StatTile` placeholder: overline label, big value, meta line. */
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
      {/* `minHeight: 24` restates StatTile's meta row, which reserves that band
          whether or not a meta line is present. */}
      <Box sx={{ minHeight: 24 }}>
        <Typography variant="body2" component="div">
          <Skeleton width="65%" />
        </Typography>
      </Box>
    </Paper>
  );
}

export interface StatTilesSkeletonProps {
  /** Number of tiles (clamped). */
  count?: number;
  /** MUI Grid `size` per tile — match the real grid (e.g. `{ xs: 6, sm: 3 }`). */
  size?: GridProps['size'];
  sx?: SxProps<Theme>;
}

/** A grid row of {@link StatTileSkeleton}s, laid out like the real tile grid. */
export function StatTilesSkeleton({ count = 4, size = { xs: 6, sm: 3 }, sx }: StatTilesSkeletonProps) {
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

// ─── Tables ─────────────────────────────────────────────────────────────────

export interface TableSkeletonProps {
  /**
   * Column count, or the real header labels. Labels render as real header text
   * (they are static), so the header row doesn't shift when the data arrives.
   */
  columns: number | readonly string[];
  /** Body rows (clamped). */
  rows?: number;
  /**
   * Surface: `outlined` Paper (default), `elevation` Paper (the
   * `TableContainer component={Paper}` tables), or `none` when the table sits
   * directly inside an already-padded section Paper.
   */
  surface?: 'outlined' | 'elevation' | 'none';
  /** Real table title (as text, not a heading), in a padded toolbar above the table. */
  title?: ReactNode;
  /** Control placeholders on the right of the toolbar (search box, switches). */
  toolbarControls?: number;
  /** Render a pagination-footer placeholder under the table. */
  pagination?: boolean;
  /**
   * What to draw below 600px. `table` (default) keeps the table, which scrolls
   * sideways like the real one. `list` draws stacked two-line rows instead, for
   * the admin tables that swap to a tappable list on phones.
   */
  mobileVariant?: 'table' | 'list';
}

/**
 * A small MUI table placeholder for the admin tables: header row, a bounded
 * number of body rows, optional titled toolbar and pagination footer. Wraps in
 * `TABLE_SCROLL_SX` like the real tables, so a wide header scrolls on mobile —
 * or, with `mobileVariant="list"`, draws the phone list those tables swap to.
 */
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

// ─── Lists ──────────────────────────────────────────────────────────────────

export interface ListSkeletonProps {
  /** Rows (clamped). */
  rows?: number;
  /** Matches `<List dense>`. */
  dense?: boolean;
}

/** A divided MUI `<List>` placeholder (one primary text line per row). */
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
  /** Cards (clamped). */
  count?: number;
  /** Body lines under each card's title. */
  lines?: number;
  /** A narrow leading column (e.g. a vote button over its count). */
  leading?: boolean;
  /** A trailing icon-button placeholder (e.g. a remove control). */
  trailing?: boolean;
  /** Gap between cards in theme units. */
  spacing?: number;
}

/**
 * A vertical stack of outlined cards — the shape of the feature-vote list and
 * the user's tracked-companies list: an `h6` title, a few body lines, and an
 * optional leading column / trailing control.
 */
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

// ─── Card grids ─────────────────────────────────────────────────────────────

export interface CardSkeletonProps {
  /** Height of a leading media/logo block; omitted = no media block. */
  mediaHeight?: Responsive<number | string>;
  /** Body text lines. */
  lines?: number;
  /** A trailing link/action line. */
  action?: boolean;
  /** CardContent padding; defaults to MUI's 16px. */
  contentPadding?: Responsive<number | string>;
}

/** One grid card placeholder: optional logo block, body lines, optional action line. */
export function CardSkeleton({ mediaHeight, lines = 3, action = false, contentPadding = 2 }: CardSkeletonProps) {
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
  /** Cards (clamped). */
  count?: number;
  /** MUI Grid `size` per card — match the real grid. */
  itemSize?: GridProps['size'];
  /** Grid spacing — match the real grid. */
  spacing?: GridProps['spacing'];
}

/** A responsive grid of {@link CardSkeleton}s laid out like the real card grid. */
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

/** A chip-shaped placeholder row (tag chips under a title). */
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

// ─── Whole page ─────────────────────────────────────────────────────────────

export interface PageSkeletonProps {
  /** Accessible label for the wait. */
  label?: string;
  /** Fill the viewport (for routes rendered outside the app shell). */
  fullPage?: boolean;
  /** Container width — match the page family (`lg` default, `xl` for admin). */
  maxWidth?: Breakpoint;
  /** Number of section placeholders under the header (clamped). */
  sections?: number;
}

/**
 * The generic page placeholder, for waits that happen before the page's own
 * shape is known: the route-level `Suspense` fallback and the admin route guard
 * while auth resolves. A page header and a few titled sections, in the app's
 * standard page container.
 */
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
