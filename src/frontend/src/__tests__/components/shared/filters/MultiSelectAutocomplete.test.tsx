import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MultiSelectAutocomplete } from '../../../../components/shared/filters/MultiSelectAutocomplete';

describe('MultiSelectAutocomplete', () => {
  it('renders label on the text input', () => {
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={['SF', 'NYC']}
        value={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    expect(screen.getByLabelText('Location')).toBeInTheDocument();
  });

  it('renders default placeholder from label lowercased', () => {
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={['SF', 'NYC']}
        value={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    expect(screen.getByPlaceholderText('Select location...')).toBeInTheDocument();
  });

  it('renders custom placeholder when provided', () => {
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={['SF', 'NYC']}
        value={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        placeholder="Pick a city"
      />
    );
    expect(screen.getByPlaceholderText('Pick a city')).toBeInTheDocument();
  });

  it('renders existing value items as chips', () => {
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={['SF', 'NYC']}
        value={['SF', 'NYC']}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    expect(screen.getByText('SF')).toBeInTheDocument();
    expect(screen.getByText('NYC')).toBeInTheDocument();
  });

  it('opens listbox with options on focus', async () => {
    const user = userEvent.setup();
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={['SF', 'NYC']}
        value={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    await user.click(screen.getByRole('combobox'));
    const listbox = await screen.findByRole('listbox');
    expect(within(listbox).getAllByRole('option')).toHaveLength(2);
  });

  it('calls onAdd when a new option is selected', async () => {
    const onAdd = vi.fn();
    const onRemove = vi.fn();
    const user = userEvent.setup();
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={['SF', 'NYC']}
        value={[]}
        onAdd={onAdd}
        onRemove={onRemove}
      />
    );
    await user.click(screen.getByRole('combobox'));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'SF' }));
    expect(onAdd).toHaveBeenCalledWith('SF');
    expect(onRemove).not.toHaveBeenCalled();
  });

  it('calls onRemove when a chip is removed via backspace', async () => {
    const onAdd = vi.fn();
    const onRemove = vi.fn();
    const user = userEvent.setup();
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={['SF', 'NYC']}
        value={['SF']}
        onAdd={onAdd}
        onRemove={onRemove}
      />
    );
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.keyboard('{Backspace}');
    expect(onRemove).toHaveBeenCalledWith('SF');
  });

  it('calls onRemove (but not onAdd) when an already-selected option is re-clicked', async () => {
    const onAdd = vi.fn();
    const onRemove = vi.fn();
    const user = userEvent.setup();
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={['SF', 'NYC']}
        value={['SF']}
        onAdd={onAdd}
        onRemove={onRemove}
      />
    );
    await user.click(screen.getByRole('combobox'));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'SF' }));
    expect(onRemove).toHaveBeenCalledWith('SF');
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('handles empty options list without error', async () => {
    const user = userEvent.setup();
    render(
      <MultiSelectAutocomplete
        label="Location"
        options={[]}
        value={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
      />
    );
    await user.click(screen.getByRole('combobox'));
    expect(await screen.findByText(/no options/i)).toBeInTheDocument();
  });
});
