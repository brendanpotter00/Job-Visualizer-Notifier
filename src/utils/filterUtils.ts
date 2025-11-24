import type { SearchTag } from '../types';

/**
 * Parses search tag input with prefix detection
 * Supports:
 * - Prefixed with '-' for exclude mode
 * - Prefixed with '+' for include mode
 * - No prefix defaults to include mode
 *
 * @param input - The raw input string from the user
 * @returns Parsed search tag object, or null if input is invalid
 */
export function parseSearchTagInput(input: string): SearchTag | null {
  const trimmed = input.trim();

  if (!trimmed) {
    return null;
  }

  let text = trimmed;
  let mode: 'include' | 'exclude' = 'include';

  // Check for prefix override
  if (text.startsWith('-')) {
    text = text.slice(1).trim();
    mode = 'exclude';
  } else if (text.startsWith('+')) {
    text = text.slice(1).trim();
    mode = 'include';
  }

  // Ensure we have text after removing prefix
  if (!text) {
    return null;
  }

  return { text, mode };
}

/**
 * Calculates the difference between two arrays
 * Returns which elements were added and which were removed
 *
 * @param oldArray - The original array
 * @param newArray - The new array
 * @returns Object containing arrays of added and removed elements
 */
export function getArrayDiff<T>(
  oldArray: T[],
  newArray: T[]
): { added: T[]; removed: T[] } {
  const oldSet = new Set(oldArray);
  const newSet = new Set(newArray);

  const added = newArray.filter((item) => !oldSet.has(item));
  const removed = oldArray.filter((item) => !newSet.has(item));

  return { added, removed };
}

/**
 * Validates and sanitizes search tag text
 * Removes extra whitespace and ensures the text is valid
 *
 * @param text - The raw text to sanitize
 * @returns Sanitized text, or null if invalid
 */
export function sanitizeSearchTag(text: string): string | null {
  const trimmed = text.trim();

  if (!trimmed) {
    return null;
  }

  // Replace multiple spaces with single space
  const sanitized = trimmed.replace(/\s+/g, ' ');

  // Ensure minimum length (at least 1 character)
  if (sanitized.length === 0) {
    return null;
  }

  return sanitized;
}
