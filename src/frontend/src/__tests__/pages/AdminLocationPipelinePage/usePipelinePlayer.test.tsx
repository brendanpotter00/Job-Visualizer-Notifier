import { describe, it, expect } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { usePipelinePlayer } from '../../../pages/AdminLocationPipelinePage/usePipelinePlayer';

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
