import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import {
  CardGridSkeleton,
  CardListSkeleton,
  CardSkeleton,
  ChipRowSkeleton,
  ControlsRowSkeleton,
  ListSkeleton,
  MAX_SKELETON_ITEMS,
  PageHeaderSkeleton,
  PageSkeleton,
  SKELETON_DEFAULT_LABEL,
  SectionSkeleton,
  SkeletonRegion,
  StatTileSkeleton,
  StatTilesSkeleton,
  StatusBannerSkeleton,
  TableSkeleton,
  TextSkeleton,
} from '../../../components/shared/Skeletons';
import { useIsMobile } from '../../../hooks/useIsMobile';

vi.mock('../../../hooks/useIsMobile');

/** MUI renders every `<Skeleton>` with this class. */
const skeletons = (root: ParentNode) => root.querySelectorAll('.MuiSkeleton-root');

describe('Skeletons', () => {
  beforeEach(() => vi.mocked(useIsMobile).mockReturnValue(false));

  describe('SkeletonRegion', () => {
    it('is a busy status region named by its label, with the label as hidden text', () => {
      render(
        <SkeletonRegion label="Loading feedback…">
          <div data-testid="child" />
        </SkeletonRegion>
      );

      const region = screen.getByRole('status', { name: 'Loading feedback…' });
      expect(region).toHaveAttribute('aria-busy', 'true');
      // The visually hidden copy keeps text-based queries (and every screen
      // reader) working, not just the aria-label.
      expect(within(region).getByText('Loading feedback…')).toBeInTheDocument();
      expect(within(region).getByTestId('child')).toBeInTheDocument();
    });

    it('defaults its label to "Loading…"', () => {
      render(
        <SkeletonRegion>
          <span />
        </SkeletonRegion>
      );
      expect(screen.getByRole('status', { name: SKELETON_DEFAULT_LABEL })).toBeInTheDocument();
    });

    it('does not render a spinner', () => {
      render(
        <SkeletonRegion>
          <span />
        </SkeletonRegion>
      );
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });
  });

  describe('visual pieces carry no role of their own', () => {
    it.each([
      ['TextSkeleton', <TextSkeleton key="t" />],
      ['PageHeaderSkeleton', <PageHeaderSkeleton key="p" actions={1} />],
      ['SectionSkeleton', <SectionSkeleton key="s" />],
      ['StatusBannerSkeleton', <StatusBannerSkeleton key="b" />],
      ['StatTilesSkeleton', <StatTilesSkeleton key="st" />],
      ['TableSkeleton', <TableSkeleton key="tb" columns={3} />],
      ['CardListSkeleton', <CardListSkeleton key="cl" />],
      ['CardGridSkeleton', <CardGridSkeleton key="cg" />],
      ['ListSkeleton', <ListSkeleton key="l" />],
      ['ControlsRowSkeleton', <ControlsRowSkeleton key="c" />],
      ['ChipRowSkeleton', <ChipRowSkeleton key="ch" />],
    ])('%s renders skeleton shapes without a status role', (_name, element) => {
      const { container } = render(element);
      expect(skeletons(container).length).toBeGreaterThan(0);
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });
  });

  describe('bounded rendering', () => {
    it('clamps table rows to MAX_SKELETON_ITEMS', () => {
      render(<TableSkeleton columns={2} rows={10_000} />);
      // +1 for the header row.
      expect(screen.getAllByRole('row')).toHaveLength(MAX_SKELETON_ITEMS + 1);
    });

    it('treats negative and non-finite counts as zero', () => {
      const { container: negative } = render(<TextSkeleton lines={-5} />);
      expect(skeletons(negative)).toHaveLength(0);
      const { container: nan } = render(<CardListSkeleton count={Number.NaN} />);
      expect(nan.querySelectorAll('.MuiCard-root')).toHaveLength(0);
    });

    it('clamps card grids, card lists, tiles and list rows', () => {
      const { container: grid } = render(<CardGridSkeleton count={500} />);
      expect(grid.querySelectorAll('.MuiCard-root')).toHaveLength(MAX_SKELETON_ITEMS);

      const { container: list } = render(<CardListSkeleton count={500} />);
      expect(list.querySelectorAll('.MuiCard-root')).toHaveLength(MAX_SKELETON_ITEMS);

      const { container: tiles } = render(<StatTilesSkeleton count={500} />);
      expect(tiles.querySelectorAll('.MuiPaper-outlined')).toHaveLength(MAX_SKELETON_ITEMS);

      render(<ListSkeleton rows={500} />);
      expect(screen.getAllByRole('listitem')).toHaveLength(MAX_SKELETON_ITEMS);
    });
  });

  describe('TextSkeleton', () => {
    it('renders one skeleton per line', () => {
      const { container } = render(<TextSkeleton lines={4} />);
      expect(skeletons(container)).toHaveLength(4);
    });

    it('shortens only the last line of a multi-line block', () => {
      const { container } = render(<TextSkeleton lines={3} lastLineWidth="40%" />);
      const lines = skeletons(container);
      expect(lines[0]).toHaveStyle({ width: '100%' });
      expect(lines[2]).toHaveStyle({ width: '40%' });
    });

    it('keeps a single line full width', () => {
      const { container } = render(<TextSkeleton lines={1} lastLineWidth="40%" />);
      expect(skeletons(container)[0]).toHaveStyle({ width: '100%' });
    });
  });

  describe('PageHeaderSkeleton', () => {
    it('renders static title and subtitle copy as text in place of placeholders', () => {
      const { container } = render(
        <PageHeaderSkeleton title="Admin · Users" subtitle="Who signed up" actions={1} />
      );
      expect(screen.getByText('Admin · Users')).toBeInTheDocument();
      expect(screen.getByText('Who signed up')).toBeInTheDocument();
      expect(screen.queryByRole('heading')).not.toBeInTheDocument();
      // Only the action placeholder remains a skeleton.
      expect(skeletons(container)).toHaveLength(1);
    });

    it('renders a title bar, the requested subtitle lines and action placeholders', () => {
      const { container } = render(<PageHeaderSkeleton subtitleLines={2} actions={2} />);
      // title + 2 subtitle lines + 2 actions
      expect(skeletons(container)).toHaveLength(5);
    });

    it('omits subtitle and actions when asked', () => {
      const { container } = render(<PageHeaderSkeleton subtitleLines={0} />);
      expect(skeletons(container)).toHaveLength(1);
    });

    it('never renders an empty heading', () => {
      render(<PageHeaderSkeleton />);
      expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    });
  });

  describe('SectionSkeleton', () => {
    it('renders a known title as text, but not as a heading', () => {
      render(<SectionSkeleton title="Health overview" />);
      expect(screen.getByText('Health overview')).toBeInTheDocument();
      // The section's h2 arrives with its data, so "heading present" keeps
      // meaning "loaded".
      expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    });

    it('renders a title bar (not a heading) when the title is unknown', () => {
      render(<SectionSkeleton lines={2} />);
      expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    });

    it('renders custom children in place of the default lines', () => {
      render(
        <SectionSkeleton title="Ticks">
          <div data-testid="custom-body" />
        </SectionSkeleton>
      );
      expect(screen.getByTestId('custom-body')).toBeInTheDocument();
    });

    it('uses an outlined Paper by default and elevation on request', () => {
      const { container: outlined } = render(<SectionSkeleton />);
      expect(outlined.querySelector('.MuiPaper-outlined')).not.toBeNull();
      const { container: elevated } = render(<SectionSkeleton variant="elevation" />);
      expect(elevated.querySelector('.MuiPaper-elevation')).not.toBeNull();
    });
  });

  describe('StatTileSkeleton', () => {
    it('renders the label, value and meta lines in an outlined tile', () => {
      const { container } = render(<StatTileSkeleton />);
      expect(container.querySelector('.MuiPaper-outlined')).not.toBeNull();
      expect(skeletons(container)).toHaveLength(3);
    });
  });

  describe('TableSkeleton', () => {
    it('renders real header labels when given', () => {
      render(<TableSkeleton columns={['Email', 'Name', 'Joined']} rows={2} />);
      const headers = screen.getAllByRole('columnheader');
      expect(headers.map((h) => h.textContent)).toEqual(['Email', 'Name', 'Joined']);
      // 1 header row + 2 body rows
      expect(screen.getAllByRole('row')).toHaveLength(3);
    });

    it('renders skeleton header cells for a bare column count', () => {
      render(<TableSkeleton columns={4} rows={1} />);
      const headers = screen.getAllByRole('columnheader');
      expect(headers).toHaveLength(4);
      headers.forEach((h) => expect(h.querySelector('.MuiSkeleton-root')).not.toBeNull());
    });

    it('renders a titled toolbar (title as text, not a heading) with control placeholders', () => {
      const { container } = render(
        <TableSkeleton columns={2} rows={0} title="User roster" toolbarControls={2} />
      );
      expect(screen.getByText('User roster')).toBeInTheDocument();
      expect(screen.queryByRole('heading')).not.toBeInTheDocument();
      // count line + 2 controls + 2 header cells
      expect(skeletons(container)).toHaveLength(5);
    });

    it('renders a pagination footer only when asked', () => {
      const { rerender } = render(<TableSkeleton columns={2} />);
      expect(screen.queryByTestId('table-skeleton-pagination')).not.toBeInTheDocument();
      rerender(<TableSkeleton columns={2} pagination />);
      expect(screen.getByTestId('table-skeleton-pagination')).toBeInTheDocument();
    });

    it('picks its surface: outlined, elevation or none', () => {
      const { container: outlined } = render(<TableSkeleton columns={1} />);
      expect(outlined.querySelector('.MuiPaper-outlined')).not.toBeNull();
      const { container: elevated } = render(<TableSkeleton columns={1} surface="elevation" />);
      expect(elevated.querySelector('.MuiPaper-elevation')).not.toBeNull();
      const { container: bare } = render(<TableSkeleton columns={1} surface="none" />);
      expect(bare.querySelector('.MuiPaper-root')).toBeNull();
    });

    it('keeps the table on phones by default', () => {
      vi.mocked(useIsMobile).mockReturnValue(true);
      render(<TableSkeleton columns={2} />);
      expect(screen.getByRole('table')).toBeInTheDocument();
      expect(screen.queryByTestId('table-skeleton-mobile-list')).not.toBeInTheDocument();
    });

    it('draws the phone list instead of the table with mobileVariant="list"', () => {
      vi.mocked(useIsMobile).mockReturnValue(true);
      render(<TableSkeleton columns={['From', 'Message']} rows={3} mobileVariant="list" />);
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      expect(screen.getByTestId('table-skeleton-mobile-list')).toBeInTheDocument();
    });

    it('still draws the table on desktop with mobileVariant="list"', () => {
      render(<TableSkeleton columns={2} mobileVariant="list" />);
      expect(screen.getByRole('table')).toBeInTheDocument();
    });
  });

  describe('cards', () => {
    it('CardSkeleton adds a media block and an action line on request', () => {
      const { container: plain } = render(<CardSkeleton lines={2} />);
      expect(skeletons(plain)).toHaveLength(2);
      const { container: full } = render(<CardSkeleton lines={2} mediaHeight={32} action />);
      expect(skeletons(full)).toHaveLength(4);
    });

    it('CardListSkeleton adds leading and trailing placeholders on request', () => {
      const { container: plain } = render(<CardListSkeleton count={1} lines={1} />);
      // title + 1 line
      expect(skeletons(plain)).toHaveLength(2);
      const { container: full } = render(
        <CardListSkeleton count={1} lines={1} leading trailing />
      );
      // + vote circle + count + trailing circle
      expect(skeletons(full)).toHaveLength(5);
    });
  });

  describe('PageSkeleton', () => {
    it('is one labelled status region with a header and sections', () => {
      render(<PageSkeleton label="Loading page…" sections={3} />);
      const region = screen.getByRole('status', { name: 'Loading page…' });
      expect(within(region).getByTestId('page-header-skeleton')).toBeInTheDocument();
      expect(region.querySelectorAll('.MuiPaper-outlined')).toHaveLength(3);
      expect(screen.getAllByRole('status')).toHaveLength(1);
    });

    it('fills the viewport in fullPage mode', () => {
      const { container } = render(<PageSkeleton fullPage />);
      expect(container.querySelector('.MuiContainer-root')).toHaveStyle({ minHeight: '100vh' });
    });

    it('does not force a viewport height by default', () => {
      const { container } = render(<PageSkeleton />);
      expect(container.querySelector('.MuiContainer-root')).not.toHaveStyle({
        minHeight: '100vh',
      });
    });
  });
});
