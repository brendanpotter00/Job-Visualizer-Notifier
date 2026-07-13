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
  });
});
