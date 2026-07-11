import { describe, it, expect } from 'vitest';
import { humanOutcomeChip } from '../../../pages/AdminEnrichmentPage/outcomeChip';

const base = {
  humanDecision: null as string | null,
  humanCorrectedAt: null as string | null,
  needsHuman: false,
  judged: true,
  judgePassed: true as boolean | null,
};

describe('humanOutcomeChip', () => {
  it('a confirmed-correct decision wins over everything, even the lock timestamp', () => {
    // A confirmed row also stamps humanCorrectedAt — decision must be checked
    // first so it does not mis-render as "human-corrected".
    expect(
      humanOutcomeChip({
        ...base,
        humanDecision: 'confirmed_correct',
        humanCorrectedAt: '2026-07-09T00:00:00Z',
        needsHuman: false,
      })
    ).toEqual({ label: 'confirmed correct', color: 'success' });
  });

  it("a 'corrected' decision renders human-corrected", () => {
    expect(humanOutcomeChip({ ...base, humanDecision: 'corrected' })).toEqual({
      label: 'human-corrected',
      color: 'info',
    });
  });

  it('a legacy human_corrected_at with no decision still reads as human-corrected', () => {
    expect(
      humanOutcomeChip({ ...base, humanDecision: null, humanCorrectedAt: '2026-01-01T00:00:00Z' })
    ).toEqual({ label: 'human-corrected', color: 'info' });
  });

  it('an unresolved needs-human flag shows "needs human"', () => {
    expect(humanOutcomeChip({ ...base, needsHuman: true })).toEqual({
      label: 'needs human',
      color: 'warning',
    });
  });

  it('falls through to the judge verdict when no human has acted', () => {
    expect(humanOutcomeChip({ ...base, judged: true, judgePassed: true })).toEqual({
      label: 'judge passed',
      color: 'default',
    });
    expect(humanOutcomeChip({ ...base, judged: true, judgePassed: false })).toEqual({
      label: 'judge corrected',
      color: 'default',
    });
    expect(humanOutcomeChip({ ...base, judged: false, judgePassed: null })).toEqual({
      label: 'unjudged',
      color: 'default',
    });
  });
});
