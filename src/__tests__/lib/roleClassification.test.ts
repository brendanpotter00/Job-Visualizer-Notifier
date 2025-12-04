import { describe, it, expect } from 'vitest';
import { classifyJobRole, isSoftwareRole, getCategoryKeywords } from '../../lib/roleClassification';
import type { Job } from '../../types';

describe('classifyJobRole', () => {
  describe('Frontend roles', () => {
    it('should classify "Senior Frontend Engineer" as frontend', () => {
      const job = {
        title: 'Senior Frontend Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('frontend');
      expect(result.matchedKeywords).toContain('frontend');
      expect(result.confidence).toBeGreaterThan(0.7);
    });

    it('should classify React developer as frontend', () => {
      const job = {
        title: 'React Developer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('frontend');
      expect(result.matchedKeywords).toContain('react');
    });

    it('should classify UI Engineer as frontend', () => {
      const job = {
        title: 'UI Engineer',
        department: 'Product',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('frontend');
    });
  });

  describe('Backend roles', () => {
    it('should classify "Backend Engineer" as backend', () => {
      const job = {
        title: 'Backend Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('backend');
      expect(result.matchedKeywords).toContain('backend');
    });

    it('should classify API Developer as backend', () => {
      const job = {
        title: 'API Developer',
        department: 'Technology',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('backend');
    });
  });

  describe('Fullstack roles', () => {
    it('should classify "Software Engineer" as fullstack', () => {
      const job = {
        title: 'Software Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('fullstack');
    });

    it('should classify "Full Stack Developer" as fullstack', () => {
      const job = {
        title: 'Full Stack Developer',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('fullstack');
    });
  });

  describe('Mobile roles', () => {
    it('should classify "iOS Engineer" as mobile', () => {
      const job = {
        title: 'iOS Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('mobile');
      expect(result.matchedKeywords).toContain('ios');
    });

    it('should classify "Android Developer" as mobile', () => {
      const job = {
        title: 'Android Developer',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('mobile');
    });
  });

  describe('Data roles', () => {
    it('should classify "Data Engineer" as data', () => {
      const job = {
        title: 'Data Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('data');
    });

    it('should classify "Data Scientist" as data', () => {
      const job = {
        title: 'Data Scientist',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('data');
    });
  });

  describe('ML/AI roles', () => {
    it('should classify "Machine Learning Engineer" as ml', () => {
      const job = {
        title: 'Machine Learning Engineer',
        department: 'R&D',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('ml');
    });

    it('should classify "AI Engineer" as ml', () => {
      const job = {
        title: 'AI Engineer',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('ml');
    });
  });

  describe('DevOps roles', () => {
    it('should classify "DevOps Engineer" as devops', () => {
      const job = {
        title: 'DevOps Engineer',
        department: 'Infrastructure',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('devops');
    });

    it('should classify "Site Reliability Engineer" as devops', () => {
      const job = {
        title: 'Site Reliability Engineer',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('devops');
    });
  });

  describe('QA roles', () => {
    it('should classify "QA Engineer" as qa', () => {
      const job = {
        title: 'QA Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('qa');
    });

    it('should classify "Test Automation Engineer" as qa', () => {
      const job = {
        title: 'Test Automation Engineer',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('qa');
    });
  });

  describe('Non-tech roles', () => {
    it('should classify "HR Manager" as nonTech', () => {
      const job = {
        title: 'HR Manager',
        department: 'Human Resources',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(false);
      expect(result.category).toBe('nonTech');
    });

    it('should classify "Sales Executive" as nonTech', () => {
      const job = {
        title: 'Sales Executive',
        department: 'Sales',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(false);
      expect(result.category).toBe('nonTech');
    });

    it('should classify "Marketing Manager" as nonTech', () => {
      const job = {
        title: 'Marketing Manager',
        department: 'Marketing',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(false);
      expect(result.category).toBe('nonTech');
    });

    it('should classify "Recruiter" as nonTech', () => {
      const job = {
        title: 'Technical Recruiter',
        department: 'Talent Acquisition',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(false);
      expect(result.category).toBe('nonTech');
    });
  });

  describe('Edge cases and ambiguous roles', () => {
    it('should handle empty title', () => {
      const job = {
        title: '',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('otherTech');
    });

    it('should handle missing department', () => {
      const job = {
        title: 'Software Engineer',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('fullstack');
    });

    it('should use tags for classification', () => {
      const job = {
        title: 'Engineer',
        department: 'Technology',
        tags: ['react', 'javascript', 'frontend'],
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      expect(result.category).toBe('frontend');
    });

    it('should have higher confidence for clear titles', () => {
      const job = {
        title: 'Senior Frontend Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.confidence).toBeGreaterThanOrEqual(0.8);
    });

    it('should have lower confidence for ambiguous titles', () => {
      const job = {
        title: 'Technical Program Manager',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.confidence).toBeLessThan(0.8);
    });

    it('should handle multiple category matches', () => {
      const job = {
        title: 'Full Stack Engineer with DevOps experience',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.isSoftwareAdjacent).toBe(true);
      // Should pick the category with most matches or first found
      expect(['fullstack', 'devops']).toContain(result.category);
    });
  });

  describe('Confidence scoring', () => {
    it('should have high confidence for specific tech roles', () => {
      const job = {
        title: 'React Frontend Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.confidence).toBeGreaterThan(0.8);
    });

    it('should have medium confidence for generic tech roles', () => {
      const job = {
        title: 'Engineer',
        department: 'Engineering',
      };

      const result = classifyJobRole(job);

      expect(result.confidence).toBeGreaterThan(0.5);
      expect(result.confidence).toBeLessThan(0.9);
    });

    it('should have high confidence for excluded non-tech roles', () => {
      const job = {
        title: 'HR Business Partner',
        department: 'Human Resources',
      };

      const result = classifyJobRole(job);

      expect(result.confidence).toBeGreaterThan(0.8);
      expect(result.category).toBe('nonTech');
    });
  });
});

describe('isSoftwareRole', () => {
  it('should return true for software roles', () => {
    const job: Job = {
      id: '1',
      source: 'greenhouse',
      company: 'test',
      title: 'Software Engineer',
      createdAt: '2025-11-20T12:00:00Z',
      url: 'https://example.com',
      classification: {
        isSoftwareAdjacent: true,
        category: 'fullstack',
        confidence: 0.9,
        matchedKeywords: ['software engineer'],
      },
      raw: {},
    };

    expect(isSoftwareRole(job)).toBe(true);
  });

  it('should return false for non-software roles', () => {
    const job: Job = {
      id: '1',
      source: 'greenhouse',
      company: 'test',
      title: 'HR Manager',
      createdAt: '2025-11-20T12:00:00Z',
      url: 'https://example.com',
      classification: {
        isSoftwareAdjacent: false,
        category: 'nonTech',
        confidence: 0.9,
        matchedKeywords: [],
      },
      raw: {},
    };

    expect(isSoftwareRole(job)).toBe(false);
  });
});

describe('getCategoryKeywords', () => {
  it('should return keywords for frontend category', () => {
    const keywords = getCategoryKeywords('frontend');

    expect(keywords).toContain('react');
    expect(keywords).toContain('frontend');
    expect(keywords.length).toBeGreaterThan(0);
  });

  it('should return keywords for backend category', () => {
    const keywords = getCategoryKeywords('backend');

    expect(keywords).toContain('backend');
    expect(keywords).toContain('api');
  });

  it('should return empty array for nonTech category', () => {
    const keywords = getCategoryKeywords('nonTech');

    expect(keywords).toEqual([]);
  });
});
