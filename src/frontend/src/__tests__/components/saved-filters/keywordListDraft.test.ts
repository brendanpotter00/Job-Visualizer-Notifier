import { describe, it, expect } from 'vitest';
import {
  addTagToList,
  removeTagFromList,
  toggleTagModeInList,
  cloneDraftList,
  type DraftKeywordList,
} from '../../../components/saved-filters/keywordListDraft';
import { MAX_SEARCH_TAGS } from '../../../constants/tags';

function makeList(tags: DraftKeywordList['tags'] = []): DraftKeywordList {
  return { id: 'list-1', name: 'Backend', tags, isBuiltin: false, position: 0, isNew: false };
}

describe('addTagToList', () => {
  it('trims and appends', () => {
    const list = makeList();
    addTagToList(list, { text: '  golang  ', mode: 'include' });
    expect(list.tags).toEqual([{ text: 'golang', mode: 'include' }]);
  });

  it('ignores an empty or whitespace-only keyword', () => {
    const list = makeList();
    addTagToList(list, { text: '   ', mode: 'include' });
    expect(list.tags).toEqual([]);
  });

  it('de-dupes by text, so re-adding an existing keyword is a no-op', () => {
    // The editor keys tags by text (flip include/exclude via toggleTagModeInList),
    // which is deliberately stricter than the backend.
    const list = makeList([{ text: 'golang', mode: 'include' }]);
    addTagToList(list, { text: 'golang', mode: 'exclude' });
    expect(list.tags).toEqual([{ text: 'golang', mode: 'include' }]);
  });

  it('refuses the keyword that would take the list past the search budget', () => {
    // MAX_SEARCH_TAGS is the SAME number as the backend's per-list storage cap and
    // its per-query keyword budget, and that is not a coincidence: an active list
    // hydrates straight into the Recent page's search parameters on page load. A
    // 21-tag list is therefore a hard 400 on that reader's next visit, with the
    // page offering nothing but a Retry that reissues the rejected request.
    //
    // The cap was added at this function and at `addSearchTagToFilters`, but only
    // the latter had a test — this is the other half.
    const list = makeList(
      Array.from({ length: MAX_SEARCH_TAGS }, (_, n) => ({
        text: `tag-${n}`,
        mode: 'include' as const,
      }))
    );

    addTagToList(list, { text: 'one-too-many', mode: 'include' });

    expect(list.tags).toHaveLength(MAX_SEARCH_TAGS);
    expect(list.tags.map((t) => t.text)).not.toContain('one-too-many');
  });

  it('still accepts the keyword that lands exactly ON the cap', () => {
    // An off-by-one the other way would cost the reader a keyword they are
    // entitled to, silently, with the same invisible failure.
    const list = makeList(
      Array.from({ length: MAX_SEARCH_TAGS - 1 }, (_, n) => ({
        text: `tag-${n}`,
        mode: 'include' as const,
      }))
    );

    addTagToList(list, { text: 'the-last-one', mode: 'include' });

    expect(list.tags).toHaveLength(MAX_SEARCH_TAGS);
    expect(list.tags.map((t) => t.text)).toContain('the-last-one');
  });
});

describe('the rest of the draft mutators', () => {
  it('removes by text and toggles a mode in place', () => {
    const list = makeList([
      { text: 'golang', mode: 'include' },
      { text: 'php', mode: 'exclude' },
    ]);

    toggleTagModeInList(list, 'php');
    expect(list.tags.find((t) => t.text === 'php')?.mode).toBe('include');

    removeTagFromList(list, 'golang');
    expect(list.tags.map((t) => t.text)).toEqual(['php']);
  });

  it('clones deeply, so an edit to the copy never reaches the cached server object', () => {
    const list = makeList([{ text: 'golang', mode: 'include' }]);
    const copy = cloneDraftList(list);
    copy.tags[0].mode = 'exclude';
    expect(list.tags[0].mode).toBe('include');
  });
});
