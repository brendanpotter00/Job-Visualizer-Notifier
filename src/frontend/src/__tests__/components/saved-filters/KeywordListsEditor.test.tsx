import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KeywordListsEditor } from '../../../components/saved-filters/KeywordListsEditor';
import type { DraftKeywordList } from '../../../components/saved-filters/keywordListDraft';

// KeywordListCard (rendered for each list) reaches for the mutation hooks.
vi.mock('../../../features/savedFilters/savedFiltersApi', () => ({
  useCreateKeywordListMutation: () => [vi.fn(), { isLoading: false }],
  useUpdateKeywordListMutation: () => [vi.fn(), { isLoading: false }],
  useDeleteKeywordListMutation: () => [vi.fn(), { isLoading: false }],
}));

const lists: DraftKeywordList[] = [
  {
    id: 'list-1',
    name: 'Backend',
    tags: [{ text: 'golang', mode: 'include' }],
    isBuiltin: false,
    position: 0,
    isNew: false,
  },
  {
    id: 'builtin-swe',
    name: 'Software Engineering',
    tags: [{ text: 'engineer', mode: 'include' }],
    isBuiltin: true,
    position: 999,
    isNew: false,
  },
];

function renderEditor(overrides: Partial<React.ComponentProps<typeof KeywordListsEditor>> = {}) {
  const props: React.ComponentProps<typeof KeywordListsEditor> = {
    lists,
    onAddList: vi.fn(),
    onCardCreated: vi.fn(),
    onCardCancelNew: vi.fn(),
    onCardDeleted: vi.fn(),
    onCardContentSaved: vi.fn(),
    activeKeywordListId: null,
    onActiveChange: vi.fn(),
    activeDirty: false,
    activeSaving: false,
    activeSuccess: false,
    activeError: null,
    onSaveActive: vi.fn(),
    ...overrides,
  };
  render(<KeywordListsEditor {...props} />);
  return props;
}

describe('KeywordListsEditor active-list selection (Critique #3)', () => {
  it('checks "No keyword filter" when no list is active', () => {
    renderEditor({ activeKeywordListId: null });
    expect(screen.getByRole('radio', { name: 'No keyword filter' })).toBeChecked();
  });

  it('clears the active list when "No keyword filter" is chosen', async () => {
    const user = userEvent.setup();
    const onActiveChange = vi.fn();
    renderEditor({ activeKeywordListId: 'list-1', onActiveChange });
    await user.click(screen.getByRole('radio', { name: 'No keyword filter' }));
    expect(onActiveChange).toHaveBeenCalledWith(null);
  });

  it('selects a list as active via its radio', async () => {
    const user = userEvent.setup();
    const onActiveChange = vi.fn();
    renderEditor({ onActiveChange });
    await user.click(
      screen.getByRole('radio', { name: 'Set Backend as the active keyword list' })
    );
    expect(onActiveChange).toHaveBeenCalledWith('list-1');
  });

  it('marks the active card and leaves "No keyword filter" unchecked', () => {
    renderEditor({ activeKeywordListId: 'list-1' });
    expect(
      screen.getByRole('radio', { name: 'Set Backend as the active keyword list' })
    ).toBeChecked();
    expect(screen.getByRole('radio', { name: 'No keyword filter' })).not.toBeChecked();
  });

  it('saves the active selection via its own Save button', async () => {
    const user = userEvent.setup();
    const onSaveActive = vi.fn();
    renderEditor({ activeDirty: true, onSaveActive });
    await user.click(screen.getByRole('button', { name: 'Save active list' }));
    expect(onSaveActive).toHaveBeenCalledTimes(1);
  });

  it('disables the active-list Save button when the selection is unchanged', () => {
    renderEditor({ activeDirty: false });
    expect(screen.getByRole('button', { name: 'Save active list' })).toBeDisabled();
  });
});
