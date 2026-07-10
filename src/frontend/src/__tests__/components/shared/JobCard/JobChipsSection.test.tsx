import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobChipsSection } from '../../../../components/shared/JobCard/JobChipsSection';

/**
 * Tests for JobChipsSection component
 * Verifies rendering of department and remote chips
 */
describe('JobChipsSection', () => {
  describe('Chip Rendering', () => {
    it('should render department chip when department is provided', () => {
      render(<JobChipsSection department="Engineering" isRemote={false} />);

      expect(screen.getByText('Engineering')).toBeInTheDocument();
    });

    it('should not render department chip when department is undefined', () => {
      render(<JobChipsSection department={undefined} isRemote={false} />);

      expect(screen.queryByText('Engineering')).not.toBeInTheDocument();
    });

    it('should render Remote chip when isRemote is true', () => {
      render(<JobChipsSection department={undefined} isRemote={true} />);

      expect(screen.getByText('Remote')).toBeInTheDocument();
    });

    it('should not render Remote chip when isRemote is false', () => {
      render(<JobChipsSection department={undefined} isRemote={false} />);

      expect(screen.queryByText('Remote')).not.toBeInTheDocument();
    });
  });

  describe('Chip Combinations', () => {
    it('should render both department and remote chips when both are provided', () => {
      render(<JobChipsSection department="Engineering" isRemote={true} />);

      expect(screen.getByText('Engineering')).toBeInTheDocument();
      expect(screen.getByText('Remote')).toBeInTheDocument();
    });

    it('should render no chips when neither department nor remote are provided', () => {
      const { container } = render(<JobChipsSection department={undefined} isRemote={false} />);

      const chips = container.querySelectorAll('.MuiChip-root');
      expect(chips).toHaveLength(0);
    });
  });

  describe('Enrichment chips', () => {
    it('renders category and level slugs as their display labels', () => {
      render(<JobChipsSection category="software_engineering" level="senior" />);

      // FACET_LABELS resolves known slugs to their human labels.
      expect(screen.getByText('Software Engineering')).toBeInTheDocument();
      expect(screen.getByText('Senior')).toBeInTheDocument();
    });

    it('humanizes an UNKNOWN slug via the split("_").join(" ") fallback', () => {
      render(<JobChipsSection category="quantum_widget_wrangler" />);

      expect(screen.getByText('quantum widget wrangler')).toBeInTheDocument();
    });

    it('caps enrichment tags at 4 visible chips and adds a "+N" overflow chip', () => {
      render(<JobChipsSection enrichmentTags={['a', 'b', 'c', 'd', 'e', 'f']} />);

      for (const t of ['a', 'b', 'c', 'd']) {
        expect(screen.getByText(t)).toBeInTheDocument();
      }
      // The 5th and 6th are folded into the overflow chip, not rendered.
      expect(screen.queryByText('e')).not.toBeInTheDocument();
      expect(screen.queryByText('f')).not.toBeInTheDocument();
      expect(screen.getByText('+2')).toBeInTheDocument();
    });

    it('shows no overflow chip when there are exactly 4 tags', () => {
      render(<JobChipsSection enrichmentTags={['a', 'b', 'c', 'd']} />);

      expect(screen.getByText('d')).toBeInTheDocument();
      // No "+N" chip at the boundary.
      expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
    });

    it('renders no chips for empty or undefined enrichmentTags', () => {
      const { container, rerender } = render(<JobChipsSection enrichmentTags={[]} />);
      expect(container.querySelectorAll('.MuiChip-root')).toHaveLength(0);

      rerender(<JobChipsSection enrichmentTags={undefined} />);
      expect(container.querySelectorAll('.MuiChip-root')).toHaveLength(0);
    });
  });
});
