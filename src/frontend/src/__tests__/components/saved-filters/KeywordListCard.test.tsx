import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KeywordListCard } from '../../../components/saved-filters/KeywordListCard';
import type { DraftKeywordList } from '../../../components/saved-filters/keywordListDraft';

const { createMock, updateMock, deleteMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  updateMock: vi.fn(),
  deleteMock: vi.fn(),
}));

vi.mock('../../../features/savedFilters/savedFiltersApi', () => ({
  useCreateKeywordListMutation: () => [createMock, { isLoading: false }],
  useUpdateKeywordListMutation: () => [updateMock, { isLoading: false }],
  useDeleteKeywordListMutation: () => [deleteMock, { isLoading: false }],
}));

const okUnwrap = (value: unknown) => ({ unwrap: () => Promise.resolve(value) });

const persisted: DraftKeywordList = {
  id: 'list-1',
  name: 'Backend',
  tags: [{ text: 'golang', mode: 'include' }],
  isBuiltin: false,
  position: 0,
  isNew: false,
};

const builtin: DraftKeywordList = {
  id: 'builtin-swe',
  name: 'Software Engineering',
  tags: [{ text: 'engineer', mode: 'include' }],
  isBuiltin: true,
  position: 999,
  isNew: false,
};

const newDraft: DraftKeywordList = {
  id: 'temp-1',
  name: '',
  tags: [],
  isBuiltin: false,
  position: 0,
  isNew: true,
};

beforeEach(() => {
  createMock.mockReset();
  updateMock.mockReset();
  deleteMock.mockReset();
});

describe('KeywordListCard', () => {
  it('renders the built-in list as read-only with no edit affordance', () => {
    render(<KeywordListCard list={builtin} />);
    expect(screen.getByText('Software Engineering (default)')).toBeInTheDocument();
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument();
  });

  it('shows a finalized read-only view with an Edit button for a saved list', () => {
    render(<KeywordListCard list={persisted} />);
    expect(screen.getByText('Backend')).toBeInTheDocument();
    expect(screen.getByText('golang')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    // Finalized: not editable until Edit is clicked.
    expect(screen.queryByLabelText('List name')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });

  it('enters edit mode from the finalized view and persists an update immediately', async () => {
    const user = userEvent.setup();
    updateMock.mockReturnValue(okUnwrap({ ...persisted, name: 'Backend & Infra' }));
    render(<KeywordListCard list={persisted} />);

    await user.click(screen.getByRole('button', { name: 'Edit' }));
    const nameField = screen.getByLabelText('List name');
    await user.clear(nameField);
    await user.type(nameField, 'Backend & Infra');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(updateMock).toHaveBeenCalledWith({
      id: 'list-1',
      name: 'Backend & Infra',
      tags: [{ text: 'golang', mode: 'include' }],
    });
    // Back to finalized view after a successful save.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument());
  });

  it('creates a new list (POST) with the keyword added from the top input', async () => {
    const user = userEvent.setup();
    createMock.mockReturnValue(okUnwrap({ ...newDraft, id: 'srv-9', name: 'My List' }));
    const onCreated = vi.fn();
    render(<KeywordListCard list={newDraft} startInEdit onCreated={onCreated} />);

    // "Add to List" input is present (at the top) — add a keyword.
    await user.type(screen.getByPlaceholderText(/Add a keyword/i), 'backend{Enter}');
    expect(screen.getByText('backend')).toBeInTheDocument();

    await user.type(screen.getByLabelText('List name'), 'My List');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(createMock).toHaveBeenCalledWith({
      name: 'My List',
      tags: [{ text: 'backend', mode: 'include' }],
    });
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('temp-1'));
  });

  it('deletes a persisted list and notifies the parent', async () => {
    const user = userEvent.setup();
    deleteMock.mockReturnValue(okUnwrap(undefined));
    const onDeleted = vi.fn();
    render(<KeywordListCard list={persisted} onDeleted={onDeleted} />);

    await user.click(screen.getByRole('button', { name: 'Delete Backend' }));
    expect(deleteMock).toHaveBeenCalledWith('list-1');
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith('list-1'));
  });

  it('discards a never-saved new card on Cancel without calling the API', async () => {
    const user = userEvent.setup();
    const onCancelNew = vi.fn();
    render(<KeywordListCard list={newDraft} startInEdit onCancelNew={onCancelNew} />);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancelNew).toHaveBeenCalledWith('temp-1');
    expect(createMock).not.toHaveBeenCalled();
  });
});
