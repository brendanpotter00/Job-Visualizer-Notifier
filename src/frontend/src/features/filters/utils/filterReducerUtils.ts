import type { SearchTag } from '../../../types';
import {
  SOFTWARE_ENGINEERING_TAGS,
  canAddSearchTag,
  getSoftwareEngineeringTagTexts,
  roomForSearchTags,
} from '../../../constants/tags.ts';

/**
 * Shared utility functions for filter reducer logic.
 * These functions operate on filter state objects and are designed to work with Immer.
 */

/**
 * Interface for filter state with search tags
 */
interface FiltersWithSearchTags {
  searchTags?: SearchTag[];
}

/**
 * Interface for filter state with location
 */
interface FiltersWithLocation {
  location?: string[];
}

/**
 * Interface for filter state with software-only flag
 */
interface FiltersWithSoftwareOnly extends FiltersWithSearchTags {
  softwareOnly: boolean;
}

// ============================================================================
// Search Tag Utilities
// ============================================================================

/**
 * Set search tags to a specific value or undefined
 */
export function setSearchTags(filters: FiltersWithSearchTags, tags: SearchTag[] | undefined): void {
  filters.searchTags = tags;
}

/**
 * Add a search tag to filters with trim, duplicate checking and a hard cap.
 *
 * The cap is `MAX_SEARCH_TAGS`, which is the search endpoint's per-query keyword
 * budget: past it, the next Recent Jobs request is a 400 and the page has no
 * affordance but a Retry that reissues the same rejected request. Refusing the
 * add is the honest end of that trade — the reader sees the chip fail to appear,
 * rather than seeing it appear and silently not apply.
 */
export function addSearchTagToFilters(filters: FiltersWithSearchTags, tag: SearchTag): void {
  const trimmedText = tag.text.trim();
  if (!trimmedText) return;

  const newTag = { text: trimmedText, mode: tag.mode };

  if (!filters.searchTags) {
    filters.searchTags = [newTag];
  } else {
    const exists = filters.searchTags.some((t) => t.text === newTag.text);
    if (!exists && canAddSearchTag(filters.searchTags)) {
      filters.searchTags.push(newTag);
    }
  }
}

/**
 * Remove a search tag from filters by text
 */
export function removeSearchTagFromFilters(filters: FiltersWithSearchTags, text: string): void {
  if (!filters.searchTags) return;

  filters.searchTags = filters.searchTags.filter((tag) => tag.text !== text);

  if (filters.searchTags.length === 0) {
    filters.searchTags = undefined;
  }
}

/**
 * Toggle a search tag's mode between include and exclude
 */
export function toggleSearchTagMode(filters: FiltersWithSearchTags, text: string): void {
  if (!filters.searchTags) return;

  const tag = filters.searchTags.find((t) => t.text === text);
  if (tag) {
    tag.mode = tag.mode === 'include' ? 'exclude' : 'include';
  }
}

/**
 * Clear all search tags
 */
export function clearSearchTags(filters: FiltersWithSearchTags): void {
  filters.searchTags = undefined;
}

// ============================================================================
// Location Utilities
// ============================================================================

/**
 * Set locations to a specific value or undefined
 */
export function setLocations(filters: FiltersWithLocation, locations: string[] | undefined): void {
  filters.location = locations;
}

/**
 * Add a location to filters with trim and duplicate checking
 */
export function addLocationToFilters(filters: FiltersWithLocation, location: string): void {
  const trimmedLocation = location.trim();
  if (!trimmedLocation) return;

  if (!filters.location) {
    filters.location = [trimmedLocation];
  } else if (!filters.location.includes(trimmedLocation)) {
    filters.location.push(trimmedLocation);
  }
}

/**
 * Remove a location from filters
 */
export function removeLocationFromFilters(filters: FiltersWithLocation, location: string): void {
  if (!filters.location) return;

  filters.location = filters.location.filter((loc) => loc !== location);

  if (filters.location.length === 0) {
    filters.location = undefined;
  }
}

/**
 * Clear all locations
 */
export function clearLocations(filters: FiltersWithLocation): void {
  filters.location = undefined;
}

// ============================================================================
// Software-Only Utilities
// ============================================================================

/**
 * Append as many of `newTags` as the keyword budget still has room for.
 *
 * The bulk software-only helpers below add up to six tags in ONE action, so the
 * per-add guard in `addSearchTagToFilters` never sees them. Twenty existing chips
 * plus this toggle is twenty-six keywords, which is a hard 400 on every
 * subsequent Recent Jobs request — with only a Retry that reissues the rejected
 * request (see `MAX_SEARCH_TAGS`).
 *
 * Appends only into the REMAINING room and never truncates what is already
 * there: dropping chips the reader can see on screen is the failure mode
 * `MAX_SEARCH_TAGS` was set at the ADD sites to avoid, and it would be a strange
 * thing for a toggle to do.
 */
function appendWithinTagBudget(currentTags: SearchTag[], newTags: SearchTag[]): SearchTag[] {
  return [...currentTags, ...newTags.slice(0, roomForSearchTags(currentTags))];
}

/**
 * Toggle software-only filter by adding/removing all software engineering tags
 */
export function toggleSoftwareOnlyInFilters(filters: FiltersWithSoftwareOnly): void {
  const seTagTexts = getSoftwareEngineeringTagTexts();
  const currentTags = filters.searchTags || [];

  // Check if all SE tags are present
  const allPresent = seTagTexts.every((text) =>
    currentTags.some((tag) => tag.text === text && tag.mode === 'include')
  );

  if (allPresent) {
    // Remove all SE tags (smart removal - preserves non-SE tags)
    filters.searchTags = currentTags.filter((tag) => !seTagTexts.includes(tag.text));
    if (filters.searchTags.length === 0) {
      filters.searchTags = undefined;
    }
  } else {
    // Add all SE tags
    const tagsToAdd = [...SOFTWARE_ENGINEERING_TAGS];
    const existingTexts = new Set(currentTags.map((tag) => tag.text));

    // Only add tags that don't already exist
    const newTags = tagsToAdd.filter((tag) => !existingTexts.has(tag.text));

    filters.searchTags = appendWithinTagBudget(currentTags, newTags);
  }

  // Keep softwareOnly in sync for backwards compatibility
  filters.softwareOnly = !allPresent;
}

/**
 * Set software-only filter by adding/removing all software engineering tags
 */
export function setSoftwareOnlyInFilters(filters: FiltersWithSoftwareOnly, enabled: boolean): void {
  const seTagTexts = getSoftwareEngineeringTagTexts();
  const currentTags = filters.searchTags || [];

  if (enabled) {
    // Add all SE tags
    const tagsToAdd = [...SOFTWARE_ENGINEERING_TAGS];
    const existingTexts = new Set(currentTags.map((tag) => tag.text));
    const newTags = tagsToAdd.filter((tag) => !existingTexts.has(tag.text));

    filters.searchTags = appendWithinTagBudget(currentTags, newTags);
  } else {
    // Remove all SE tags (smart removal - preserves non-SE tags)
    filters.searchTags = currentTags.filter((tag) => !seTagTexts.includes(tag.text));
    if (filters.searchTags.length === 0) {
      filters.searchTags = undefined;
    }
  }

  filters.softwareOnly = enabled;
}
