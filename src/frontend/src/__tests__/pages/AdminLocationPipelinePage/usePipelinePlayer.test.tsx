import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import {
  usePipelinePlayer,
  STEP_MS,
} from '../../../pages/AdminLocationPipelinePage/usePipelinePlayer';

// Example order in fixtures.ts:
// 0 multi-miss · 1 cache-hit · 2 remote-eu · 3 garbage-fail · 4 no-key

describe('usePipelinePlayer', () => {
  it('starts at the raw stage of the first example, idle', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    expect(result.current.exampleIndex).toBe(0);
    expect(result.current.currentStageIndex).toBe(0);
    expect(result.current.phase).toBe('running');
    expect(result.current.isPlaying).toBe(false);
    expect(result.current.showRows).toBe(false);
  });

  it('steps through the full MISS pipeline to a done state', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    for (let i = 0; i < 6; i++) act(() => result.current.stepForward());
    expect(result.current.currentStageIndex).toBe(6); // persist
    expect(result.current.atEnd).toBe(true);
    expect(result.current.phase).toBe('done');
    expect(result.current.showRows).toBe(true);
  });

  it('does not advance past the final stage', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    for (let i = 0; i < 10; i++) act(() => result.current.stepForward());
    expect(result.current.currentStageIndex).toBe(6);
    expect(result.current.atEnd).toBe(true);
  });

  it('cache HIT jumps from Tier-1 straight to persist', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.selectExample(1));
    act(() => result.current.stepForward()); // normalize
    act(() => result.current.stepForward()); // tier1
    expect(result.current.currentStageIndex).toBe(2);
    act(() => result.current.stepForward()); // jumps over LLM/floor/canonicalize
    expect(result.current.currentStageIndex).toBe(6);
    expect(result.current.phase).toBe('done');
    expect(result.current.showRows).toBe(true);
  });

  it('low-confidence example stops at the floor as failed with no rows', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.selectExample(3));
    for (let i = 0; i < 4; i++) act(() => result.current.stepForward());
    expect(result.current.currentStageIndex).toBe(4); // confidence floor
    expect(result.current.atEnd).toBe(true);
    expect(result.current.phase).toBe('failed');
    expect(result.current.showRows).toBe(false);
    // Stepping again must not move past the floor.
    act(() => result.current.stepForward());
    expect(result.current.currentStageIndex).toBe(4);
  });

  it('no-key example stops at the LLM stage, deferred (status NULL)', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.selectExample(4));
    for (let i = 0; i < 3; i++) act(() => result.current.stepForward());
    expect(result.current.currentStageIndex).toBe(3); // Tier-2 (no-op, no key)
    expect(result.current.atEnd).toBe(true);
    expect(result.current.phase).toBe('deferred');
    expect(result.current.showRows).toBe(false);
  });

  it('restart returns to the first stage and pauses', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.stepForward());
    act(() => result.current.stepForward());
    expect(result.current.currentStageIndex).toBe(2);
    act(() => result.current.restart());
    expect(result.current.currentStageIndex).toBe(0);
    expect(result.current.isPlaying).toBe(false);
  });

  it('selecting an example resets to its first stage', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.stepForward());
    act(() => result.current.selectExample(2));
    expect(result.current.exampleIndex).toBe(2);
    expect(result.current.cursor).toBe(0);
    expect(result.current.currentStageIndex).toBe(0);
  });

  it('stepping back decrements the cursor and pauses', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.stepForward());
    act(() => result.current.stepForward());
    act(() => result.current.stepBack());
    expect(result.current.currentStageIndex).toBe(1);
    expect(result.current.isPlaying).toBe(false);
  });
});

describe('usePipelinePlayer · autoplay (fake timers)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('play() sets isPlaying true and a tick advances the cursor one stage', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.play());
    expect(result.current.isPlaying).toBe(true);
    expect(result.current.currentStageIndex).toBe(0);

    act(() => vi.advanceTimersByTime(STEP_MS));
    expect(result.current.currentStageIndex).toBe(1);
    expect(result.current.isPlaying).toBe(true);
  });

  it('autoplay runs to the last stage then halts (timer stops re-arming)', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.play());

    // MISS path has 7 stages (indices 0..6) → 6 ticks reach the end.
    for (let i = 0; i < 6; i++) {
      act(() => vi.advanceTimersByTime(STEP_MS));
    }
    expect(result.current.currentStageIndex).toBe(6);
    expect(result.current.atEnd).toBe(true);
    expect(result.current.phase).toBe('done');

    // Autoplay self-terminates by NOT re-arming the timer at the end (the
    // effect bails on `atEnd`). The cursor freezes — no runaway advance — even
    // though `isPlaying` is left set (the visible "stop" is the halted cursor).
    act(() => vi.advanceTimersByTime(STEP_MS * 3));
    expect(result.current.currentStageIndex).toBe(6);
    expect(result.current.atEnd).toBe(true);
  });

  it('play() while already at the end restarts from cursor 0 and plays', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    // Walk to the end first.
    for (let i = 0; i < 6; i++) act(() => result.current.stepForward());
    expect(result.current.atEnd).toBe(true);

    act(() => result.current.play());
    expect(result.current.currentStageIndex).toBe(0);
    expect(result.current.isPlaying).toBe(true);

    act(() => vi.advanceTimersByTime(STEP_MS));
    expect(result.current.currentStageIndex).toBe(1);
  });

  it('pause() stops playback and clears the timer (no advance after pause)', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    act(() => result.current.play());
    act(() => vi.advanceTimersByTime(STEP_MS));
    expect(result.current.currentStageIndex).toBe(1);

    act(() => result.current.pause());
    expect(result.current.isPlaying).toBe(false);

    // The cleared timer must not fire — the cursor stays put.
    act(() => vi.advanceTimersByTime(STEP_MS * 5));
    expect(result.current.currentStageIndex).toBe(1);
  });

  it('toggle() plays from paused and pauses from playing', () => {
    const { result } = renderHook(() => usePipelinePlayer());
    expect(result.current.isPlaying).toBe(false);

    act(() => result.current.toggle());
    expect(result.current.isPlaying).toBe(true);

    act(() => vi.advanceTimersByTime(STEP_MS));
    expect(result.current.currentStageIndex).toBe(1);

    act(() => result.current.toggle());
    expect(result.current.isPlaying).toBe(false);

    // Paused again — no further advance.
    act(() => vi.advanceTimersByTime(STEP_MS * 3));
    expect(result.current.currentStageIndex).toBe(1);
  });
});
