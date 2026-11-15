/**
 * A returnTo is honoured only as a same-origin, absolute PATH ("/pricing?x=1").
 * Anything else — a full URL, a protocol-relative "//evil.com", a backslash
 * trick — falls back to the default, so the post-login hop can never leave the
 * site.
 */
export function safeReturnTo(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return null;
  return value;
}
