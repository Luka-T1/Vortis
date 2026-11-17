import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { claimPairing, saveDeviceToken } from '../lib/hud-api';

function guessDeviceName(): string {
  const ua = navigator.userAgent;
  if (/android/i.test(ua)) return /mobile/i.test(ua) ? 'Android telefon' : 'Android TV/tablet';
  if (/iphone/i.test(ua)) return 'iPhone';
  if (/ipad/i.test(ua)) return 'iPad';
  if (/smart-tv|smarttv|tizen|webos|hbbtv/i.test(ua)) return 'TV';
  return 'Uređaj';
}

export function PairPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<'ask' | 'working' | 'ok' | 'error'>('working');
  const [message, setMessage] = useState('Uparivanje…');
  const [typed, setTyped] = useState('');
  const [isTv, setIsTv] = useState(() => guessDeviceName() === 'TV' || guessDeviceName().includes('TV'));

  const claim = useCallback(
    (code: string, tv: boolean) => {
      setStatus('working');
      setMessage('Uparivanje…');
      claimPairing(code, tv ? 'TV' : guessDeviceName())
        .then((token) => {
          saveDeviceToken(token);
          setStatus('ok');
          setMessage(tv ? 'Upareno! Ovaj ekran je sada Jarvisov TV prikaz.' : 'Upareno! Otvaram HUD…');
          setTimeout(() => navigate(tv ? '/display?screen=tv' : '/hud', { replace: true }), 800);
        })
        .catch((e) => {
          setStatus('error');
          setMessage(e instanceof Error ? e.message : String(e));
        });
    },
    [navigate],
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const code = params.get('code') || '';
    window.history.replaceState(null, '', window.location.pathname);
    if (!code) {
      setStatus('ask');
      return;
    }
    claim(code, isTv);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === 'ask' || status === 'error') {
    return (
      <form
        className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center"
        onSubmit={(e) => {
          e.preventDefault();
          if (typed.trim()) claim(typed.trim(), isTv);
        }}
      >
        {status === 'error' && <div style={{ color: 'var(--color-error)' }}>{message}</div>}
        <div className="text-lg">Upiši kod sa HUD-a (Uređaji → QR kod)</div>
        <input
          autoFocus
          value={typed}
          onChange={(e) => setTyped(e.target.value.toUpperCase())}
          maxLength={9}
          className="text-3xl tracking-[0.3em] text-center px-4 py-3 rounded-lg w-72"
          style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }}
        />
        <label className="flex items-center gap-2 text-base">
          <input type="checkbox" checked={isTv} onChange={(e) => setIsTv(e.target.checked)} /> Ovo je TV (samo prikaz)
        </label>
        <button type="submit" className="px-6 py-3 rounded-lg text-lg" style={{ background: 'var(--color-accent)', color: 'var(--color-text-inverse)' }}>
          Upari
        </button>
      </form>
    );
  }

  return (
    <div className="flex h-full items-center justify-center p-6 text-center">
      <div className="text-base" style={{ color: 'var(--color-text)' }}>
        {message}
      </div>
    </div>
  );
}
