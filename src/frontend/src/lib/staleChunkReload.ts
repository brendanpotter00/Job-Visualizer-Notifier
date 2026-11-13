const RELOAD_STAMP_KEY = 'jvn.staleChunkReloadAt';
const MIN_RELOAD_INTERVAL_MS = 10_000;

export function installStaleChunkReload(target: Window = window): () => void {
  const handlePreloadError = () => {
    try {
      const now = Date.now();
      const lastReloadAt = Number(target.sessionStorage.getItem(RELOAD_STAMP_KEY));
      if (Number.isFinite(lastReloadAt) && now - lastReloadAt < MIN_RELOAD_INTERVAL_MS) return;
      target.sessionStorage.setItem(RELOAD_STAMP_KEY, String(now));
    } catch {
      return;
    }
    target.location.reload();
  };

  target.addEventListener('vite:preloadError', handlePreloadError);
  return () => target.removeEventListener('vite:preloadError', handlePreloadError);
}
