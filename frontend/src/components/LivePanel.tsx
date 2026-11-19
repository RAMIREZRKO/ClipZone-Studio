import { useCallback, useEffect, useRef, useState } from 'react';
import { Captions, Clapperboard, Download, HardDrive, LoaderCircle, Radio, RefreshCw, Sparkles } from 'lucide-react';
import { request, seconds, sizeLabel, type Video } from '../api';
import { DirectControls, platformLabel, useDirectLive } from './DirectLive';

type CaptureMethod = 'direct' | 'obs';
type ReplayLength = 30 | 60 | 90 | 120 | 300;
export type LiveDestination = 'editor' | 'analysis' | 'subtitles' | 'export';

interface LiveStatus {
  connected: boolean;
  buffer_active: boolean;
  buffer_seconds: number | null;
  ready: boolean;
  busy: boolean;
  port: string;
  error: string | null;
  replay_dir: string;
  replay_free_bytes: number | null;
  library_free_bytes: number | null;
}

interface Capture {
  id: string;
  name: string;
  requested_seconds: ReplayLength;
  captured_at: string;
  duration: number;
  size: number;
  video: Video | null;
  method?: CaptureMethod;
  platform?: string;
  quality?: string;
}

const obsLengths = [30, 60, 90] as const;
const directLengths = [30, 60, 90, 120, 300] as const;
const dateLabel = new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' });
const available = (bytes: number | null | undefined) => bytes == null ? 'No disponible' : sizeLabel(bytes);

function preferences(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key: string, value: string) {
  try { window.localStorage.setItem(key, value); }
  catch { /* El navegador puede bloquear el almacenamiento de preferencias. */ }
}

function preferredLength(options: readonly ReplayLength[], key: string): ReplayLength {
  return options.find(value => value === Number(preferences(key))) ?? 60;
}

export function LivePanel({ active, onImported, onOpen }: {
  active: boolean;
  onImported: (video: Video) => void;
  onOpen: (video: Video, destination: LiveDestination) => void;
}) {
  const [method, setMethod] = useState<CaptureMethod>(() => preferences('clipzone.live.method') === 'obs' ? 'obs' : 'direct');
  const [obsLength, setObsLength] = useState<ReplayLength>(() => preferredLength(obsLengths, 'clipzone.live.duration'));
  const [directLength, setDirectLength] = useState<ReplayLength>(() => preferredLength(directLengths, 'clipzone.live.direct.duration'));
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [history, setHistory] = useState<Capture[]>([]);
  const [historyReady, setHistoryReady] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [captureError, setCaptureError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const capturing = useRef(false);
  const checkingRef = useRef(false);
  const historyRevision = useRef(0);
  const direct = useDirectLive(active && method === 'direct');
  const { status: directStatus, refresh: refreshDirect } = direct;
  const length = method === 'obs' ? obsLength : directLength;

  const refreshStatus = useCallback(async () => {
    if (checkingRef.current) return;
    checkingRef.current = true;
    setChecking(true);
    try {
      setStatus(await request<LiveStatus>('/live/status'));
      setConnectionError('');
    } catch (cause) {
      setStatus(null);
      setConnectionError((cause as Error).message);
    } finally {
      checkingRef.current = false;
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    if (!active || method !== 'obs') return;
    const refresh = () => {
      if (!document.hidden && !capturing.current) void refreshStatus();
    };
    refresh();
    const interval = window.setInterval(refresh, 10_000);
    return () => window.clearInterval(interval);
  }, [active, method, refreshStatus]);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const revision = historyRevision.current;
    setHistoryError('');
    request<Capture[]>('/live/captures', { signal: controller.signal }).then(items => {
      if (revision === historyRevision.current) setHistory(items);
      setHistoryReady(true);
    }).catch(cause => {
      if (!controller.signal.aborted) setHistoryError((cause as Error).message);
    });
    return () => controller.abort();
  }, [active]);

  const busy = method === 'obs' ? status?.busy : directStatus?.saving;
  const ready = (method === 'obs' ? status?.ready : (directStatus?.buffer_seconds ?? 0) > 0) && !busy && !saving;
  const capture = useCallback(async () => {
    if (!active || !ready || capturing.current) return;
    capturing.current = true;
    setSaving(true);
    setCaptureError('');
    setNotice('');
    try {
      const endpoint = method === 'obs' ? '/live/captures' : '/live/direct/captures';
      const saved = await request<Capture>(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds: length }),
      });
      historyRevision.current++;
      setHistory(previous => [saved, ...previous.filter(item => item.id !== saved.id)]);
      setHistoryReady(true);
      if (saved.video) onImported(saved.video);
      setNotice('Fragmento guardado e importado a Mis vídeos.');
    } catch (cause) {
      setCaptureError((cause as Error).message);
    } finally {
      capturing.current = false;
      setSaving(false);
      if (method === 'obs') void refreshStatus();
      else void refreshDirect();
    }
  }, [active, ready, method, length, onImported, refreshStatus, refreshDirect]);

  useEffect(() => {
    if (!active) return;
    function onKey(event: KeyboardEvent) {
      if (event.repeat || event.defaultPrevented || event.getModifierState('AltGraph') ||
          !event.ctrlKey || !event.altKey || event.shiftKey || event.metaKey || event.code !== 'KeyG') return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || target.closest('input, textarea, select, [role="dialog"]'))) return;
      if (!ready) return;
      event.preventDefault();
      void capture();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, capture, ready]);

  function changeLength(value: ReplayLength) {
    if (method === 'obs') {
      setObsLength(value);
      remember('clipzone.live.duration', String(value));
    } else {
      setDirectLength(value);
      remember('clipzone.live.direct.duration', String(value));
    }
  }
  function changeMethod(value: CaptureMethod) {
    setMethod(value);
    setCaptureError('');
    setNotice('');
    remember('clipzone.live.method', value);
  }

  const connection = status?.connected ? 'OBS conectado' : checking && !status ? 'Buscando OBS…' : 'OBS sin conexión';
  const librarySize = history.reduce((sum, item) => sum + (item.video ? item.size : 0), 0);
  return <div className="live-workspace">
    <div className="live-methods" role="group" aria-label="Método de captura">
      <button className="secondary" aria-pressed={method === 'direct'} disabled={saving} onClick={() => changeMethod('direct')}>Captura directa</button>
      <button className="secondary" aria-pressed={method === 'obs'} disabled={saving} onClick={() => changeMethod('obs')}>OBS Studio</button>
    </div>
    <section className="panel live-controls" aria-labelledby="live-save-heading">
      <div className="panel-heading"><div><Radio size={18}/><h2 id="live-save-heading">{method === 'obs' ? 'Guardar repetición' : 'Transmisión en directo'}</h2></div></div>
      <div className="live-body">
        {method === 'direct' ? <DirectControls direct={direct}/> : <>
          <div className="live-status-row">
          <span className="live-state" data-online={status?.connected || undefined}><i/>{connection}</span>
          <span>{status?.buffer_active ? 'Búfer activo' : 'Búfer inactivo'}{status?.buffer_seconds ? ` · hasta ${status.buffer_seconds} s` : ''}</span>
          <button type="button" className="icon-button" aria-label="Comprobar conexión con OBS" title="Comprobar conexión con OBS"
            disabled={checking} onClick={() => void refreshStatus()}><RefreshCw size={17}/></button>
          </div>
          {(connectionError || status?.error) && <p className="live-error" role="status">{connectionError || status?.error}</p>}
          {status?.connected && !status.buffer_active && <p className="live-note">Inicia el búfer de repetición en OBS.</p>}
        </>}
        <fieldset className="live-length" disabled={saving}>
          <legend>Guardar los últimos</legend>
          {(method === 'obs' ? obsLengths : directLengths).map(value => <button type="button" key={value} className="secondary" aria-pressed={length === value}
            onClick={() => changeLength(value)}>{value} s</button>)}
        </fieldset>
        {method === 'obs' && status?.buffer_seconds && status.buffer_seconds < length &&
          <p className="live-note">OBS tiene configurados {status.buffer_seconds} s. Para guardar {length} s completos, ajusta y reinicia su búfer.</p>}
        <div className="live-save-row">
          <button className="primary" disabled={!ready} aria-keyshortcuts="Control+Alt+G" onClick={() => void capture()}>
            {saving ? <LoaderCircle className="spin" size={17}/> : <Radio size={17}/>}
            {saving ? 'Guardando e importando…' : 'Guardar fragmento'}
          </button>
          <span className="live-note"><kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>G</kbd> con ClipZone Live enfocado</span>
        </div>
        {busy && !saving && <p className="live-note" role="status">Hay otro guardado en curso.</p>}
        {captureError && <p className="live-error" role="alert">{captureError}</p>}
        {notice && <p className="live-success" role="status">{notice}</p>}
        {method === 'obs' && <details className="live-setup">
          <summary>Configurar OBS Studio</summary>
          <ol>
            <li>En OBS, activa el servidor WebSocket 5. Usa el puerto {status?.port || '4455'} y la contraseña configurada para ClipZone.</li>
            <li>En Ajustes → Salida, activa el búfer de repetición y fija el tiempo máximo en 90 s.</li>
            <li>Usa esta ruta de grabación e inicia el búfer desde OBS.</li>
          </ol>
          {status?.replay_dir && <code>{status.replay_dir}</code>}
          <p>OBS conserva la repetición que escribe en esa carpeta. La copia importada se administra desde Mis vídeos.</p>
        </details>}
      </div>
    </section>
    <section className="panel live-storage" aria-labelledby="live-storage-heading">
      <div className="panel-heading"><div><HardDrive size={18}/><h2 id="live-storage-heading">Almacenamiento</h2></div></div>
      <dl className="live-body">
        {method === 'obs' ? <>
          <div><dt>Libre para OBS</dt><dd>{available(status?.replay_free_bytes)}</dd></div>
          <div><dt>Libre en la biblioteca de ClipZone</dt><dd>{available(status?.library_free_bytes)}</dd></div>
        </> : <>
          <div><dt>Búfer en disco</dt><dd>{directStatus ? `${sizeLabel(directStatus.bytes)} / ${sizeLabel(directStatus.max_bytes)}` : 'No disponible'}</dd></div>
          <div><dt>Libre para captura directa</dt><dd>{available(directStatus?.free_bytes)}</dd></div>
        </>}
        <div><dt>Capturas en la biblioteca</dt><dd>{sizeLabel(librarySize)}</dd></div>
      </dl>
    </section>
    <section className="panel live-history" aria-labelledby="live-history-heading">
      <div className="panel-heading"><div><Clapperboard size={18}/><h2 id="live-history-heading">Historial de capturas</h2></div></div>
      <div className="live-body">
        {historyError && <p className="live-error" role="alert">{historyError}</p>}
        {!historyError && history.length === 0 && <p className="live-note">{historyReady ? 'Todavía no hay fragmentos guardados.' : 'Cargando historial…'}</p>}
        <ul>
          {history.map(item => <li key={item.id}>
            <div className="live-capture-info">
              <h3>{item.name}</h3>
              <p><time dateTime={item.captured_at}>{dateLabel.format(new Date(item.captured_at))}</time> · {seconds(item.duration)} · {sizeLabel(item.size)} · {item.method === 'direct' ? [platformLabel(item.platform), item.quality].filter(Boolean).join(' · ') : 'OBS Studio'}</p>
              {item.duration + 0.15 < item.requested_seconds &&
                <p>Se guardaron {Math.round(item.duration * 10) / 10} s de los {item.requested_seconds} s solicitados.</p>}
            </div>
            {item.video ? <div className="live-capture-actions">
              <button className="secondary" onClick={() => onOpen(item.video!, 'editor')}><Clapperboard size={15}/>Editor</button>
              <button className="secondary" onClick={() => onOpen(item.video!, 'analysis')}><Sparkles size={15}/>Analizar con Whisper</button>
              <button className="secondary" onClick={() => onOpen(item.video!, 'subtitles')}><Captions size={15}/>Subtítulos</button>
              <button className="secondary" onClick={() => onOpen(item.video!, 'export')}><Download size={15}/>Ir a exportar</button>
            </div> : <span className="live-note">Retirado de Mis vídeos</span>}
          </li>)}
        </ul>
      </div>
    </section>
  </div>;
}
