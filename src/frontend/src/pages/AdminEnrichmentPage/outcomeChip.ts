/**
 * Pure mapping from an enrichment row's status fields to the single "Outcome"
 * chip shown in the admin tables (React-free, mirrors verdict.ts). Two
 * independent axes collapse here into one label, in precedence order:
 *
 *  1. The HUMAN decision (human_decision) — the reviewer's verdict — wins over
 *     everything, because a human resolving a row is the final word:
 *       - 'confirmed_correct' → "confirmed correct"  (flagged, but the AI was right)
 *       - 'corrected'         → "human-corrected"     (labels were wrong, human fixed them)
 *     A legacy human_corrected_at with no decision is treated as 'corrected'.
 *  2. Otherwise the pipeline state: an unresolved needs-human flag →
 *     "needs human".
 *  3. Otherwise the JUDGE verdict — the machine's opinion — "judge passed" /
 *     "judge corrected" / "unjudged".
 *
 * Both human decisions stamp human_corrected_at, so checking human_decision
 * FIRST (not the timestamp) is what keeps a confirmed row from mis-rendering as
 * "human-corrected".
 */

export type OutcomeChipColor = 'success' | 'info' | 'warning' | 'default';

export interface OutcomeChip {
  label: string;
  color: OutcomeChipColor;
}

export interface OutcomeChipInput {
  humanDecision: string | null;
  humanCorrectedAt: string | null;
  needsHuman: boolean;
  judged: boolean;
  judgePassed: boolean | null;
}

export function humanOutcomeChip(row: OutcomeChipInput): OutcomeChip {
  if (row.humanDecision === 'confirmed_correct') {
    return { label: 'confirmed correct', color: 'success' };
  }
  if (row.humanDecision === 'corrected' || row.humanCorrectedAt) {
    return { label: 'human-corrected', color: 'info' };
  }
  if (row.needsHuman) {
    return { label: 'needs human', color: 'warning' };
  }
  return {
    label: row.judged ? (row.judgePassed ? 'judge passed' : 'judge corrected') : 'unjudged',
    color: 'default',
  };
}
