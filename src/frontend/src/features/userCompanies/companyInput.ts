/**
 * Decide whether what someone typed is a URL or a company name.
 *
 * URL-FIRST is the rule, and this function is where it is enforced. A URL is
 * exact: the user has told us precisely which board they mean, and the backend
 * resolves it for free and instantly with no search call and no ambiguity. A
 * name is a guess we then have to pay to research and ask them to confirm. So
 * anything that could reasonably be a URL is treated as one, and the name path
 * is the fallback — never the other way round.
 */

/** Schemes we will hand to the add endpoint untouched. */
const HTTP_SCHEME = /^https?:\/\//i;

/** Any scheme at all, so `ftp://` / `javascript:` are recognised and refused. */
const ANY_SCHEME = /^[a-z][a-z0-9+.-]*:/i;

/**
 * A bare host with a plausible TLD — `cisco.com`, `careers.cisco.com/global/en`.
 *
 * The TLD must be at least two letters and NOT all digits, so an IPv4 literal
 * (`10.0.0.1`) never looks like a hostname here. It would be refused by the
 * server's SSRF guard anyway; this just avoids sending it.
 */
const BARE_HOST = /^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(?::\d+)?(?:[/?#]|$)/i;

/**
 * A bare IP literal — `10.0.0.1`, `[::1]`, `169.254.169.254`.
 *
 * These are NOT hostnames (`BARE_HOST` requires an alphabetic TLD), and left to
 * fall through they would be classified as a company NAME and spend a paid
 * search call on an address. Worse, routing them to the name path skips the
 * server's SSRF guard entirely — and an IP literal is precisely the input that
 * guard exists to refuse. So they are classified as URLs, and the guard gets to
 * say no with its own reason code.
 */
const IP_LITERAL = /^(?:\d{1,3}(?:\.\d{1,3}){3}|\[[0-9a-f:]+\])(?::\d+)?(?:[/?#]|$)/i;

export type CompanyInputKind =
  | { kind: 'url'; url: string }
  | { kind: 'name'; name: string };

/**
 * Classify a submitted string.
 *
 * `cisco.com` is classified as a URL and given the `https://` it is missing.
 * That alone fixes a real papercut: the shipped guard rejects a bare domain with
 * "only https is accepted", so a user who typed the most obvious possible thing
 * got an error that reads like their company is unsupported.
 *
 * Anything carrying a non-HTTP scheme is returned as a URL so the server's guard
 * is the one that refuses it, with its own reason code. Classifying it as a
 * NAME would be worse: we would spend a paid search call on `javascript:alert(1)`.
 */
export function classifyCompanyInput(raw: string): CompanyInputKind {
  const trimmed = raw.trim();

  if (HTTP_SCHEME.test(trimmed)) {
    return { kind: 'url', url: trimmed };
  }
  if (ANY_SCHEME.test(trimmed)) {
    // Not ours to accept, but also not a name. Let the SSRF guard say no.
    return { kind: 'url', url: trimmed };
  }
  // A name can contain spaces; a host cannot. Checking this before the host
  // pattern keeps "Acme Corp. Ltd" a name rather than a hostname with a dot.
  if (!/\s/.test(trimmed) && (BARE_HOST.test(trimmed) || IP_LITERAL.test(trimmed))) {
    return { kind: 'url', url: `https://${trimmed}` };
  }
  return { kind: 'name', name: trimmed };
}
