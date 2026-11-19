import { useCallback, useEffect, useRef, useState } from 'react';
import { LoaderCircle, Radio, Square } from 'lucide-react';
import { request, seconds } from '../api';

interface DirectStatus {
  installed: boolean;
  state: 'idle' | 'connecting' | 'capturing' | 'reconnecting' | 'stopping' | 'stopped' | 'ended' | 'error';
  url: string | null;
  quality: string | null;
  platform: string | null;
  elapsed: number;
  buffer_seconds: number;
  bytes: number;
  max_bytes: number;
  free_bytes: number | null;
  saving: boolean;
  retries: number;
  max_retries: number;
  message: string | null;
}
interface ProbeResult {
  url: string;
  platform: string;
  live: boolean;
  qualities: string[];
}

const stateLabels: Record<DirectStatus['state'], string> = {
  idle: 'Sin captura activa',
  connecting: 'Conectando al directo…',
  capturing: 'Capturando en segundo plano',
  reconnecting: 'Reconectando…',
  stopping: 'Deteniendo captura…',
  stopped: 'Captura detenida',
  ended: 'Directo finalizado',
  error: 'Captura interrumpida',
};
const activeStates: DirectStatus['state'][] = ['connecting', 'capturing', 'reconnecting', 'stopping'];
export const platformLabel = (platform: string | null | undefined) =>
  platform === 'kick' ? 'Kick' : platform === 'twitch' ? 'Twitch' : 'Captura directa';

function post<T>(resource: string, body?: object) {
  return request<T>(`/live/direct/${resource}`, {
    method: 'POST',
    ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  });
}

export function useDirectLive(active: boolean) {
  const [status, setStatus] = useState<DirectStatus | null>(null);
  const [url, setUrl] = useState('');
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [quality, setQuality] = useState('');
  const [working, setWorking] = useState<'probe' | 'start' | 'stop' | null>(null);
  const [error, setError] = useState('');
  const [statusError, setStatusError] = useState('');
  const statusSequence = useRef(0);
  const commandInFlight = useRef(false);
  const running = status !== null && activeStates.includes(status.state);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const sequence = ++statusSequence.current;
    try {
      const latest = await request<DirectStatus>('/live/direct/status', { signal });
      if (signal?.aborted || sequence !== statusSequence.current) return;
      setStatus(latest);
      setStatusError('');
    } catch (cause) {
      if (!signal?.aborted && sequence === statusSequence.current) setStatusError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const update = () => { if (!document.hidden) void refresh(controller.signal); };
    update();
    const poll = window.setInterval(update, 1000);
    document.addEventListener('visibilitychange', update);
    return () => {
      controller.abort();
      window.clearInterval(poll);
      document.removeEventListener('visibilitychange', update);
    };
  }, [active, refresh]);

  function changeUrl(value: string) {
    setUrl(value);
    setProbe(null);
    setQuality('');
    setError('');
  }

  async function command(action: 'probe' | 'start' | 'stop') {
    if (commandInFlight.current) return;
    commandInFlight.current = true;
    setWorking(action);
    setError('');
    try {
      if (action === 'probe') {
        setProbe(null);
        setQuality('');
        const result = await post<ProbeResult>('probe', { url });
        setUrl(result.url);
        setProbe(result);
        setQuality(result.qualities[0] ?? '');
      } else {
        const result = await post<DirectStatus>(action, action === 'start' ? { url, quality } : undefined);
        statusSequence.current++;
        setStatus(result);
      }
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      commandInFlight.current = false;
      setWorking(null);
    }
  }

  return { status, url, probe, quality, working, error, statusError, running, refresh, changeUrl, setQuality, command };
}

export function DirectControls({ direct }: { direct: ReturnType<typeof useDirectLive> }) {
  const { status, probe, running, working } = direct;
  const selected = running ? status?.quality ?? '' : direct.quality;
  const qualities = running && selected ? [selected] : probe?.qualities ?? [];
  const state = status?.state;
  const message = direct.error || direct.statusError || status?.message;
  const error = direct.error || direct.statusError || state === 'error';
  return <>
    <div className="live-status-row">
      <span className="live-state" data-online={state === 'capturing' || undefined} role="status"><i/>
        {state ? stateLabels[state] : 'Consultando captura…'}
      </span>
      {running && <span>{platformLabel(status?.platform)} · {status?.quality}</span>}
      {status?.state === 'reconnecting' && <span>{status.retries}/{status.max_retries} reintentos</span>}
    </div>
    <form className="live-source-form" onSubmit={event => { event.preventDefault(); void direct.command('probe'); }}>
      <label htmlFor="live-source-url">URL del directo autorizado</label>
      <div>
        <input id="live-source-url" type="url" maxLength={500} value={running ? status?.url ?? direct.url : direct.url}
          placeholder="https://www.twitch.tv/tu_canal" disabled={running || !!working} required
          onChange={event => direct.changeUrl(event.target.value)}/>
        <button type="submit" className="secondary" disabled={running || !!working || !direct.url.trim() || status?.installed !== true}>
          {working === 'probe' ? <LoaderCircle className="spin" size={16}/> : null}
          {working === 'probe' ? 'Comprobando…' : 'Comprobar directo'}
        </button>
      </div>
    </form>
    {probe && !running && <p className="live-note" role="status">
      {platformLabel(probe.platform)} · {probe.live ? 'Canal en directo' : 'El canal no está en directo'}
    </p>}
    <div className="live-capture-options">
      <label>Calidad del directo<select value={selected} disabled={running || !!working || !qualities.length}
        onChange={event => direct.setQuality(event.target.value)}>
        {!qualities.length && <option value="">Comprueba el directo</option>}
        {qualities.map(quality => <option value={quality} key={quality}>{quality === 'source' ? 'Fuente' : quality === 'live' ? 'Disponible' : quality}</option>)}
      </select></label>
      <button className="secondary" disabled={!probe?.live || !selected || running || !!working || status?.saving}
        onClick={() => void direct.command('start')}><Radio size={16}/>Iniciar captura</button>
      <button className="secondary" disabled={!running || state === 'stopping' || !!working}
        onClick={() => void direct.command('stop')}><Square size={14}/>Detener captura</button>
    </div>
    <dl className="live-capture-metrics">
      <div><dt>Tiempo de captura</dt><dd>{seconds(status?.elapsed ?? 0)}</dd></div>
      <div><dt>Disponible en el búfer</dt><dd>{seconds(status?.buffer_seconds ?? 0)}</dd></div>
    </dl>
    {status?.installed === false && <p className="live-note">Instala Streamlink para habilitar la captura directa.
      {' '}<code>.\.venv\Scripts\python.exe -m pip install -r backend/requirements-live.txt</code>
    </p>}
    {message && <p className={error ? 'live-error' : 'live-note'} role={error ? 'alert' : 'status'}>{message}</p>}
  </>;
}

