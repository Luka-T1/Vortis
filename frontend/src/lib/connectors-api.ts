import { apiFetch, getBase } from './api';
import type { ConnectorInfo, SyncStatus, ConnectRequest, ConnectResponse } from '../types/connectors';


export async function listConnectors(): Promise<ConnectorInfo[]> {
  const res = await apiFetch('/v1/connectors');
  if (!res.ok) throw new Error(`Failed to list connectors: ${res.status}`);
  const data = await res.json();
  return data.connectors || [];
}

export async function getConnector(id: string): Promise<ConnectorInfo> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to get connector ${id}: ${res.status}`);
  return res.json();
}

export async function connectSource(id: string, req: ConnectRequest): Promise<ConnectResponse> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to connect ${id}: ${res.status}`);
  }
  return res.json();
}

export function startServerOAuth(id: string, oauthStartPath?: string): Promise<void> {
  const path = oauthStartPath || `/v1/connectors/${encodeURIComponent(id)}/oauth/start`;
  window.open(`${getBase()}${path}`, '_blank', 'width=600,height=700');
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      try {
        const info = await getConnector(id);
        if (info.connected) {
          clearInterval(interval);
          clearTimeout(timer);
          resolve();
        }
      } catch {
      }
    }, 2000);
    const timer = setTimeout(() => {
      clearInterval(interval);
      reject(new Error('Authorization timed out — please try again.'));
    }, 180000);
  });
}

export class ConnectorApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ConnectorApiError';
  }
}

export async function disconnectSource(
  id: string,
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}/disconnect`, {
    method: 'POST',
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ConnectorApiError(
      err.detail || `Failed to disconnect ${id}: ${res.status}`,
      res.status,
    );
  }
}

export interface DisconnectUntilCompleteOptions {
  signal?: AbortSignal;
  retryDelayMs?: number;
  onPending?: (message: string) => void;
}

function waitForDisconnectRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Disconnect cancelled', 'AbortError'));
      return;
    }

    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', handleAbort);
      resolve();
    }, delayMs);
    const handleAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Disconnect cancelled', 'AbortError'));
    };
    signal?.addEventListener('abort', handleAbort, { once: true });
  });
}

export async function disconnectSourceUntilComplete(
  id: string,
  {
    signal,
    retryDelayMs = 1500,
    onPending,
  }: DisconnectUntilCompleteOptions = {},
): Promise<void> {
  while (true) {
    try {
      await disconnectSource(id, signal);
      return;
    } catch (err) {
      if (!(err instanceof ConnectorApiError) || err.status !== 409) {
        throw err;
      }
      onPending?.(err.message);
      await waitForDisconnectRetry(retryDelayMs, signal);
    }
  }
}

export async function getSyncStatus(id: string): Promise<SyncStatus> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}/sync`);
  if (!res.ok) throw new Error(`Failed to get sync status for ${id}: ${res.status}`);
  return res.json();
}

export async function triggerSync(id: string): Promise<{ connector_id: string; chunks_indexed: number; status: string }> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}/sync`, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Sync failed: ${res.status}`);
  }
  return res.json();
}
