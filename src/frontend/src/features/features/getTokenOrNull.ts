type TokenGetter = () => Promise<string>;

let currentGetter: TokenGetter | null = null;

export function registerTokenGetter(getter: TokenGetter | null): void {
  currentGetter = getter;
}

export async function getTokenOrNull(): Promise<string | null> {
  if (!currentGetter) return null;
  try {
    const token = await currentGetter();
    return token ?? null;
  } catch (e) {
    // Surface the rejection reason instead of swallowing it silently — an
    // empty catch here previously conflated "user is signed out" with "the
    // Auth0 SDK broke" and left both states looking identical.
    console.warn('[getTokenOrNull] token getter rejected:', e);
    return null;
  }
}
