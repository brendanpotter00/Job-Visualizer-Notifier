import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobChipsSection } from '../../../../components/shared/JobCard/JobChipsSection';
import type { Job } from '../../../../types';

/**
 * Tests for JobChipsSection component
 * Verifies rendering of department, remote, and software category chips
 */
describe('JobChipsSection', () => {
  const mockClassification: Job['classification'] = {
    category: 'frontend',
    confidence: 0.85,
    isSoftwareAdjacent: true,
    matchedKeywords: ['react', 'javascript'],
  };

  describe('Chip Rendering', () => {
    it('should render department chip when department is provided', () => {
      render(
        <JobChipsSection
          department="Engineering"
          isRemote={false}
          classification={{ ...mockClassification, isSoftwareAdjacent: false }}
        />
      );

      expect(screen.getByText('Engineering')).toBeInTheDocument();
    });

    it('should not render department chip when department is undefined', () => {
      render(
        <JobChipsSection
          department={undefined}
          isRemote={false}
          classification={{ ...mockClassification, isSoftwareAdjacent: false }}
        />
      );

      expect(screen.queryByText('Engineering')).not.toBeInTheDocument();
    });

    it('should render Remote chip when isRemote is true', () => {
      render(
        <JobChipsSection
          department={undefined}
          isRemote={true}
          classification={{ ...mockClassification, isSoftwareAdjacent: false }}
        />
      );

      expect(screen.getByText('Remote')).toBeInTheDocument();
    });

    it('should not render Remote chip when isRemote is false', () => {
      render(
        <JobChipsSection
          department={undefined}
          isRemote={false}
          classification={{ ...mockClassification, isSoftwareAdjacent: false }}
        />
      );

      expect(screen.queryByText('Remote')).not.toBeInTheDocument();
    });

    it('should render software category chip when isSoftwareAdjacent is true', () => {
      render(
        <JobChipsSection
          department={undefined}
          isRemote={false}
          classification={mockClassification}
        />
      );

      expect(screen.getByText('frontend')).toBeInTheDocument();
    });

    it('should not render software category chip when isSoftwareAdjacent is false', () => {
      render(
        <JobChipsSection
          department={undefined}
          isRemote={false}
          classification={{ ...mockClassification, isSoftwareAdjacent: false }}
        />
      );

      expect(screen.queryByText('frontend')).not.toBeInTheDocument();
    });

    it('should render all chips when all conditions are met', () => {
      render(
        <JobChipsSection
          department="Engineering"
          isRemote={true}
          classification={mockClassification}
        />
      );

      expect(screen.getByText('Engineering')).toBeInTheDocument();
      expect(screen.getByText('Remote')).toBeInTheDocument();
      expect(screen.getByText('frontend')).toBeInTheDocument();
    });

    it('should render no chips when all props are false/undefined', () => {
      render(
        <JobChipsSection
          department={undefined}
          isRemote={false}
          classification={{ ...mockClassification, isSoftwareAdjacent: false }}
        />
      );

      const chips = screen.queryAllByRole('button');
      expect(chips).toHaveLength(0);
    });
  });

  describe('Classification Categories', () => {
    const categories = [
      'frontend',
      'backend',
      'fullstack',
      'mobile',
      'data',
      'ml',
      'devops',
      'platform',
      'qa',
      'security',
    ] as const;

    categories.forEach((category) => {
      it(`should render ${category} category chip`, () => {
        render(
          <JobChipsSection
            department={undefined}
            isRemote={false}
            classification={{
              category,
              confidence: 0.85,
              isSoftwareAdjacent: true,
              matchedKeywords: [],
            }}
          />
        );

        expect(screen.getByText(category)).toBeInTheDocument();
      });
    });
  });
});
