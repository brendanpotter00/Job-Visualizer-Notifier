import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SavedFiltersSectionSkeleton } from '../../../components/saved-filters/SavedFiltersSectionSkeleton';

describe('SavedFiltersSectionSkeleton', () => {
  it('shows the section title as text, not as a heading', () => {
    render(<SavedFiltersSectionSkeleton title="Default time windows" />);
    expect(screen.getByText('Default time windows')).toBeInTheDocument();
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
  });

  it('renders the description line, one placeholder per control, and the save button', () => {
    const { container } = render(<SavedFiltersSectionSkeleton title="Locations" controls={3} />);
    expect(container.querySelectorAll('.MuiSkeleton-root')).toHaveLength(5);
  });

  it('is purely visual — the caller supplies the status region', () => {
    render(<SavedFiltersSectionSkeleton title="Keyword lists" />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
});
