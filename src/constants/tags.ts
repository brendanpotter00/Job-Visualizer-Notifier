import type { SearchTag } from '../types';

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
