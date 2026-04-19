function buildKey(storageKey: string): string {
  return `newFeatureCallout:${storageKey}:dismissed`;
}

export function isDismissed(storageKey: string): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    const raw = window.localStorage.getItem(buildKey(storageKey));
    return typeof raw === 'string' && raw.length > 0;
  } catch {
    return false;
  }
}

export function markDismissed(storageKey: string): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    window.localStorage.setItem(buildKey(storageKey), new Date().toISOString());
  } catch {
    // Storage may be disabled or full; the caller already toggled state so
    // the callout hides for this session even if persistence fails.
  }
}
