import type { NameSearchRow } from './nameSearchNarration';

/**
 * The morph, as numbers — when each row arrives and when it leaves.
 *
 * Kept out of `NameSearchProgress.tsx` for the same reason the copy is: the shape of
 * the animation is the part worth testing without a browser and without waiting for
 * it. The component turns these into `animation-delay` values and does nothing else
 * with them.
 *
 * THE WHOLE ANIMATION IS `animation-delay`. NO TIMERS AND NO STATE. A JS-driven
 * morph would need a run counter to reset on a second search, a `setState` from a
 * `setTimeout` on every beat, and it would be the only thing on the page still
 * animating after the test that rendered it had finished. Everything here is
 * computed once, from the rows, and handed to CSS.
 *
 * `ROW_IN_MS` is `DiscoveryNetworkLog`'s arrival exactly (260ms fade+rise) and
 * `ROW_FOLD_MS` its departure (a 300ms collapse), because a reader who has seen one
 * of these panels should recognise the other.
 */
export const ROW_IN_MS = 260;
export const ROW_STAGGER_MS = 60;
export const ROW_FOLD_MS = 300;
export const ROW_FOLD_STAGGER_MS = 30;
export const VERDICT_IN_MS = 220;
export const STATUS_FADE_MS = 220;
/** How long a settled list stays readable before it narrows. */
export const HOLD_MS = 620;
/** No sentence flashes past faster than this, however few rows there are to fold. */
export const MIN_STATUS_MS = 520;
/**
 * A ceiling for the collapse, not a measured height — measuring would be a layout
 * read per row. It comfortably covers the two-line board row; a taller one clips a
 * few pixels at the very start of a fade it is already losing, which is not
 * perceptible. It is only ever a ceiling DURING the animation: no fill holds it
 * afterwards, so a row that stays sizes to its own content.
 */
export const ROW_MAX_HEIGHT = '120px';

/** When one row arrives, when it leaves, and whether it grew in from nothing. */
export interface MorphRowTiming {
  inAt: number;
  /** ms before it folds away, or `null` when it survives the morph. */
  outAt: number | null;
  /** It came from the SECOND search, so it grows in after the list has narrowed. */
  late: boolean;
}

export interface MorphTimeline {
  /** Index-aligned with the rows it was built from. */
  rows: MorphRowTiming[];
  /** When a board's verdict appears — right after the junk has folded away. */
  verdictAt: number;
  /** End to end. The status line is fitted to this, so the two finish together. */
  totalMs: number;
}

/**
 * Every row's place in the morph.
 *
 * TWO RULES DECIDE EVERYTHING HERE, and both are about not lying:
 *
 * 1. **A fold only runs when something survives it.** A search that came back with
 *    nothing but junk has no answer to narrow to, and a list that folded itself
 *    away to an empty box would be deleting its own evidence. Those rows land and
 *    stay, and `CareersPageAnswer` below says "No job board found" in words.
 * 2. **The boards only fold when there IS an answer.** With no confirmed board and
 *    no careers page, the boards we found are the most we have; they are the thing
 *    `CompanyCandidateList` is about to offer behind its disclosure, so they stay.
 */
export function morphTimeline(rows: NameSearchRow[]): MorphTimeline {
  const early = rows.filter((row) => !row.late);
  const discarded = rows.filter((row) => row.kind === 'discarded');
  const rejected = rows.filter((row) => row.kind === 'rejected');
  const answers = rows.filter((row) => row.kind === 'answer');

  const landEnd = early.length > 0 ? (early.length - 1) * ROW_STAGGER_MS + ROW_IN_MS : 0;
  const foldsJunk = discarded.length > 0 && rows.length > discarded.length;
  const fold1Start = landEnd + HOLD_MS;
  const fold1End = foldsJunk
    ? fold1Start + ROW_FOLD_MS + (discarded.length - 1) * ROW_FOLD_STAGGER_MS
    : landEnd;

  const verdictAt = fold1End;
  const foldsBoards = rejected.length > 0 && answers.length > 0;
  const fold2Start = verdictAt + HOLD_MS;
  const fold2End = foldsBoards
    ? fold2Start + ROW_FOLD_MS + (rejected.length - 1) * ROW_FOLD_STAGGER_MS
    : verdictAt;
  const answerAt = fold2End;

  let landed = 0;
  let junk = 0;
  let board = 0;
  const timings = rows.map((row): MorphRowTiming => {
    const inAt = row.late ? answerAt : landed++ * ROW_STAGGER_MS;
    let outAt: number | null = null;
    if (row.kind === 'discarded') {
      outAt = foldsJunk ? fold1Start + junk * ROW_FOLD_STAGGER_MS : null;
      junk += 1;
    } else if (row.kind === 'rejected') {
      outAt = foldsBoards ? fold2Start + board * ROW_FOLD_STAGGER_MS : null;
      board += 1;
    }
    return { inAt, outAt, late: row.late === true };
  });

  return { rows: timings, verdictAt, totalMs: answerAt + ROW_IN_MS };
}

/**
 * How long each sentence of the status line holds — the morph's own length, split
 * between them.
 *
 * Fitted rather than fixed so the line and the list finish together: a status that
 * outlasted the fold would still be describing the search after the answer had
 * arrived. The floor stops a two-row search from strobing five sentences in a
 * second.
 */
export function statusDwell(totalMs: number, steps: number): number {
  return Math.max(MIN_STATUS_MS, Math.round(totalMs / Math.max(steps, 1)));
}
