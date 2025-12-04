import type { SearchTag, SoftwareRoleCategory } from '../../../types';
import {
  SOFTWARE_ENGINEERING_TAGS,
  getSoftwareEngineeringTagTexts,
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
 * Interface for filter state with department
 */
interface FiltersWithDepartment {
  department?: string[];
}

/**
 * Interface for filter state with role category
 */
interface FiltersWithRoleCategory {
  roleCategory?: SoftwareRoleCategory[];
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
 * Add a search tag to filters with trim and duplicate checking
 */
export function addSearchTagToFilters(filters: FiltersWithSearchTags, tag: SearchTag): void {
  const trimmedText = tag.text.trim();
  if (!trimmedText) return;

  const newTag = { text: trimmedText, mode: tag.mode };

  if (!filters.searchTags) {
    filters.searchTags = [newTag];
  } else {
    const exists = filters.searchTags.some((t) => t.text === newTag.text);
    if (!exists) {
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
// Department Utilities
// ============================================================================

/**
 * Set departments to a specific value or undefined
 */
export function setDepartments(
  filters: FiltersWithDepartment,
  departments: string[] | undefined
): void {
  filters.department = departments;
}

/**
 * Add a department to filters with duplicate checking
 */
export function addDepartmentToFilters(filters: FiltersWithDepartment, department: string): void {
  if (!filters.department) {
    filters.department = [department];
  } else if (!filters.department.includes(department)) {
    filters.department.push(department);
  }
}

/**
 * Remove a department from filters
 */
export function removeDepartmentFromFilters(
  filters: FiltersWithDepartment,
  department: string
): void {
  if (!filters.department) return;

  filters.department = filters.department.filter((dept) => dept !== department);

  if (filters.department.length === 0) {
    filters.department = undefined;
  }
}

/**
 * Clear all departments
 */
export function clearDepartments(filters: FiltersWithDepartment): void {
  filters.department = undefined;
}

// ============================================================================
// Role Category Utilities
// ============================================================================

/**
 * Set role categories to a specific value or undefined
 */
export function setRoleCategories(
  filters: FiltersWithRoleCategory,
  categories: SoftwareRoleCategory[] | undefined
): void {
  filters.roleCategory = categories;
}

/**
 * Add a role category to filters with duplicate checking
 */
export function addRoleCategoryToFilters(
  filters: FiltersWithRoleCategory,
  category: SoftwareRoleCategory
): void {
  if (!filters.roleCategory) {
    filters.roleCategory = [category];
  } else if (!filters.roleCategory.includes(category)) {
    filters.roleCategory.push(category);
  }
}

/**
 * Remove a role category from filters
 */
export function removeRoleCategoryFromFilters(
  filters: FiltersWithRoleCategory,
  category: SoftwareRoleCategory
): void {
  if (!filters.roleCategory) return;

  filters.roleCategory = filters.roleCategory.filter((cat) => cat !== category);

  if (filters.roleCategory.length === 0) {
    filters.roleCategory = undefined;
  }
}

/**
 * Clear all role categories
 */
export function clearRoleCategories(filters: FiltersWithRoleCategory): void {
  filters.roleCategory = undefined;
}

// ============================================================================
// Software-Only Utilities
// ============================================================================

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

    filters.searchTags = [...currentTags, ...newTags];
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

    filters.searchTags = [...currentTags, ...newTags];
  } else {
    // Remove all SE tags (smart removal - preserves non-SE tags)
    filters.searchTags = currentTags.filter((tag) => !seTagTexts.includes(tag.text));
    if (filters.searchTags.length === 0) {
      filters.searchTags = undefined;
    }
  }

  filters.softwareOnly = enabled;
}
