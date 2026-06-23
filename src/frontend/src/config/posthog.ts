export interface PostHogConfig {
  key: string;
  apiHost: string;
  uiHost: string;
  isEnabled: boolean;
}

export const POSTHOG_CONFIG: PostHogConfig = {
  key: import.meta.env.VITE_POSTHOG_KEY ?? '',
  apiHost: import.meta.env.VITE_POSTHOG_HOST ?? '/ingest',
  uiHost: 'https://us.posthog.com',
  get isEnabled() {
    return Boolean(this.key);
  },
};
