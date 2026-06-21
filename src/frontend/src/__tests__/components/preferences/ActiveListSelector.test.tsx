import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActiveListSelector } from '../../../components/preferences/ActiveListSelector';
import type { DraftKeywordList } from '../../../components/preferences/keywordListDraft';

const lists: DraftKeywordList[] = [
  { id: 'a', name: 'Backend', tags: [], isBuiltin: false, position: 0, isNew: false },
  { id: 'b', name: 'Frontend', tags: [], isBuiltin: false, position: 1, isNew: false },
  {
    id: 'builtin-swe',
    name: 'Software Engineering',
    tags: [],
    isBuiltin: true,
    position: 999,
    isNew: false,
  },
];

describe('ActiveListSelector (single shared active list)', () => {
  it('describes the selection as applying to all pages and shows the active list', () => {
    render(
      <ActiveListSelector selectableLists={lists} activeKeywordListId="a" onChange={vi.fn()} />
    );
    expect(screen.getByText(/applied by default on all pages/i)).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveTextContent('Backend');
  });

  it('emits the chosen list id', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ActiveListSelector selectableLists={lists} activeKeywordListId={null} onChange={onChange} />
    );
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: 'Frontend' }));
    expect(onChange).toHaveBeenCalledWith('b');
  });

  it('emits null for the None option', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ActiveListSelector selectableLists={lists} activeKeywordListId="a" onChange={onChange} />
    );
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: 'None' }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
