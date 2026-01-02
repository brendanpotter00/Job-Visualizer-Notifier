import type { SearchTag } from '../../../types';
import {
  SOFTWARE_ENGINEERING_TAGS,
  getSoftwareEngineeringTagTexts,
  getRoleTagGroupById,
  roleTagGroupToSearchTags,
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

// ============================================================================
// Role Tag Group Utilities
// ============================================================================

/**
 * Interface for filter state with active role groups
 */
interface FiltersWithRoleGroups extends FiltersWithSearchTags {
  activeRoleGroups?: string[];
}

/**
 * Toggle a role tag group on/off
 * When toggled on, adds the group's tags to searchTags
 * When toggled off, removes the group's tags from searchTags
 */
export function toggleRoleGroupInFilters(
  filters: FiltersWithRoleGroups,
  groupId: string
): void {
  const group = getRoleTagGroupById(groupId);
  if (!group) return;

  const currentGroups = filters.activeRoleGroups || [];
  const isActive = currentGroups.includes(groupId);

  if (isActive) {
    // Remove group from active groups
    filters.activeRoleGroups = currentGroups.filter((id) => id !== groupId);
    if (filters.activeRoleGroups.length === 0) {
      filters.activeRoleGroups = undefined;
    }

    // Remove group's tags from searchTags
    const groupTagTexts = new Set(group.tags);
    if (filters.searchTags) {
      filters.searchTags = filters.searchTags.filter(
        (tag) => !groupTagTexts.has(tag.text)
      );
      if (filters.searchTags.length === 0) {
        filters.searchTags = undefined;
      }
    }
  } else {
    // Add group to active groups
    filters.activeRoleGroups = [...currentGroups, groupId];

    // Add group's tags to searchTags
    const tagsToAdd = roleTagGroupToSearchTags(group);
    const currentTags = filters.searchTags || [];
    const existingTexts = new Set(currentTags.map((tag) => tag.text));

    // Only add tags that don't already exist
    const newTags = tagsToAdd.filter((tag) => !existingTexts.has(tag.text));
    filters.searchTags = [...currentTags, ...newTags];
  }
}

/**
 * Set a role tag group to enabled or disabled
 */
export function setRoleGroupInFilters(
  filters: FiltersWithRoleGroups,
  groupId: string,
  enabled: boolean
): void {
  const group = getRoleTagGroupById(groupId);
  if (!group) return;

  const currentGroups = filters.activeRoleGroups || [];
  const isActive = currentGroups.includes(groupId);

  // Only take action if state needs to change
  if (enabled && !isActive) {
    // Add group to active groups
    filters.activeRoleGroups = [...currentGroups, groupId];

    // Add group's tags to searchTags
    const tagsToAdd = roleTagGroupToSearchTags(group);
    const currentTags = filters.searchTags || [];
    const existingTexts = new Set(currentTags.map((tag) => tag.text));

    const newTags = tagsToAdd.filter((tag) => !existingTexts.has(tag.text));
    filters.searchTags = [...currentTags, ...newTags];
  } else if (!enabled && isActive) {
    // Remove group from active groups
    filters.activeRoleGroups = currentGroups.filter((id) => id !== groupId);
    if (filters.activeRoleGroups.length === 0) {
      filters.activeRoleGroups = undefined;
    }

    // Remove group's tags from searchTags
    const groupTagTexts = new Set(group.tags);
    if (filters.searchTags) {
      filters.searchTags = filters.searchTags.filter(
        (tag) => !groupTagTexts.has(tag.text)
      );
      if (filters.searchTags.length === 0) {
        filters.searchTags = undefined;
      }
    }
  }
}

/**
 * Clear all active role groups and their associated tags
 */
export function clearAllRoleGroups(filters: FiltersWithRoleGroups): void {
  const currentGroups = filters.activeRoleGroups || [];

  // Collect all tag texts from all active groups
  const allGroupTagTexts = new Set<string>();
  for (const groupId of currentGroups) {
    const group = getRoleTagGroupById(groupId);
    if (group) {
      for (const tag of group.tags) {
        allGroupTagTexts.add(tag);
      }
    }
  }

  // Clear active groups
  filters.activeRoleGroups = undefined;

  // Remove all group tags from searchTags
  if (filters.searchTags) {
    filters.searchTags = filters.searchTags.filter(
      (tag) => !allGroupTagTexts.has(tag.text)
    );
    if (filters.searchTags.length === 0) {
      filters.searchTags = undefined;
    }
  }
}

/**
 * Check if a role group is currently active
 */
export function isRoleGroupActive(
  activeRoleGroups: string[] | undefined,
  groupId: string
): boolean {
  return activeRoleGroups?.includes(groupId) ?? false;
}
