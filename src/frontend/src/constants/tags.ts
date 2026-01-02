import type { SearchTag } from '../types';

// ============================================================================
// Role Tag Group Types
// ============================================================================

/**
 * A named group of tags that can be toggled together
 */
export interface RoleTagGroup {
  /** Unique identifier for the group */
  id: string;
  /** Display name for the group */
  label: string;
  /** Description shown in UI */
  description: string;
  /** Whether tags should be included or excluded when enabled */
  mode: 'include' | 'exclude';
  /** The tag texts in this group */
  tags: readonly string[];
}

// ============================================================================
// Predefined Tag Groups
// ============================================================================

/**
 * Predefined search tags for software engineering roles
 * Used by the "Software engineering roles only" toggle
 */
export const SOFTWARE_ENGINEERING_TAGS: readonly SearchTag[] = [
  { text: 'software engineer', mode: 'include' },
  { text: 'developer', mode: 'include' },
  { text: 'engineer', mode: 'include' },
  { text: 'data engineer', mode: 'include' },
  { text: 'backend', mode: 'include' },
  { text: 'frontend', mode: 'include' },
] as const;

/**
 * Tags for manager/leadership roles (to exclude non-IC roles)
 */
export const MANAGER_TAGS: readonly string[] = [
  'manager',
  'director',
  'head of',
  'vp',
  'vice president',
  'chief',
  'lead',
  'supervisor',
] as const;

/**
 * Tags for senior+ level roles
 */
export const SENIOR_PLUS_TAGS: readonly string[] = [
  'senior',
  'sr.',
  'sr ',
  'staff',
  'principal',
  'distinguished',
  'fellow',
  'architect',
] as const;

/**
 * Tags for entry-level roles
 */
export const ENTRY_LEVEL_TAGS: readonly string[] = [
  'junior',
  'jr.',
  'jr ',
  'entry',
  'associate',
  'intern',
  'internship',
  'new grad',
  'graduate',
] as const;

/**
 * Tags for contract/temporary roles
 */
export const CONTRACT_TAGS: readonly string[] = [
  'contract',
  'contractor',
  'temp',
  'temporary',
  'freelance',
  'consultant',
] as const;

// ============================================================================
// Role Tag Group Definitions
// ============================================================================

/**
 * All available role tag groups
 */
export const ROLE_TAG_GROUPS: readonly RoleTagGroup[] = [
  {
    id: 'exclude-managers',
    label: 'Exclude Managers',
    description: 'Hide manager, director, VP, and other leadership roles',
    mode: 'exclude',
    tags: MANAGER_TAGS,
  },
  {
    id: 'senior-plus',
    label: 'Senior+ Only',
    description: 'Show only senior, staff, principal, and higher level roles',
    mode: 'include',
    tags: SENIOR_PLUS_TAGS,
  },
  {
    id: 'entry-level',
    label: 'Entry Level Only',
    description: 'Show only junior, intern, and entry-level roles',
    mode: 'include',
    tags: ENTRY_LEVEL_TAGS,
  },
  {
    id: 'exclude-entry',
    label: 'Exclude Entry Level',
    description: 'Hide junior, intern, and entry-level roles',
    mode: 'exclude',
    tags: ENTRY_LEVEL_TAGS,
  },
  {
    id: 'exclude-contract',
    label: 'Exclude Contract',
    description: 'Hide contract, temporary, and freelance roles',
    mode: 'exclude',
    tags: CONTRACT_TAGS,
  },
] as const;

/**
 * Get a role tag group by its ID
 */
export function getRoleTagGroupById(id: string): RoleTagGroup | undefined {
  return ROLE_TAG_GROUPS.find((group) => group.id === id);
}

/**
 * Convert a role tag group to SearchTag array based on its mode
 */
export function roleTagGroupToSearchTags(group: RoleTagGroup): SearchTag[] {
  return group.tags.map((text) => ({ text, mode: group.mode }));
}

/**
 * Helper to check if a search tag is one of the predefined software engineering tags
 */
export function isSoftwareEngineeringTag(tag: SearchTag): boolean {
  return SOFTWARE_ENGINEERING_TAGS.some(
    (seTag) => seTag.text === tag.text && seTag.mode === tag.mode
  );
}

/**
 * Helper to get just the text values of software engineering tags
 */
export function getSoftwareEngineeringTagTexts(): string[] {
  return SOFTWARE_ENGINEERING_TAGS.map((tag) => tag.text);
}

/**
 * Check if software-only mode is enabled
 * (all software engineering tags are present with 'include' mode)
 */
export function isSoftwareOnlyEnabled(searchTags: SearchTag[] | undefined): boolean {
  if (!searchTags || searchTags.length === 0) {
    return false;
  }

  const seTagTexts = getSoftwareEngineeringTagTexts();

  return seTagTexts.every((text) =>
    searchTags.some((tag) => tag.text === text && tag.mode === 'include')
  );
}

/**
 * Add all software engineering tags to the provided tags array
 * Returns a new array with SE tags added (no duplicates)
 */
export function addAllSoftwareEngineeringTags(currentTags: SearchTag[] | undefined): SearchTag[] {
  const tags = currentTags || [];
  const tagsToAdd = [...SOFTWARE_ENGINEERING_TAGS];
  const existingTexts = new Set(tags.map((tag) => tag.text));

  // Only add tags that don't already exist
  const newTags = tagsToAdd.filter((tag) => !existingTexts.has(tag.text));

  return [...tags, ...newTags];
}

/**
 * Remove all software engineering tags from the provided tags array
 * Returns a new array with SE tags removed (preserves other tags)
 */
export function removeAllSoftwareEngineeringTags(
  currentTags: SearchTag[] | undefined
): SearchTag[] | undefined {
  if (!currentTags || currentTags.length === 0) {
    return undefined;
  }

  const seTagTexts = getSoftwareEngineeringTagTexts();
  const filtered = currentTags.filter((tag) => !seTagTexts.includes(tag.text));

  return filtered.length === 0 ? undefined : filtered;
}
