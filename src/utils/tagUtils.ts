/**
 * Sanitizes tag values by filtering out nulls, flattening nested arrays,
 * and ensuring only valid non-empty strings remain
 *
 * @param tags - Raw tag data from API (can be array, null, or undefined)
 * @returns Array of valid non-empty string tags
 *
 * @example
 * sanitizeTags(['React', null, ['TypeScript', 'Node'], '', 'Python'])
 * // Returns: ['React', 'TypeScript', 'Node', 'Python']
 */
export function sanitizeTags(tags: unknown): string[] {
  if (!Array.isArray(tags)) return [];

  return tags
    .flatMap((tag) => {
      // Handle nested arrays - flatten them
      if (Array.isArray(tag)) {
        return tag.filter((t): t is string => typeof t === 'string' && t.length > 0);
      }
      // Only keep valid non-empty strings
      if (typeof tag === 'string' && tag.length > 0) {
        return [tag];
      }
      // Filter out null, undefined, empty strings, numbers, objects, etc.
      return [];
    });
}
