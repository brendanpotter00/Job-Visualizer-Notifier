import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ScorecardPanel } from '../../../pages/AdminEnrichmentPage/components/ScorecardPanel';

/**
 * The panel takes plain props and needs no store, so it renders directly.
 *
 * The two things worth pinning here are both about ABSENCE: a tile that should
 * not appear yet, and a tile that has silently shown '—' against every real
 * payload since it was written.
 */
const V6_SCORECARD: Record<string, unknown> = {
  n: 252,
  gold_quality: 'draft',
  category_accuracy: 0.9087,
  category_f1_macro: 0.9152,
  level_exact_accuracy: 0.7897,
  level_filter_consistent_accuracy: 0.8214,
  tags_f1: 0.2159,
  tags_token_f1: 0.289,
  judge_kappa_prejudge: 0.2477,
};

describe('ScorecardPanel', () => {
  it('renders exactly 4 tiles for a v6-shaped scorecard', () => {
    render(
      <ScorecardPanel scorecard={V6_SCORECARD} scorecardTickUuid={null} knobs={null} />
    );
    expect(screen.getByText('Category accuracy')).toBeInTheDocument();
    expect(screen.getByText('Level (filter-consistent)')).toBeInTheDocument();
    expect(screen.getByText('Tags (token F1)')).toBeInTheDocument();
    expect(screen.getByText('Judge κ')).toBeInTheDocument();
    // The fifth tile must NOT appear until the enricher emits the metric —
    // otherwise it sits at '—' for weeks and reads as a broken pipeline.
    expect(screen.queryByText('Subcategory (primary)')).not.toBeInTheDocument();
  });

  it('renders a 5th tile once the subcategory metric is present', () => {
    render(
      <ScorecardPanel
        scorecard={{
          ...V6_SCORECARD,
          subcategory_primary_accuracy_nonempty: 0.71,
          subcategory_set_f1: 0.63,
          subcategory_leak_rate: 0.04,
          subcategory_n: 67,
        }}
        scorecardTickUuid={null}
        knobs={null}
      />
    );
    expect(screen.getByText('Subcategory (primary)')).toBeInTheDocument();
    expect(screen.getByText('71.0%')).toBeInTheDocument();
    expect(screen.getByText(/set F1 63.0% · leak 4.0% · n=67/)).toBeInTheDocument();
  });

  it('⚠ renders a NUMBER for judge κ from judge_kappa_prejudge, not an em dash', () => {
    // The regression the old fixture was hiding. `scoring.py::to_dict` emits
    // `judge_kappa_prejudge`; the panel read `judge_kappa`, so this tile has
    // ALWAYS been '—' against a real payload.
    render(
      <ScorecardPanel
        scorecard={{ judge_kappa_prejudge: 0.2477 }}
        scorecardTickUuid={null}
        knobs={null}
      />
    );
    expect(screen.getByText('0.25')).toBeInTheDocument();
  });

  it('still reads a legacy judge_kappa key when that is all there is', () => {
    render(
      <ScorecardPanel
        scorecard={{ judge_kappa: 0.31 }}
        scorecardTickUuid={null}
        knobs={null}
      />
    );
    expect(screen.getByText('0.31')).toBeInTheDocument();
  });

  it('renders an em dash for judge κ when neither key is present', () => {
    render(<ScorecardPanel scorecard={{}} scorecardTickUuid={null} knobs={null} />);
    const kappaTile = screen.getByText('Judge κ').closest('div') as HTMLElement;
    expect(kappaTile.textContent).toContain('—');
  });
});
