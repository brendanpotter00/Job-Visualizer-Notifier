import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchTagsInput } from '../../../../components/shared/filters/SearchTagsInput';
import type { SearchTag } from '../../../../types';

describe('SearchTagsInput', () => {
  it('renders placeholder when value is empty', () => {
    render(
      <SearchTagsInput
        value={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    expect(screen.getByPlaceholderText(/Type to add search tags/)).toBeInTheDocument();
  });

  it('renders "Add another tag..." placeholder when value is non-empty', () => {
    const value: SearchTag[] = [{ text: 'senior', mode: 'include' }];
    render(
      <SearchTagsInput
        value={value}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    expect(screen.getByPlaceholderText('Add another tag...')).toBeInTheDocument();
  });

  it('renders existing tags as chips', () => {
    const value: SearchTag[] = [
      { text: 'senior', mode: 'include' },
      { text: 'intern', mode: 'exclude' },
    ];
    render(
      <SearchTagsInput
        value={value}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    expect(screen.getByText('senior')).toBeInTheDocument();
    expect(screen.getByText('intern')).toBeInTheDocument();
  });

  it('on Enter with bare text, calls onAdd with {text, mode:"include"}', async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <SearchTagsInput
        value={[]}
        onAdd={onAdd}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.type(input, 'senior{enter}');
    expect(onAdd).toHaveBeenCalledWith({ text: 'senior', mode: 'include' });
  });

  it('on Enter with "-" prefix, calls onAdd with mode:"exclude"', async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <SearchTagsInput
        value={[]}
        onAdd={onAdd}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.type(input, '-junior{enter}');
    expect(onAdd).toHaveBeenCalledWith({ text: 'junior', mode: 'exclude' });
  });

  it('on Enter with "+" prefix, calls onAdd with mode:"include" and strips prefix', async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <SearchTagsInput
        value={[]}
        onAdd={onAdd}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.type(input, '+ml{enter}');
    expect(onAdd).toHaveBeenCalledWith({ text: 'ml', mode: 'include' });
  });

  it('does not call onAdd on Enter with a prefix-only input (parseSearchTagInput returns null)', async () => {
    // Input is '-' which passes the inputValue.trim() guard (non-empty) but
    // parseSearchTagInput returns null (no body after stripping the '-'
    // prefix). Exercises the `if (parsed)` else branch in handleKeyDown.
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <SearchTagsInput
        value={[]}
        onAdd={onAdd}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.type(input, '-{enter}');
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('does not call onAdd on Enter with empty input', async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <SearchTagsInput
        value={[]}
        onAdd={onAdd}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.keyboard('{Enter}');
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('clears the input after a successful add', async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <SearchTagsInput
        value={[]}
        onAdd={onAdd}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    const input = screen.getByRole('combobox') as HTMLInputElement;
    await user.click(input);
    await user.type(input, 'senior{enter}');
    expect(input.value).toBe('');
  });

  it('calls onToggleMode with chip text when chip is clicked', async () => {
    const onToggleMode = vi.fn();
    const user = userEvent.setup();
    const value: SearchTag[] = [{ text: 'senior', mode: 'include' }];
    render(
      <SearchTagsInput
        value={value}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onToggleMode={onToggleMode}
      />
    );
    await user.click(screen.getByText('senior'));
    expect(onToggleMode).toHaveBeenCalledWith('senior');
  });

  it('calls onRemove when a chip is removed via Backspace', async () => {
    const onRemove = vi.fn();
    const user = userEvent.setup();
    const value: SearchTag[] = [{ text: 'senior', mode: 'include' }];
    render(
      <SearchTagsInput
        value={value}
        onAdd={vi.fn()}
        onRemove={onRemove}
        onToggleMode={vi.fn()}
      />
    );
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.keyboard('{Backspace}');
    expect(onRemove).toHaveBeenCalledWith('senior');
  });

  it('renders include tags with AddIcon and exclude tags with RemoveIcon', () => {
    const value: SearchTag[] = [
      { text: 'alpha', mode: 'include' },
      { text: 'beta', mode: 'exclude' },
    ];
    render(
      <SearchTagsInput
        value={value}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onToggleMode={vi.fn()}
      />
    );
    const alphaChip = screen.getByText('alpha').closest('.MuiChip-root');
    const betaChip = screen.getByText('beta').closest('.MuiChip-root');
    expect(alphaChip).not.toBeNull();
    expect(betaChip).not.toBeNull();
    expect(within(alphaChip as HTMLElement).getByTestId('AddIcon')).toBeInTheDocument();
    expect(within(betaChip as HTMLElement).getByTestId('RemoveIcon')).toBeInTheDocument();
  });
});
