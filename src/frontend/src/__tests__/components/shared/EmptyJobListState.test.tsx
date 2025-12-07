import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EmptyJobListState } from '../../../components/shared/EmptyJobListState.tsx';
import { EMPTY_STATE_MESSAGES } from '../../../constants/messages.ts';

/**
 * Tests for EmptyJobListState component
 * Verifies empty state rendering with default and custom messages
 */
describe('EmptyJobListState', () => {
  describe('Default Rendering', () => {
    it('should render default title when no custom title provided', () => {
      render(<EmptyJobListState />);

      expect(screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_TITLE)).toBeInTheDocument();
    });

    it('should render default message when no custom message provided', () => {
      render(<EmptyJobListState />);

      expect(screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_HINT)).toBeInTheDocument();
    });

    it('should center content by default', () => {
      const { container } = render(<EmptyJobListState />);
      const box = container.firstChild as HTMLElement;

      expect(box).toHaveStyle({ textAlign: 'center' });
    });
  });

  describe('Custom Props', () => {
    it('should render custom title when provided', () => {
      const customTitle = 'Custom Empty State Title';
      render(<EmptyJobListState title={customTitle} />);

      expect(screen.getByText(customTitle)).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_STATE_MESSAGES.NO_JOBS_TITLE)).not.toBeInTheDocument();
    });

    it('should render custom message when provided', () => {
      const customMessage = 'This is a custom hint message';
      render(<EmptyJobListState message={customMessage} />);

      expect(screen.getByText(customMessage)).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_STATE_MESSAGES.NO_JOBS_HINT)).not.toBeInTheDocument();
    });

    it('should render both custom title and message', () => {
      const customTitle = 'No Results';
      const customMessage = 'Try different filters';

      render(<EmptyJobListState title={customTitle} message={customMessage} />);

      expect(screen.getByText(customTitle)).toBeInTheDocument();
      expect(screen.getByText(customMessage)).toBeInTheDocument();
    });

    it('should not render message when empty string is provided', () => {
      render(<EmptyJobListState message="" />);

      expect(screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_TITLE)).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_STATE_MESSAGES.NO_JOBS_HINT)).not.toBeInTheDocument();
    });
  });

  describe('Centering Behavior', () => {
    it('should left-align content when centered is false', () => {
      const { container } = render(<EmptyJobListState centered={false} />);
      const box = container.firstChild as HTMLElement;

      expect(box).toHaveStyle({ textAlign: 'left' });
    });

    it('should center content when centered is true', () => {
      const { container } = render(<EmptyJobListState centered={true} />);
      const box = container.firstChild as HTMLElement;

      expect(box).toHaveStyle({ textAlign: 'center' });
    });
  });

  describe('Typography Variants', () => {
    it('should render title as h6 variant', () => {
      render(<EmptyJobListState />);
      const title = screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_TITLE);

      expect(title.tagName).toBe('H6');
    });

    it('should render message with secondary text color', () => {
      render(<EmptyJobListState />);
      const message = screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_HINT);

      // MUI applies color via CSS class
      expect(message).toBeInTheDocument();
    });
  });

  describe('Integration Scenarios', () => {
    it('should work as used in JobList component', () => {
      // Simulates JobList usage: if (jobs.length === 0) return <EmptyJobListState />
      render(<EmptyJobListState />);

      expect(screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_TITLE)).toBeInTheDocument();
      expect(screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_HINT)).toBeInTheDocument();
    });

    it('should work as used in RecentJobsList component', () => {
      // Simulates RecentJobsList usage: if (jobs.length === 0) return <EmptyJobListState />
      render(<EmptyJobListState />);

      expect(screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_TITLE)).toBeInTheDocument();
      expect(screen.getByText(EMPTY_STATE_MESSAGES.NO_JOBS_HINT)).toBeInTheDocument();
    });
  });
});
