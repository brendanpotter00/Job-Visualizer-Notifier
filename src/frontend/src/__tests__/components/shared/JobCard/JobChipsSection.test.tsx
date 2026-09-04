import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobChipsSection } from '../../../../components/shared/JobCard/JobChipsSection';

/**
 * Tests for JobChipsSection component
 * Verifies rendering of the enrichment category/level chips. The Remote chip
 * is NOT rendered here — it lives in JobListingCard's location row (see
 * JobCard.test.tsx).
 */
describe('JobChipsSection', () => {
  describe('Chip Rendering', () => {
    it('should render nothing when there is no enrichment', () => {
      const { container } = render(<JobChipsSection />);

      expect(container).toBeEmptyDOMElement();
    });

    it('should not render a Remote chip', () => {
      render(<JobChipsSection category="software_engineering" />);

      // The positive half matters: without it this passes even if the
      // component renders nothing at all.
      expect(screen.getByText('Software Engineering')).toBeInTheDocument();
      expect(screen.queryByText('Remote')).not.toBeInTheDocument();
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

    it('renders only the chips it is given', () => {
      const { container } = render(<JobChipsSection level="senior" />);

      expect(screen.getByText('Senior')).toBeInTheDocument();
      expect(container.querySelectorAll('.MuiChip-root')).toHaveLength(1);
    });
  });
});
