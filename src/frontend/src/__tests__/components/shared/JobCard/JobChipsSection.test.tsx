import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobChipsSection } from '../../../../components/shared/JobCard/JobChipsSection';

// The reveal flag comes from context. Stub the hook rather than standing up a
// store + provider: this component is a pure renderer and the provider's own
// behaviour is covered in subcategoryReveal.test.tsx.
const revealState = { enabled: false };
vi.mock('../../../../features/settings/subcategoryReveal', () => ({
  useSubcategoryRevealEnabled: () => revealState.enabled,
}));

/**
 * Tests for JobChipsSection component
 * Verifies rendering of the remote chip and the enrichment category/level chips.
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

  describe('Subcategory chips (they SUBSTITUTE for the category chip)', () => {
    function chipLabels(container: HTMLElement): string[] {
      return [...container.querySelectorAll('.MuiChip-label')].map((n) => n.textContent ?? '');
    }

    describe('with the reveal flag ON', () => {
      beforeEach(() => {
        revealState.enabled = true;
      });

      it('renders the specialty chip and NOT the category chip', () => {
        render(
          <JobChipsSection
            category="software_engineering"
            level="senior"
            subcategories={['backend']}
          />
        );

        expect(screen.getByText('Backend')).toBeInTheDocument();
        // THE SUBSTITUTION. Both would say the same thing twice and cost a row
        // of vertical space on every card.
        expect(screen.queryByText('Software Engineering')).not.toBeInTheDocument();
      });

      it('renders two subcategories IN THE GIVEN ORDER, primary first', () => {
        const { container } = render(
          <JobChipsSection
            category="software_engineering"
            subcategories={['backend', 'ai_engineering']}
          />
        );

        expect(chipLabels(container)).toEqual(['Backend', 'AI Engineering']);
      });

      it('renders the CATEGORY chip when the array is EMPTY', () => {
        // ~9% of SWE rows end here permanently, and 100% do during the backfill.
        // A literal "subcategories replace the category" substitution would give
        // those cards no chip at all.
        render(<JobChipsSection category="software_engineering" subcategories={[]} />);

        expect(screen.getByText('Software Engineering')).toBeInTheDocument();
      });

      it('renders the CATEGORY chip when the array is NULL', () => {
        render(<JobChipsSection category="software_engineering" subcategories={null} />);

        expect(screen.getByText('Software Engineering')).toBeInTheDocument();
      });

      it('humanizes an unknown subcategory slug', () => {
        render(
          <JobChipsSection
            category="software_engineering"
            subcategories={['quantum_widget_wrangler']}
          />
        );

        expect(screen.getByText('quantum widget wrangler')).toBeInTheDocument();
      });

      it('leaves Remote and level untouched, and the chip COUNT unchanged', () => {
        const { container } = render(
          <JobChipsSection
            isRemote
            category="software_engineering"
            level="senior"
            subcategories={['backend']}
          />
        );

        // Exactly three, same as today — Remote + one facet chip + level. THAT
        // is the substitution, proven by arithmetic rather than by inspection.
        expect(chipLabels(container)).toEqual(['Remote', 'Backend', 'Senior']);
      });
    });

    describe('with the reveal flag OFF', () => {
      beforeEach(() => {
        revealState.enabled = false;
      });

      it('is byte-identical to today: the CATEGORY chip, never the specialty', () => {
        const { container } = render(
          <JobChipsSection
            isRemote
            category="software_engineering"
            level="senior"
            subcategories={['backend']}
          />
        );

        expect(chipLabels(container)).toEqual(['Remote', 'Software Engineering', 'Senior']);
        expect(screen.queryByText('Backend')).not.toBeInTheDocument();
      });
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
      render(<JobChipsSection isRemote={true} category="software_engineering" level="senior" />);

      expect(screen.getByText('Remote')).toBeInTheDocument();
      expect(screen.getByText('Software Engineering')).toBeInTheDocument();
      expect(screen.getByText('Senior')).toBeInTheDocument();
    });
  });
});
