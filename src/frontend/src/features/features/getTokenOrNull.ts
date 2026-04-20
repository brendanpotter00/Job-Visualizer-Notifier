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
  } catch {
    return null;
  }
}
