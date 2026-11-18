import { useEffect, useRef } from 'react';
import { apiFetch, getBase } from './api';
import { buildWsProtocols, buildWsUrl, type AgentEvent } from './useAgentEvents';

export interface PendingConfirmation {
  id: string;
  tool: string;
  title: string;
  detail: string;
  arguments: Record<string, unknown>;
  agent: string;
  created_at: number;
  expires_at: number;
  token: string;
}

export async function fetchConfirmations(): Promise<PendingConfirmation[]> {
  const res = await apiFetch('/v1/confirmations');
  if (!res.ok) return [];
  const data = await res.json();
  return (data.confirmations ?? []) as PendingConfirmation[];
}

export async function decideConfirmation(
  item: Pick<PendingConfirmation, 'id' | 'token'>,
  approve: boolean,
): Promise<boolean> {
  const res = await apiFetch(`/v1/confirmations/${encodeURIComponent(item.id)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: item.token, approve }),
  });
  return res.ok;
}

export async function reportGesture(body: {
  gesture: string;
  score: number;
  hand?: string;
  action?: string;
  device?: string;
}): Promise<void> {
  try {
    await apiFetch('/v1/gestures', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
  }
}

export interface PairingTicket {
  code: string;
  expires_at: number;
  origin: string;
  pair_url: string;
  lan_reachable: boolean;
}

export async function startPairing(host?: string): Promise<PairingTicket> {
  const res = await apiFetch('/v1/pairing/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(host ? { host } : {}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Pairing failed (${res.status})`);
  }
  return res.json();
}

export interface PairedDevice {
  id: string;
  name: string;
  created_at: number;
  last_seen: number | null;
}

export async function fetchPairedDevices(): Promise<PairedDevice[]> {
  const res = await apiFetch('/v1/pairing/devices');
  if (!res.ok) return [];
  return (await res.json()).devices ?? [];
}

export async function revokeDevice(id: string): Promise<void> {
  await apiFetch(`/v1/pairing/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function claimPairing(code: string, name: string): Promise<string> {
  const res = await fetch(`${getBase()}/pair/claim`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, name }),
  });
  if (!res.ok) throw new Error('Kod je pogrešan ili je istekao. Skeniraj novi QR kod.');
  return (await res.json()).token as string;
}

export function saveDeviceToken(token: string): void {
  let settings: Record<string, unknown> = {};
  try {
    settings = JSON.parse(localStorage.getItem('vortis-settings') || '{}');
  } catch {}
  settings.apiKey = token;
  localStorage.setItem('vortis-settings', JSON.stringify(settings));
}

export function useHudEvents(onEvent: (event: AgentEvent) => void, enabled = true): void {
  const ref = useRef(onEvent);
  ref.current = onEvent;
  useEffect(() => {
    if (!enabled) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(buildWsUrl(), buildWsProtocols());
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        retry = 0;
      };
      ws.onmessage = (msg) => {
        try {
          ref.current(JSON.parse(msg.data) as AgentEvent);
        } catch {}
      };
      ws.onclose = () => {
        if (!closed) schedule();
      };
      ws.onerror = () => ws?.close();
    };
    const schedule = () => {
      const delay = Math.min(15000, 1000 * 2 ** Math.min(retry, 4));
      retry += 1;
      timer = setTimeout(connect, delay);
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [enabled]);
}

export const HUD_CONFIRM_EVENT = 'vortis-hud-confirm';
export const GESTURE_CONFIRM_KEY = 'vortis-hud-gesture-confirm';

export function gestureConfirmAllowed(): boolean {
  try {
    return localStorage.getItem(GESTURE_CONFIRM_KEY) === '1';
  } catch {
    return false;
  }
}

export async function pushToDisplay(body: {
  title?: string;
  markdown?: string;
  target?: string;
}): Promise<void> {
  const res = await apiFetch('/v1/display', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source: 'hud', ...body }),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(`Slanje na ekran nije uspelo: ${detail}`);
  }
}
