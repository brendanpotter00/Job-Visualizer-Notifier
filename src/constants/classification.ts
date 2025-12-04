/**
 * Confidence thresholds for role classification algorithm
 *
 * The classification system uses keyword matching and department analysis
 * to determine if a job is software-related and categorize it appropriately.
 *
 * Confidence scoring works as follows:
 * 1. Start with BASE confidence (0.5)
 * 2. Add MATCH_INCREMENT per keyword match (0.1 each)
 * 3. Cap keyword matches at MAX_MATCH_BONUS (0.85)
 * 4. Add TITLE_BONUS if keywords appear in job title (0.15)
 * 5. Add TECH_DEPT_BONUS for tech departments (0.05)
 * 6. Never exceed MAX_CONFIDENCE (0.95)
 * 7. Cap "otherTech" category at OTHER_TECH_MAX (0.75)
 * 8. Excluded roles get EXCLUSION confidence (0.9)
 */
export const CLASSIFICATION_CONFIDENCE = {
  /**
   * Starting confidence for any keyword match
   */
  BASE: 0.5,

  /**
   * Confidence increment per keyword match
   * Example: 3 matches = 0.5 + (3 × 0.1) = 0.8
   */
  MATCH_INCREMENT: 0.1,

  /**
   * Maximum confidence from keyword matches alone
   * Prevents over-confidence from many keyword matches
   */
  MAX_MATCH_BONUS: 0.85,

  /**
   * Bonus added when keyword appears in job title
   * Title matches are stronger signals than tag/description matches
   */
  TITLE_BONUS: 0.15,

  /**
   * Bonus added for tech department classification
   * Small boost for jobs in engineering/tech departments
   */
  TECH_DEPT_BONUS: 0.05,

  /**
   * Absolute maximum confidence score
   * Never exceeded regardless of matches
   */
  MAX_CONFIDENCE: 0.95,

  /**
   * Maximum confidence for "otherTech" category
   * Lower cap since this is a catch-all category
   */
  OTHER_TECH_MAX: 0.75,

  /**
   * Confidence for explicitly excluded roles
   * High confidence that job is NOT software-related
   */
  EXCLUSION: 0.9,
} as const;
