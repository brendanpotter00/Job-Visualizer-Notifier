import type { RoleClassification, SoftwareRoleCategory, Job } from '../types';
import { ROLE_CLASSIFICATION_CONFIG } from '../config/roleClassificationConfig';
import { CLASSIFICATION_CONFIDENCE } from '../constants/classificationConstants';

/**
 * Classifies a job role based on title, department, team, and tags.
 * Uses keyword matching and confidence scoring.
 */
export function classifyJobRole(job: Partial<Job>): RoleClassification {
  const { title = '', department = '', team = '', tags = [] } = job;

  // Combine all text fields for analysis
  const combinedText = [title, department, team, ...tags].join(' ').toLowerCase();

  // Check exclusion patterns first
  const isExcluded = ROLE_CLASSIFICATION_CONFIG.exclusionPatterns.some((pattern) =>
    pattern.test(combinedText)
  );

  if (isExcluded) {
    return {
      isSoftwareAdjacent: false,
      category: 'nonTech',
      confidence: CLASSIFICATION_CONFIDENCE.EXCLUSION,
      matchedKeywords: [],
    };
  }

  // Track matches for each category
  const categoryMatches: Record<SoftwareRoleCategory, string[]> = {
    frontend: [],
    backend: [],
    fullstack: [],
    mobile: [],
    data: [],
    ml: [],
    devops: [],
    platform: [],
    qa: [],
    security: [],
    graphics: [],
    embedded: [],
    otherTech: [],
    nonTech: [],
  };

  // Find keyword matches for each category
  Object.entries(ROLE_CLASSIFICATION_CONFIG.categoryKeywords).forEach(([category, keywords]) => {
    keywords.forEach((keyword) => {
      if (combinedText.includes(keyword.toLowerCase())) {
        categoryMatches[category as SoftwareRoleCategory].push(keyword);
      }
    });
  });

  // Determine the category with the most matches (excluding otherTech for now)
  let bestCategory: SoftwareRoleCategory = 'nonTech';
  let maxMatches = 0;

  // First pass: Check all categories except otherTech and nonTech
  Object.entries(categoryMatches).forEach(([category, matches]) => {
    if (category !== 'otherTech' && category !== 'nonTech' && matches.length > maxMatches) {
      maxMatches = matches.length;
      bestCategory = category as SoftwareRoleCategory;
    }
  });

  // If no specific category matched, check otherTech
  if (bestCategory === 'nonTech' && categoryMatches.otherTech.length > 0) {
    bestCategory = 'otherTech';
    maxMatches = categoryMatches.otherTech.length;
  }

  // Check if it matches tech department
  const isTechDepartment = ROLE_CLASSIFICATION_CONFIG.techDepartments.some((pattern) =>
    pattern.test(department)
  );

  // Determine if software-adjacent
  const isSoftwareAdjacent = bestCategory !== 'nonTech' || (isTechDepartment && maxMatches === 0);

  // If tech department but no specific category, mark as otherTech
  if (isTechDepartment && bestCategory === 'nonTech') {
    bestCategory = 'otherTech';
  }

  // Calculate confidence score
  let confidence: number = CLASSIFICATION_CONFIDENCE.BASE;

  if (maxMatches > 0) {
    // More matches = higher confidence, but cap the increase
    confidence = Math.min(
      CLASSIFICATION_CONFIDENCE.BASE + maxMatches * CLASSIFICATION_CONFIDENCE.MATCH_INCREMENT,
      CLASSIFICATION_CONFIDENCE.MAX_MATCH_BONUS
    );
  }

  // Title matches are more confident than tag matches
  const titleKeywords = categoryMatches[bestCategory].filter((keyword) =>
    title.toLowerCase().includes(keyword.toLowerCase())
  );

  if (titleKeywords.length > 0) {
    confidence = Math.min(
      confidence + CLASSIFICATION_CONFIDENCE.TITLE_BONUS,
      CLASSIFICATION_CONFIDENCE.MAX_CONFIDENCE
    );
  }

  if (isTechDepartment && bestCategory !== 'nonTech') {
    // Tech department adds a small confidence boost
    confidence = Math.min(
      confidence + CLASSIFICATION_CONFIDENCE.TECH_DEPT_BONUS,
      CLASSIFICATION_CONFIDENCE.MAX_CONFIDENCE
    );
  }

  // Cap confidence for otherTech category
  if (bestCategory === 'otherTech') {
    confidence = Math.min(confidence, CLASSIFICATION_CONFIDENCE.OTHER_TECH_MAX);
  }

  return {
    isSoftwareAdjacent,
    category: bestCategory,
    confidence,
    matchedKeywords: categoryMatches[bestCategory],
  };
}

/**
 * Helper function to check if a job is a software role
 */
export function isSoftwareRole(job: Job): boolean {
  return job.classification.isSoftwareAdjacent;
}

/**
 * Get keywords for a specific category
 */
export function getCategoryKeywords(category: SoftwareRoleCategory): string[] {
  return ROLE_CLASSIFICATION_CONFIG.categoryKeywords[category] || [];
}
