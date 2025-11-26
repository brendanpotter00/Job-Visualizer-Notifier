import type { RoleClassification, SoftwareRoleCategory, Job } from '../types';
import { ROLE_CLASSIFICATION_CONFIG } from '../config/roleClassificationConfig';
import { CLASSIFICATION_CONFIDENCE } from '../constants/classificationConstants';

/**
 * Check if combined text matches exclusion patterns
 */
function checkExclusion(combinedText: string): boolean {
  return ROLE_CLASSIFICATION_CONFIG.exclusionPatterns.some((pattern) => pattern.test(combinedText));
}

/**
 * Find keyword matches for each category
 */
function findCategoryMatches(combinedText: string): Record<SoftwareRoleCategory, string[]> {
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

  Object.entries(ROLE_CLASSIFICATION_CONFIG.categoryKeywords).forEach(([category, keywords]) => {
    keywords.forEach((keyword) => {
      if (combinedText.includes(keyword.toLowerCase())) {
        categoryMatches[category as SoftwareRoleCategory].push(keyword);
      }
    });
  });

  return categoryMatches;
}

/**
 * Select the best category based on keyword matches
 */
function selectBestCategory(
  categoryMatches: Record<SoftwareRoleCategory, string[]>
): { category: SoftwareRoleCategory; matchCount: number } {
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

  return { category: bestCategory, matchCount: maxMatches };
}

/**
 * Calculate confidence score based on matches and context
 */
function calculateConfidence(
  matchCount: number,
  bestCategory: SoftwareRoleCategory,
  categoryMatches: Record<SoftwareRoleCategory, string[]>,
  title: string,
  isTechDepartment: boolean
): number {
  let confidence: number = CLASSIFICATION_CONFIDENCE.BASE;

  if (matchCount > 0) {
    // More matches = higher confidence, but cap the increase
    confidence = Math.min(
      CLASSIFICATION_CONFIDENCE.BASE + matchCount * CLASSIFICATION_CONFIDENCE.MATCH_INCREMENT,
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

  return confidence;
}

/**
 * Classifies a job role based on title, department, team, and tags.
 * Uses keyword matching and confidence scoring.
 */
export function classifyJobRole(job: Partial<Job>): RoleClassification {
  const { title = '', department = '', team = '', tags = [] } = job;

  // Combine all text fields for analysis
  const combinedText = [title, department, team, ...tags].join(' ').toLowerCase();

  // Check exclusion patterns first
  if (checkExclusion(combinedText)) {
    return {
      isSoftwareAdjacent: false,
      category: 'nonTech',
      confidence: CLASSIFICATION_CONFIDENCE.EXCLUSION,
      matchedKeywords: [],
    };
  }

  // Find keyword matches for each category
  const categoryMatches = findCategoryMatches(combinedText);

  // Select the best category based on matches
  const { category: bestCategory, matchCount } = selectBestCategory(categoryMatches);

  // Check if it matches tech department
  const isTechDepartment = ROLE_CLASSIFICATION_CONFIG.techDepartments.some((pattern) =>
    pattern.test(department)
  );

  // Adjust category if tech department but no specific match
  let finalCategory = bestCategory;
  if (isTechDepartment && bestCategory === 'nonTech') {
    finalCategory = 'otherTech';
  }

  // Determine if software-adjacent
  const isSoftwareAdjacent = finalCategory !== 'nonTech' || (isTechDepartment && matchCount === 0);

  // Calculate confidence score
  const confidence = calculateConfidence(matchCount, finalCategory, categoryMatches, title, isTechDepartment);

  return {
    isSoftwareAdjacent,
    category: finalCategory,
    confidence,
    matchedKeywords: categoryMatches[finalCategory],
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
