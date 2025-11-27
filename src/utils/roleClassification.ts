import type { RoleClassification, SoftwareRoleCategory, Job } from '../types';
import { ROLE_CLASSIFICATION_CONFIG } from '../config/roleClassificationConfig';
import { CLASSIFICATION_CONFIDENCE } from '../constants/classificationConstants';

/**
 * Checks if the job matches any exclusion patterns for non-technical roles.
 *
 * Exclusion patterns identify roles that should be classified as nonTech
 * with high confidence, such as "recruiter", "coordinator", "sales", etc.
 *
 * @param combinedText - Lowercase concatenated text from job fields
 * @returns True if job matches exclusion patterns (is non-tech)
 *
 * @see {@link ROLE_CLASSIFICATION_CONFIG.exclusionPatterns}
 */
function checkExclusion(combinedText: string): boolean {
  return ROLE_CLASSIFICATION_CONFIG.exclusionPatterns.some((pattern) => pattern.test(combinedText));
}

/**
 * Finds keyword matches for each role category.
 *
 * Scans the job text for keywords defined in the classification config,
 * building a record of which keywords matched for each category.
 *
 * **Time Complexity:** O(c × k) where:
 * - c = number of categories (14)
 * - k = average keywords per category (~10-20)
 *
 * @param combinedText - Lowercase concatenated text from job fields
 * @returns Record mapping each category to its matched keywords
 *
 * @example
 * ```typescript
 * const matches = findCategoryMatches('senior frontend engineer react vue');
 * // Returns:
 * // {
 * //   frontend: ['frontend', 'react', 'vue'],
 * //   backend: [],
 * //   ...
 * // }
 * ```
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
 * Selects the best role category based on keyword match counts.
 *
 * **Algorithm:**
 * 1. First pass: Check specific categories (frontend, backend, etc.)
 * 2. Select category with most keyword matches
 * 3. If no matches, check 'otherTech' as fallback
 * 4. If still no matches, defaults to 'nonTech'
 *
 * **Priority Order:**
 * - Specific categories (frontend, backend, mobile, etc.) - highest priority
 * - otherTech - fallback for generic tech roles
 * - nonTech - default when no tech keywords found
 *
 * @param categoryMatches - Record of keywords matched per category
 * @returns Object with best category and its match count
 *
 * @example
 * ```typescript
 * const matches = {
 *   frontend: ['react', 'vue'],
 *   backend: ['api'],
 *   otherTech: ['software'],
 *   // ... other categories with 0 matches
 * };
 *
 * const result = selectBestCategory(matches);
 * // Returns: { category: 'frontend', matchCount: 2 }
 * // Frontend wins with 2 matches vs backend's 1 match
 * ```
 */
function selectBestCategory(categoryMatches: Record<SoftwareRoleCategory, string[]>): {
  category: SoftwareRoleCategory;
  matchCount: number;
} {
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
 * Calculates confidence score for the role classification.
 *
 * **Scoring Algorithm:**
 * 1. Base confidence: 0.5 for any match
 * 2. Add 0.1 per keyword match (capped at 0.85)
 * 3. Add 0.15 bonus if keyword appears in job title
 * 4. Add 0.05 bonus for tech department
 * 5. Cap 'otherTech' category at 0.75 confidence
 * 6. Maximum confidence: 0.95 (except exclusions at 0.9)
 *
 * **Confidence Interpretation:**
 * - 0.9-1.0: Very high confidence (exclusions, strong title matches)
 * - 0.75-0.9: High confidence (multiple keyword matches + title/dept bonus)
 * - 0.5-0.75: Medium confidence (otherTech, or few specific keywords)
 * - 0.0-0.5: Low confidence (fallback categories, weak signals)
 *
 * @param matchCount - Number of keywords matched
 * @param bestCategory - Selected role category
 * @param categoryMatches - All keyword matches by category
 * @param title - Job title (for title match bonus)
 * @param isTechDepartment - Whether job is in a tech department
 * @returns Confidence score between 0 and 1
 *
 * @see {@link CLASSIFICATION_CONFIDENCE} for threshold constants
 * @see docs/architecture.md for confidence scoring table
 *
 * @example
 * ```typescript
 * const confidence = calculateConfidence(
 *   3,                                    // 3 keyword matches
 *   'frontend',                           // Category
 *   { frontend: ['react', 'vue', 'ui'] }, // Matched keywords
 *   'Senior Frontend Engineer',           // Title (contains 'frontend')
 *   true                                  // Is tech department
 * );
 * // Returns: ~0.95
 * // Calculation: 0.5 (base) + 0.3 (3 matches) + 0.15 (title) + 0.05 (dept) = 1.0 → capped at 0.95
 * ```
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
 * Classifies a job role into one of 14 categories using keyword matching and confidence scoring.
 *
 * This is the main entry point for role classification, running on every job during
 * API transformation. The algorithm is heuristic-based and uses confidence scoring
 * to indicate classification certainty.
 *
 * **Algorithm Overview:**
 * 1. Combine all text fields (title, department, team, tags) into searchable text
 * 2. Check exclusion patterns for non-tech roles (high confidence early exit)
 * 3. Find keyword matches across all 14 categories
 * 4. Select category with most matches (specific categories prioritized)
 * 5. Apply tech department heuristic if no specific match
 * 6. Calculate confidence score based on matches, title, and department
 * 7. Return classification with category, confidence, and matched keywords
 *
 * **Categories (14 total):**
 * - Specific Engineering: frontend, backend, fullstack, mobile, data, ml, devops,
 *   platform, qa, security, graphics, embedded
 * - Generic Tech: otherTech (fallback for generic software roles)
 * - Non-Technical: nonTech (no tech keywords found)
 *
 * **Time Complexity:** O(c × k) where:
 * - c = number of categories (14)
 * - k = average keywords per category (~10-20)
 *
 * @param job - Partial job object with at least title, department, team, or tags
 * @returns RoleClassification with category, confidence score, and matched keywords
 *
 * @example
 * ```typescript
 * const classification = classifyJobRole({
 *   title: 'Senior Frontend Engineer',
 *   department: 'Engineering',
 *   tags: ['React', 'TypeScript', 'UI/UX'],
 * });
 *
 * // Returns:
 * // {
 * //   isSoftwareAdjacent: true,
 * //   category: 'frontend',
 * //   confidence: 0.95,
 * //   matchedKeywords: ['frontend', 'react', 'typescript', 'ui']
 * // }
 * ```
 *
 * @example
 * ```typescript
 * const classification = classifyJobRole({
 *   title: 'Technical Recruiter',
 *   department: 'People Operations',
 * });
 *
 * // Returns:
 * // {
 * //   isSoftwareAdjacent: false,
 * //   category: 'nonTech',
 * //   confidence: 0.9,  // High confidence due to exclusion pattern
 * //   matchedKeywords: []
 * // }
 * ```
 *
 * @see {@link checkExclusion} for non-tech exclusion logic
 * @see {@link findCategoryMatches} for keyword matching
 * @see {@link selectBestCategory} for category selection
 * @see {@link calculateConfidence} for confidence scoring
 * @see {@link ROLE_CLASSIFICATION_CONFIG} for keyword definitions
 * @see {@link CLASSIFICATION_CONFIDENCE} for scoring constants
 * @see docs/architecture.md for detailed algorithm flowchart
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
  const confidence = calculateConfidence(
    matchCount,
    finalCategory,
    categoryMatches,
    title,
    isTechDepartment
  );

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
