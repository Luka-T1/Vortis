
export const TIMEZONE_HEADER = 'X-Vortis-Timezone';

export function deviceTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function isValidTimeZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

export function resolveTimeZone(setting: string | undefined): string {
  return setting && isValidTimeZone(setting) ? setting : deviceTimeZone();
}

export function timeZoneHeaders(): Record<string, string> {
  let setting = '';
  try {
    const raw = localStorage.getItem('vortis-settings');
    if (raw) setting = String(JSON.parse(raw).timeZone || '');
  } catch {
    setting = '';
  }
  return { [TIMEZONE_HEADER]: resolveTimeZone(setting) };
}

export function listTimeZones(): string[] {
  let zones: string[] = [];
  try {
    zones = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] })
      .supportedValuesOf?.('timeZone') ?? [];
  } catch {
    zones = [];
  }
  const device = deviceTimeZone();
  return zones.includes(device) ? zones : [device, ...zones];
}

export function utcOffsetLabel(zone: string, at: Date = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'longOffset' })
      .formatToParts(at)
      .find((p) => p.type === 'timeZoneName')?.value;
    if (!part || part === 'GMT') return 'UTC+00:00';
    return part.replace('GMT', 'UTC');
  } catch {
    return '';
  }
}
