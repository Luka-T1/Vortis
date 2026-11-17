import { useCallback, useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { Smartphone, Trash2, RefreshCw } from 'lucide-react';
import {
  fetchPairedDevices,
  revokeDevice,
  startPairing,
  type PairedDevice,
  type PairingTicket,
} from '../../lib/hud-api';

export function PairDevicePanel() {
  const [ticket, setTicket] = useState<PairingTicket | null>(null);
  const [qr, setQr] = useState('');
  const [error, setError] = useState('');
  const [devices, setDevices] = useState<PairedDevice[]>([]);
  const [host, setHost] = useState('');

  const loadDevices = useCallback(() => {
    fetchPairedDevices().then(setDevices).catch(() => {});
  }, []);

  const newCode = useCallback(async () => {
    setError('');
    try {
      const t = await startPairing(host.trim() || undefined);
      setTicket(t);
      setQr(await QRCode.toString(t.pair_url, { type: 'svg', margin: 1, width: 220 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [host]);

  useEffect(() => {
    loadDevices();
    const id = setInterval(loadDevices, 5000);
    return () => clearInterval(id);
  }, [loadDevices]);

  return (
    <div className="flex flex-col gap-3 text-sm" style={{ color: 'var(--color-text)' }}>
      <div className="flex items-center gap-2 font-semibold">
        <Smartphone size={16} /> Telefon / TV
      </div>
      {qr ? (
        <div className="flex flex-col items-center gap-2">
          <div className="rounded-lg p-2 bg-white" dangerouslySetInnerHTML={{ __html: qr }} />
          <div className="text-xs text-center" style={{ color: 'var(--color-text-secondary)' }}>
            Skeniraj kamerom telefona. Kod <b>{ticket?.code}</b> važi 5 minuta i radi samo jednom.
          </div>
          {ticket && (
            <div className="text-xs text-center" style={{ color: 'var(--color-text-tertiary)' }}>
              TV: u pregledaču otvori <code>{ticket.pair_url.split('#')[0]}</code>, ukucaj kod i označi „Ovo je TV”.
            </div>
          )}
          {ticket && !ticket.lan_reachable && (
            <div className="text-xs" style={{ color: 'var(--color-accent-amber)' }}>
              Server sluša samo na ovom računaru. Pokreni ga sa
              {' '}<code>vortis serve --host 0.0.0.0</code> i API ključem da bi ga telefon video.
            </div>
          )}
        </div>
      ) : (
        <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          Upari telefon ili TV: dobija isti HUD, glas i dugme za potvrdu.
        </div>
      )}
      <div className="flex gap-2">
        <input
          value={host}
          onChange={(e) => setHost(e.target.value)}
          placeholder="IP adresa (opciono)"
          className="flex-1 min-w-0 px-2 py-1.5 rounded text-xs"
          style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }}
        />
        <button
          onClick={newCode}
          className="flex items-center gap-1 px-3 py-1.5 rounded text-xs cursor-pointer"
          style={{ background: 'var(--color-accent)', color: 'var(--color-text-inverse)' }}
        >
          <RefreshCw size={12} /> {qr ? 'Novi kod' : 'QR kod'}
        </button>
      </div>
      {error && <div className="text-xs" style={{ color: 'var(--color-error)' }}>{error}</div>}
      {devices.length > 0 && (
        <ul className="flex flex-col gap-1">
          {devices.map((d) => (
            <li key={d.id} className="flex items-center gap-2 text-xs">
              <span className="flex-1 truncate">{d.name}</span>
              <span style={{ color: 'var(--color-text-tertiary)' }}>
                {d.last_seen ? new Date(d.last_seen * 1000).toLocaleTimeString() : 'nije viđen'}
              </span>
              <button
                aria-label={`Ukloni ${d.name}`}
                className="cursor-pointer p-1"
                onClick={() => revokeDevice(d.id).then(loadDevices)}
              >
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
