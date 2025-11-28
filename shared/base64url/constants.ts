/**
 * Validation constants for base64url encoding/decoding
 */

/**
 * Valid base64url characters: A-Z, a-z, 0-9, -, _
 * No padding (=) characters should be present in base64url format
 */
export const VALID_BASE64URL_CHARS_REGEX = /^[A-Za-z0-9_-]*$/;

/**
 * Domain validation regex per DNS specification
 * - Each label (segment) can be 1-63 characters
 * - Labels can contain alphanumeric and hyphens (but not start/end with hyphen)
 * - Total domain length max 255 characters
 */
export const DOMAIN_REGEX =
  /^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/;

/**
 * Maximum domain length per DNS specification
 */
export const MAX_DOMAIN_LENGTH = 255;

/**
 * Maximum base64url encoded length
 * Accounts for 4/3 expansion ratio: 255 * 4/3 ≈ 340
 */
export const MAX_ENCODED_LENGTH = 340;

/**
 * Error messages for validation failures
 */
export const ERROR_MESSAGES = {
  INVALID_DOMAIN: 'Domain must be a valid hostname (alphanumeric, hyphens, dots only)',
  DOMAIN_TOO_LONG: `Domain exceeds maximum length of ${MAX_DOMAIN_LENGTH} characters`,
  INVALID_ENCODED_FORMAT:
    'Encoded domain contains invalid base64url characters (only A-Za-z0-9_- allowed)',
  DECODE_FAILED: 'Failed to decode base64url domain',
  ENCODE_FAILED: 'Failed to encode domain to base64url',
  PADDING_RESTORATION_FAILED: 'Could not restore base64 padding',
  ROUND_TRIP_FAILED: 'Round-trip validation failed: encoded domain does not decode back to original',
  EMPTY_INPUT: 'Input cannot be empty',
} as const;
