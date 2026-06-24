import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SectionSaveButton } from '../../../components/saved-filters/SectionSaveButton';

const baseProps = {
  dirty: true,
  saving: false,
  success: false,
  error: null,
  onSave: () => {},
};

describe('SectionSaveButton', () => {
  it('enables and fires onSave when dirty', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<SectionSaveButton {...baseProps} onSave={onSave} />);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toBeEnabled();
    await user.click(button);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('is disabled when not dirty', () => {
    render(<SectionSaveButton {...baseProps} dirty={false} />);
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('shows "Saving…" and is disabled while saving', () => {
    render(<SectionSaveButton {...baseProps} saving />);
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  });

  it('renders the error message', () => {
    render(<SectionSaveButton {...baseProps} error="Boom" />);
    expect(screen.getByText('Boom')).toBeInTheDocument();
  });

  it('shows the saved confirmation only when clean', () => {
    const { rerender } = render(<SectionSaveButton {...baseProps} dirty={false} success />);
    expect(screen.getByText('Saved.')).toBeInTheDocument();
    // Editing again (dirty) hides the stale confirmation.
    rerender(<SectionSaveButton {...baseProps} dirty success />);
    expect(screen.queryByText('Saved.')).not.toBeInTheDocument();
  });

  it('honors a custom label', () => {
    render(<SectionSaveButton {...baseProps} label="Save locations" />);
    expect(screen.getByRole('button', { name: 'Save locations' })).toBeInTheDocument();
  });
});
