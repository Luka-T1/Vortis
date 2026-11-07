
export interface AnalyticsIdentity {
  enabled: boolean;
  anon_id: string;
  host: string;
  key: string;
  choice_recorded?: boolean;
}

const DISABLED: AnalyticsIdentity = {
  enabled: false,
  anon_id: '',
  host: '',
  key: '',
  choice_recorded: true,
};

export async function fetchAnalyticsIdentity(): Promise<AnalyticsIdentity> {
  return { ...DISABLED };
}

export async function saveAnalyticsPreference(_enabled: boolean): Promise<void> {}

export async function initAnalytics(_force = false): Promise<void> {}

export function track(_event: string, _properties: Record<string, unknown> = {}): void {}

export function flush(): void {}

export function isAnalyticsEnabled(): boolean {
  return false;
}

export function getAnonId(): string {
  return '';
}

export async function hashId(s: string): Promise<string> {
  try {
    const data = new TextEncoder().encode(s);
    const digest = await crypto.subtle.digest('SHA-256', data);
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('')
      .slice(0, 16);
  } catch {
    return '';
  }
}

export function detectPlatform(): string {
  const ua = typeof navigator !== 'undefined' ? navigator.userAgent : '';
  if (/Mac/i.test(ua)) return 'darwin';
  if (/Win/i.test(ua)) return 'windows';
  if (/Linux/i.test(ua)) return 'linux';
  return 'unknown';
}
