/**
 * Drives the scripted playback of the Location Pipeline visualizer.
 *
 * Pure local state (useReducer) — no Redux, no network. The hook owns the
 * current example, the cursor along that example's branch path, and the
 * autoplay timer. Components are presentational and read derived values.
 */
import { useCallback, useEffect, useMemo, useReducer } from 'react';
import { EXAMPLES, PATHS, STAGES, type Branch, type PipelineExample } from './fixtures';

/** Terminal/visual phase of the run at the current cursor. */
export type Phase = 'running' | 'done' | 'failed' | 'deferred';

/** Milliseconds each stage holds during autoplay. */
export const STEP_MS = 1200;

interface PlayerState {
  exampleIndex: number;
  cursor: number;
  isPlaying: boolean;
}

type Action =
  | { type: 'SELECT'; index: number }
  | { type: 'NEXT' }
  | { type: 'PREV' }
  | { type: 'RESTART' }
  | { type: 'PLAY' }
  | { type: 'PAUSE' };

function pathFor(exampleIndex: number): number[] {
  return PATHS[EXAMPLES[exampleIndex].branch];
}

function lastCursor(exampleIndex: number): number {
  return pathFor(exampleIndex).length - 1;
}

function reducer(state: PlayerState, action: Action): PlayerState {
  switch (action.type) {
    case 'SELECT':
      return { exampleIndex: action.index, cursor: 0, isPlaying: false };
    case 'NEXT': {
      if (state.cursor >= lastCursor(state.exampleIndex)) {
        return { ...state, isPlaying: false };
      }
      return { ...state, cursor: state.cursor + 1 };
    }
    case 'PREV':
      return { ...state, cursor: Math.max(0, state.cursor - 1), isPlaying: false };
    case 'RESTART':
      return { ...state, cursor: 0, isPlaying: false };
    case 'PLAY': {
      // Restart from the top if we're already at the end.
      const cursor = state.cursor >= lastCursor(state.exampleIndex) ? 0 : state.cursor;
      return { ...state, cursor, isPlaying: true };
    }
    case 'PAUSE':
      return { ...state, isPlaying: false };
    default:
      return state;
  }
}

function computePhase(branch: Branch, currentStageIndex: number, atEnd: boolean): Phase {
  // The confidence-floor failure is visible the moment we land on the floor box.
  if (branch === 'fail' && currentStageIndex >= 4) return 'failed';
  if (branch === 'nokey' && atEnd) return 'deferred';
  if (atEnd && (branch === 'miss' || branch === 'hit')) return 'done';
  return 'running';
}

export interface PipelinePlayer {
  example: PipelineExample;
  examples: PipelineExample[];
  exampleIndex: number;
  /** The full ordered list of stages (always 7) for rendering the rail. */
  stages: typeof STAGES;
  /** Stage indices this example actually visits. */
  path: number[];
  /** Position along `path`. */
  cursor: number;
  /** The absolute stage index (0–6) currently active. */
  currentStageIndex: number;
  isPlaying: boolean;
  atEnd: boolean;
  phase: Phase;
  /** Whether the DB tables should show their rows (only on a successful run). */
  showRows: boolean;
  selectExample: (index: number) => void;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  stepForward: () => void;
  stepBack: () => void;
  restart: () => void;
}

export function usePipelinePlayer(): PipelinePlayer {
  const [state, dispatch] = useReducer(reducer, {
    exampleIndex: 0,
    cursor: 0,
    isPlaying: false,
  });

  const path = useMemo(() => pathFor(state.exampleIndex), [state.exampleIndex]);
  const atEnd = state.cursor >= path.length - 1;
  const currentStageIndex = path[state.cursor];
  const example = EXAMPLES[state.exampleIndex];
  const phase = computePhase(example.branch, currentStageIndex, atEnd);

  // Autoplay: advance one step per tick while playing. Re-arms on every cursor
  // change; the reducer flips `isPlaying` off once NEXT hits the last stage.
  useEffect(() => {
    if (!state.isPlaying || atEnd) return;
    const timer = setTimeout(() => dispatch({ type: 'NEXT' }), STEP_MS);
    return () => clearTimeout(timer);
  }, [state.isPlaying, state.cursor, atEnd]);

  const selectExample = useCallback((index: number) => dispatch({ type: 'SELECT', index }), []);
  const play = useCallback(() => dispatch({ type: 'PLAY' }), []);
  const pause = useCallback(() => dispatch({ type: 'PAUSE' }), []);
  const toggle = useCallback(
    () => dispatch({ type: state.isPlaying ? 'PAUSE' : 'PLAY' }),
    [state.isPlaying]
  );
  const stepForward = useCallback(() => dispatch({ type: 'NEXT' }), []);
  const stepBack = useCallback(() => dispatch({ type: 'PREV' }), []);
  const restart = useCallback(() => dispatch({ type: 'RESTART' }), []);

  return {
    example,
    examples: EXAMPLES,
    exampleIndex: state.exampleIndex,
    stages: STAGES,
    path,
    cursor: state.cursor,
    currentStageIndex,
    isPlaying: state.isPlaying,
    atEnd,
    phase,
    showRows: phase === 'done',
    selectExample,
    play,
    pause,
    toggle,
    stepForward,
    stepBack,
    restart,
  };
}
