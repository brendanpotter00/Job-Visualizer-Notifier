import { describe, it, expect } from 'vitest';
import { resolveActiveTags } from '../../../features/savedFilters/resolveActiveTags';
import type { KeywordList } from '../../../types';

const lists: KeywordList[] = [
  {
    id: 'builtin-swe',
    name: 'Software Engineering',
    isBuiltin: true,
    position: 999,
    tags: [{ text: 'engineer', mode: 'include' }],
  },
  {
    id: 'list-1',
    name: 'Backend',
    isBuiltin: false,
    position: 0,
    tags: [
      { text: 'golang', mode: 'include' },
      { text: 'intern', mode: 'exclude' },
    ],
  },
];

describe('resolveActiveTags', () => {
  it('returns undefined for a null active id (no keyword filter)', () => {
    expect(resolveActiveTags(null, lists)).toBeUndefined();
  });

  it('resolves a user list id to a copy of its tags', () => {
    const tags = resolveActiveTags('list-1', lists);
    expect(tags).toEqual([
      { text: 'golang', mode: 'include' },
      { text: 'intern', mode: 'exclude' },
    ]);
    // Must be a fresh copy so redux never aliases the cached list.
    expect(tags).not.toBe(lists[1].tags);
  });

  it('resolves the built-in list from the provided lists', () => {
    expect(resolveActiveTags('builtin-swe', lists)).toEqual([
      { text: 'engineer', mode: 'include' },
    ]);
  });

  it('returns undefined when the active id no longer exists', () => {
    expect(resolveActiveTags('deleted-id', lists)).toBeUndefined();
  });
});
