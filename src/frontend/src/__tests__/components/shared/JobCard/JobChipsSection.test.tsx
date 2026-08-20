import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobChipsSection } from '../../../../components/shared/JobCard/JobChipsSection';

/**
 * Tests for JobChipsSection component
 * Verifies rendering of the remote chip and the enrichment category/level chips.
 * The ATS-provided department chip was removed from the card (it restated the
 * enrichment chips), so this component no longer takes a `department` prop.
 */
describe('JobChipsSection', () => {
  describe('Chip Rendering', () => {
    it('should render Remote chip when isRemote is true', () => {
      render(<JobChipsSection isRemote={true} />);

      expect(screen.getByText('Remote')).toBeInTheDocument();
    });

    it('should not render Remote chip when isRemote is false', () => {
      render(<JobChipsSection isRemote={false} />);

      expect(screen.queryByText('Remote')).not.toBeInTheDocument();
    });

    it('should render no chips when nothing is provided', () => {
      const { container } = render(<JobChipsSection isRemote={false} />);

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

    it('renders remote alongside the enrichment chips', () => {
      const { container } = render(
        <JobChipsSection isRemote={true} category="software_engineering" level="senior" />
      );

      expect(container.querySelectorAll('.MuiChip-root')).toHaveLength(3);
    });
  });
});
