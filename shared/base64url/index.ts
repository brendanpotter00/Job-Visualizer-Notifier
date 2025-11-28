/**
 * Shared base64url encoding/decoding utility for Workday API integration
 *
 * This module provides cross-environment (browser + Node.js) base64url encoding/decoding
 * with automatic round-trip validation to prevent encoding corruption.
 *
 * Why this exists:
 * - Browser's btoa() uses Latin-1 encoding, Node.js Buffer uses UTF-8
 * - This mismatch caused corrupted URLs in production
 * - Round-trip validation catches encoding issues immediately
 *
 * @module @job-visualizer/base64url
 */

import {
  VALID_BASE64URL_CHARS_REGEX,
  DOMAIN_REGEX,
  MAX_DOMAIN_LENGTH,
  ERROR_MESSAGES,
} from './constants';

/**
 * Detect if running in Node.js environment
 * Using globalThis to safely access process without TypeScript errors
 */
const isNodeEnvironment =
  typeof (globalThis as any).process !== 'undefined' &&
  (globalThis as any).process.versions != null &&
  (globalThis as any).process.versions.node != null;

/**
 * Validate that a string is a valid domain name
 *
 * @param domain - The domain to validate
 * @returns True if valid domain format
 *
 * @example
 * isValidDomain('nvidia.wd5.myworkdayjobs.com') // true
 * isValidDomain('invalid..domain') // false
 * isValidDomain('') // false
 */
export function isValidDomain(domain: string): boolean {
  if (!domain || domain.length === 0) {
    return false;
  }
  if (domain.length > MAX_DOMAIN_LENGTH) {
    return false;
  }
  return DOMAIN_REGEX.test(domain);
}

/**
 * Encode a domain to base64url format with round-trip validation
 *
 * This function:
 * 1. Validates the input domain
 * 2. Encodes to base64url (works in both browser and Node.js)
 * 3. Validates the encoded format
 * 4. Performs round-trip validation (decode and compare)
 * 5. Returns the encoded domain if validation passes
 *
 * Round-trip validation ensures that encoding corruption is caught immediately
 * rather than failing later when constructing the API URL.
 *
 * @param domain - The domain name to encode (e.g., 'nvidia.wd5.myworkdayjobs.com')
 * @returns Base64url-encoded domain safe for URL paths
 * @throws Error if domain is invalid, encoding fails, or round-trip validation fails
 *
 * @example
 * const encoded = encodeBase64url('nvidia.wd5.myworkdayjobs.com');
 * // Returns: 'bnZpZGlhLndkNS5teXdvcmtkYXlqb2JzLmNvbQ'
 * // No +, /, or = characters (base64url format)
 */
export function encodeBase64url(domain: string): string {
  // 1. Validate input
  if (!domain || domain.length === 0) {
    throw new Error(`${ERROR_MESSAGES.EMPTY_INPUT}: domain`);
  }

  if (!isValidDomain(domain)) {
    throw new Error(
      `${ERROR_MESSAGES.INVALID_DOMAIN}: "${domain}" (length: ${domain.length}, valid: ${DOMAIN_REGEX.test(domain)})`
    );
  }

  // 2. Encode to base64 (environment-specific)
  let base64: string;
  try {
    if (isNodeEnvironment) {
      // Node.js: Use Buffer with UTF-8 encoding
      base64 = (globalThis as any).Buffer.from(domain, 'utf-8').toString('base64');
    } else {
      // Browser: Use btoa with proper UTF-8 handling via TextEncoder
      // btoa expects Latin-1, so we convert UTF-8 bytes to Latin-1 string
      const utf8Bytes = new TextEncoder().encode(domain);
      const latin1String = String.fromCharCode(...utf8Bytes);
      base64 = btoa(latin1String);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`${ERROR_MESSAGES.ENCODE_FAILED}: ${message}`);
  }

  // 3. Convert base64 to base64url format
  // Replace + with -, / with _, and remove padding =
  const base64url = base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');

  // 4. Validate encoded format
  if (!VALID_BASE64URL_CHARS_REGEX.test(base64url)) {
    throw new Error(
      `${ERROR_MESSAGES.INVALID_ENCODED_FORMAT}: "${base64url}" contains invalid characters`
    );
  }

  // 5. Round-trip validation (decode and compare to original)
  // This catches encoding issues immediately
  let decoded: string;
  try {
    decoded = decodeBase64url(base64url);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`${ERROR_MESSAGES.ROUND_TRIP_FAILED}: decode failed with: ${message}`);
  }

  if (decoded !== domain) {
    // Round-trip failed - encoding is corrupted
    // Use globalThis to safely access Buffer
    const BufferGlobal = (globalThis as any).Buffer;
    const hexOriginal = BufferGlobal
      ? BufferGlobal.from(domain, 'utf-8')
          .toString('hex')
          .match(/.{1,2}/g)
          ?.join(' ')
      : 'N/A';
    const hexDecoded = BufferGlobal
      ? BufferGlobal.from(decoded, 'utf-8')
          .toString('hex')
          .match(/.{1,2}/g)
          ?.join(' ')
      : 'N/A';

    throw new Error(
      `${ERROR_MESSAGES.ROUND_TRIP_FAILED}:\n` +
        `  Original: "${domain}"\n` +
        `  Encoded:  "${base64url}"\n` +
        `  Decoded:  "${decoded}"\n` +
        `  Original hex: ${hexOriginal}\n` +
        `  Decoded hex:  ${hexDecoded}`
    );
  }

  return base64url;
}

/**
 * Decode a domain from base64url format
 *
 * This function:
 * 1. Validates the input base64url format
 * 2. Converts base64url to standard base64
 * 3. Restores base64 padding if needed
 * 4. Decodes from base64 to UTF-8 string (works in both browser and Node.js)
 * 5. Validates the decoded domain
 *
 * @param encoded - The base64url-encoded domain
 * @returns The decoded domain name
 * @throws Error with detailed diagnostic info if decoding fails
 *
 * @example
 * const domain = decodeBase64url('bnZpZGlhLndkNS5teXdvcmtkYXlqb2JzLmNvbQ');
 * // Returns: 'nvidia.wd5.myworkdayjobs.com'
 */
export function decodeBase64url(encoded: string): string {
  // 1. Validate input
  if (!encoded || encoded.length === 0) {
    throw new Error(`${ERROR_MESSAGES.EMPTY_INPUT}: encoded`);
  }

  if (!VALID_BASE64URL_CHARS_REGEX.test(encoded)) {
    throw new Error(
      `${ERROR_MESSAGES.INVALID_ENCODED_FORMAT}: "${encoded}" contains invalid base64url characters`
    );
  }

  // 2. Convert base64url to base64
  // Replace - with +, _ with /
  let base64 = encoded.replace(/-/g, '+').replace(/_/g, '/');

  // 3. Restore base64 padding
  // Base64 strings must be a multiple of 4 characters
  // Add '=' padding to reach the next multiple of 4
  const paddingLength = (4 - (base64.length % 4)) % 4;
  if (paddingLength > 0) {
    base64 += '='.repeat(paddingLength);
  }

  // 4. Decode from base64 (environment-specific)
  let domain: string;
  try {
    if (isNodeEnvironment) {
      // Node.js: Use Buffer with UTF-8 decoding
      domain = (globalThis as any).Buffer.from(base64, 'base64').toString('utf-8');
    } else {
      // Browser: Use atob and TextDecoder for proper UTF-8 handling
      const latin1String = atob(base64);
      const utf8Bytes = Uint8Array.from(latin1String, (char) => char.charCodeAt(0));
      domain = new TextDecoder().decode(utf8Bytes);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // Use globalThis to safely access Buffer
    const BufferGlobal = (globalThis as any).Buffer;
    const hexEncoded = BufferGlobal
      ? BufferGlobal.from(encoded, 'utf-8')
          .toString('hex')
          .match(/.{1,2}/g)
          ?.join(' ')
      : 'N/A';

    throw new Error(
      `${ERROR_MESSAGES.DECODE_FAILED}: ${message}\n` +
        `  Encoded: "${encoded}"\n` +
        `  Base64:  "${base64}"\n` +
        `  Hex:     ${hexEncoded}`
    );
  }

  // 5. Validate decoded domain
  if (!isValidDomain(domain)) {
    throw new Error(
      `${ERROR_MESSAGES.DECODE_FAILED}: decoded value is not a valid domain: "${domain}"`
    );
  }

  return domain;
}
