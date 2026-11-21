import { useCallback, useEffect, useRef, useState } from 'react';
import { Captions, Clapperboard, Download, HardDrive, LoaderCircle, Plus, Radio, RefreshCw, Sparkles } from 'lucide-react';
import { request, seconds, sizeLabel, type CampaignTemplate, type RenderOptions, type StreamerTemplate, type Video } from '../api';
import { canSaveBuffer, captureLimits, channelQuery, DirectControls, platformLabel, saveChannel,
  type CaptureLimit, type ChannelOverview, type DirectChannel } from './DirectLive';
import { AutoClipping } from './AutoClipping';

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
  method?: CaptureMethod | 'auto';
  platform?: string;
  channel?: string;
  channel_name?: string;
  quality?: string;
}

const obsLengths = [30, 60, 90] as const;
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
  onOpen: (video: Video, destination: LiveDestination, options?: RenderOptions) => void;
}) {
  const [method, setMethod] = useState<CaptureMethod>(() => preferences('clipzone.live.method') === 'obs' ? 'obs' : 'direct');
  const [obsLength, setObsLength] = useState<ReplayLength>(() => preferredLength(obsLengths, 'clipzone.live.duration'));
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [history, setHistory] = useState<Capture[]>([]);
  const [historyReady, setHistoryReady] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [captureError, setCaptureError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [overview, setOverview] = useState<ChannelOverview | null>(null);
  const [selectedId, setSelectedId] = useState(() => preferences('clipzone.direct.selected') ?? '');
  const [channelUrl, setChannelUrl] = useState('');
  const [adding, setAdding] = useState(false);
  const [channelsError, setChannelsError] = useState('');
  const [limitUpdating, setLimitUpdating] = useState(false);
  const [limitError, setLimitError] = useState('');
  const [addError, setAddError] = useState('');
  const [savingChannels, setSavingChannels] = useState<string[]>([]);
  const [streamerFilter, setStreamerFilter] = useState('');
  const capturing = useRef(false);
  const checkingRef = useRef(false);
  const historyRevision = useRef(0);
  const savingDirect = useRef(new Set<string>());
  const channelRevision = useRef(0);
  const selected = overview?.channels.find(channel => channel.id === selectedId) ?? overview?.channels[0];
  const [platform, channel] = selected?.id.split(':') ?? [];
  const length = obsLength;

  const refreshChannels = useCallback(async (signal?: AbortSignal) => {
    const revision = ++channelRevision.current;
    try {
      const latest = await request<ChannelOverview>('/live/direct/channels', { signal });
      if (signal?.aborted || revision !== channelRevision.current) return;
      setOverview(latest);
      setChannelsError('');
    } catch (cause) {
      if (!signal?.aborted && revision === channelRevision.current) setChannelsError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!active || method !== 'direct') return;
    const controller = new AbortController();
    const update = () => { if (!document.hidden) void refreshChannels(controller.signal); };
    const migrationKey = 'clipzone.direct.channels.migrated';
    if (!preferences(migrationKey)) {
      const previous = [...new Set([preferences('clipzone.direct.url.0'), preferences('clipzone.direct.url.1')])];
      void Promise.all(previous.filter((url): url is string => !!url).map(url => saveChannel(url))).then(() => {
        remember(migrationKey, '1');
        if (!controller.signal.aborted) update();
      }).catch(() => { /* Los canales se pueden registrar desde el panel. */ });
    }
    update();
    const poll = window.setInterval(update, 1000);
    document.addEventListener('visibilitychange', update);
    return () => {
      controller.abort();
      window.clearInterval(poll);
      document.removeEventListener('visibilitychange', update);
    };
  }, [active, method, refreshChannels]);

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

  const ready = status?.ready && !status.busy && !saving;
  const capture = useCallback(async (entry?: DirectChannel) => {
    if (!active) return;
    if (entry) {
      if (!canSaveBuffer(entry.capture) || savingDirect.current.has(entry.id)) return;
      savingDirect.current.add(entry.id);
      setSavingChannels([...savingDirect.current]);
    } else {
      if (!ready || capturing.current) return;
      capturing.current = true;
      setSaving(true);
    }
    setCaptureError('');
    setNotice('');
    try {
      const endpoint = entry ? '/live/direct/captures' + channelQuery(entry.id) : '/live/captures';
      const saved = await request<Capture>(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds: entry?.seconds ?? length }),
      });
      historyRevision.current++;
      setHistory(previous => [saved, ...previous.filter(item => item.id !== saved.id)]);
      setHistoryReady(true);
      if (saved.video) onImported(saved.video);
      setNotice(entry ? `Fragmento de ${entry.name ?? entry.id.split(':')[1]} guardado e importado a Mis vídeos.` : 'Fragmento guardado e importado a Mis vídeos.');
    } catch (cause) {
      setCaptureError((cause as Error).message);
    } finally {
      if (entry) {
        savingDirect.current.delete(entry.id);
        setSavingChannels([...savingDirect.current]);
        void refreshChannels();
      } else {
        capturing.current = false;
        setSaving(false);
        void refreshStatus();
      }
    }
  }, [active, ready, length, onImported, refreshStatus, refreshChannels]);

  useEffect(() => {
    if (!active) return;
    function onKey(event: KeyboardEvent) {
      if (event.repeat || event.defaultPrevented || event.getModifierState('AltGraph') ||
          !event.ctrlKey || !event.altKey || event.shiftKey || event.metaKey || event.code !== 'KeyG') return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || target.closest('input, textarea, select, [role="dialog"]'))) return;
      if (method === 'direct' ? !selected || !canSaveBuffer(selected.capture) : !ready) return;
      event.preventDefault();
      void capture(method === 'direct' ? selected : undefined);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, capture, ready, method, selected]);

  function changeLength(value: ReplayLength) {
    setObsLength(value);
    remember('clipzone.live.duration', String(value));
  }
  function selectChannel(id: string) {
    setSelectedId(id);
    remember('clipzone.direct.selected', id);
  }
  async function addChannel() {
    setAdding(true);
    setAddError('');
    try {
      const saved = await saveChannel(channelUrl);
      selectChannel(saved.id);
      setChannelUrl('');
      await refreshChannels();
    } catch (cause) {
      setAddError((cause as Error).message);
    } finally {
      setAdding(false);
    }
  }
  async function changeLimit(max_active: CaptureLimit) {
    setLimitUpdating(true);
    setLimitError('');
    try {
      await request('/live/direct/settings', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ max_active }),
      });
      await refreshChannels();
    } catch (cause) {
      setLimitError((cause as Error).message);
    } finally {
      setLimitUpdating(false);
    }
  }
  function changeMethod(value: CaptureMethod) {
    setMethod(value);
    setCaptureError('');
    setNotice('');
    remember('clipzone.live.method', value);
  }

  function onAutoKeep(video: Video) {
    onImported(video);
    const revision = ++historyRevision.current;
    request<Capture[]>('/live/captures').then(items => {
      if (revision === historyRevision.current) setHistory(items);
    }).catch(cause => setHistoryError((cause as Error).message));
  }

  const connection = status?.connected ? 'OBS conectado' : checking && !status ? 'Buscando OBS…' : 'OBS sin conexión';
  const librarySize = history.reduce((sum, item) => sum + (item.video ? item.size : 0), 0);
  const channelKey = (item: Capture) => item.channel ? `${item.platform}:${item.channel}` : '';
  const channels = [...new Set(history.map(channelKey).filter(Boolean))].sort();
  const visibleHistory = history.filter(item => !streamerFilter || channelKey(item) === streamerFilter);
  async function openCapture(item: Capture, destination: LiveDestination) {
    if (!item.video) return;
    let options: RenderOptions | undefined;
    if (item.channel) {
      try {
        const links = await request<StreamerTemplate[]>('/live/streamers');
        const templateId = links.find(link => link.id === channelKey(item))?.template_id;
        if (templateId) options = (await request<CampaignTemplate[]>('/templates')).find(template => template.id === templateId)?.options;
      } catch (cause) { setHistoryError((cause as Error).message); }
    }
    onOpen(item.video, destination, options);
  }
  return <div className="live-workspace">
    <div className="live-methods" role="group" aria-label="Método de captura">
      <button className="secondary" aria-pressed={method === 'direct'} disabled={saving} onClick={() => changeMethod('direct')}>Captura directa</button>
      <button className="secondary" aria-pressed={method === 'obs'} disabled={saving} onClick={() => changeMethod('obs')}>OBS Studio</button>
    </div>
    <section className="panel live-controls" data-method={method} aria-labelledby="live-save-heading">
      <div className="panel-heading"><div><Radio size={18}/><h2 id="live-save-heading">{method === 'obs' ? 'Guardar repetición' : 'MultiStream IA'}</h2></div></div>
      <div className="live-body">
        {method === 'direct' ? <>
          <div className="live-status-row">
            {overview && <span role="status">{overview.active} de {overview.max_active} capturas activas</span>}
            {selected && <span><kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>G</kbd> · {selected.name ?? channel}</span>}
          </div>
          {overview && <label className="live-capture-limit">Límite de capturas simultáneas
            <select disabled={limitUpdating} value={overview.max_active}
              onChange={event => void changeLimit(Number(event.target.value) as CaptureLimit)}>
              {captureLimits.map(value => <option key={value} value={value}>{value} canales</option>)}
            </select>
          </label>}
          {limitError && <p className="live-error" role="alert">{limitError}</p>}
          <form className="live-source-form" onSubmit={event => { event.preventDefault(); void addChannel(); }}>
            <label htmlFor="live-source-url">URL del directo autorizado</label>
            <div>
              <input id="live-source-url" type="url" maxLength={500} value={channelUrl} required disabled={adding}
                placeholder="URL de Kick, Twitch o YouTube Live" onChange={event => setChannelUrl(event.target.value)}/>
              <button type="submit" className="secondary" disabled={adding || !channelUrl.trim()}>
                {adding ? <LoaderCircle className="spin" size={16}/> : <Plus size={16}/>}Añadir canal
              </button>
            </div>
          </form>
          {(addError || channelsError) && <p className="live-error" role="alert">{addError || channelsError}</p>}
          {overview?.installed === false && <p className="live-note">Instala Streamlink para habilitar la captura directa.
            {' '}<code>.\.venv\Scripts\python.exe -m pip install -r backend/requirements-live.txt</code>
          </p>}
          {overview?.channels.length === 0 && <p className="live-note">Añade un canal de Kick, Twitch o YouTube para empezar.</p>}
          {overview && overview.active >= overview.max_active && <p className="live-note">Detén una captura para iniciar otro canal.</p>}
          <div className="live-channels">
            {overview?.channels.map(entry => <DirectControls key={entry.id} entry={entry} installed={overview.installed}
              atLimit={overview.active >= overview.max_active} selected={selected?.id === entry.id} saving={savingChannels.includes(entry.id)}
              onSelect={() => selectChannel(entry.id)} onChange={refreshChannels} onSave={() => capture(entry)}/>)}
          </div>
        </> : <>
          <div className="live-status-row">
          <span className="live-state" data-online={status?.connected || undefined}><i/>{connection}</span>
          <span>{status?.buffer_active ? 'Búfer activo' : 'Búfer inactivo'}{status?.buffer_seconds ? ` · hasta ${status.buffer_seconds} s` : ''}</span>
          <button type="button" className="icon-button" aria-label="Comprobar conexión con OBS" title="Comprobar conexión con OBS"
            disabled={checking} onClick={() => void refreshStatus()}><RefreshCw size={17}/></button>
          </div>
          {(connectionError || status?.error) && <p className="live-error" role="status">{connectionError || status?.error}</p>}
          {status?.connected && !status.buffer_active && <p className="live-note">Inicia el búfer de repetición en OBS.</p>}
        <fieldset className="live-length" disabled={saving}>
          <legend>Guardar los últimos</legend>
          {obsLengths.map(value => <button type="button" key={value} className="secondary" aria-pressed={length === value}
            onClick={() => changeLength(value)}>{value} s</button>)}
        </fieldset>
        {status?.buffer_seconds && status.buffer_seconds < length &&
          <p className="live-note">OBS tiene configurados {status.buffer_seconds} s. Para guardar {length} s completos, ajusta y reinicia su búfer.</p>}
        <div className="live-save-row">
          <button className="primary" disabled={!ready} aria-keyshortcuts="Control+Alt+G" onClick={() => void capture()}>
            {saving ? <LoaderCircle className="spin" size={17}/> : <Radio size={17}/>}
            {saving ? 'Guardando e importando…' : 'Guardar fragmento'}
          </button>
          <span className="live-note"><kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>G</kbd> con ClipZone Live enfocado</span>
        </div>
        {status?.busy && !saving && <p className="live-note" role="status">Hay otro guardado en curso.</p>}
        <details className="live-setup">
          <summary>Configurar OBS Studio</summary>
          <ol>
            <li>En OBS, activa el servidor WebSocket 5. Usa el puerto {status?.port || '4455'} y la contraseña configurada para ClipZone.</li>
            <li>En Ajustes → Salida, activa el búfer de repetición y fija el tiempo máximo en 90 s.</li>
            <li>Usa esta ruta de grabación e inicia el búfer desde OBS.</li>
          </ol>
          {status?.replay_dir && <code>{status.replay_dir}</code>}
          <p>OBS conserva la repetición que escribe en esa carpeta. La copia importada se administra desde Mis vídeos.</p>
        </details>
        </>}
        {captureError && <p className="live-error" role="alert">{captureError}</p>}
        {notice && <p className="live-success" role="status">{notice}</p>}
      </div>
    </section>
    <section className="panel live-storage" data-method={method} aria-labelledby="live-storage-heading">
      <div className="panel-heading"><div><HardDrive size={18}/><h2 id="live-storage-heading">Almacenamiento</h2></div></div>
      <dl className="live-body">
        {method === 'obs' ? <>
          <div><dt>Libre para OBS</dt><dd>{available(status?.replay_free_bytes)}</dd></div>
          <div><dt>Libre en la biblioteca de ClipZone</dt><dd>{available(status?.library_free_bytes)}</dd></div>
        </> : <>
          <div><dt>Búfer de todos los canales</dt><dd>{overview ? `${sizeLabel(overview.bytes)} / ${sizeLabel(overview.max_bytes)}` : 'No disponible'}</dd></div>
          <div><dt>Libre para captura directa</dt><dd>{available(overview?.free_bytes)}</dd></div>
        </>}
        <div><dt>Capturas en la biblioteca</dt><dd>{sizeLabel(librarySize)}</dd></div>
      </dl>
    </section>
    <AutoClipping key={method === 'direct' ? selected?.id ?? 'history' : 'obs'}
      streamer={method === 'direct' && selected ? { id: selected.id, url: selected.url, platform, channel, name: selected.name } : null}
      active={active} onKeep={onAutoKeep} onConfig={refreshChannels} onEdit={(video, options) => onOpen(video, 'editor', options)}/>
    <section className="panel live-history" aria-labelledby="live-history-heading">
      <div className="panel-heading"><div><Clapperboard size={18}/><h2 id="live-history-heading">Historial de capturas</h2></div></div>
      <div className="live-body">
        {historyError && <p className="live-error" role="alert">{historyError}</p>}
        {!historyError && history.length === 0 && <p className="live-note">{historyReady ? 'Todavía no hay fragmentos guardados.' : 'Cargando historial…'}</p>}
        {channels.length > 0 && <label>Filtrar capturas por streamer <select value={streamerFilter}
          onChange={e => setStreamerFilter(e.target.value)}><option value="">Todos</option>
          {channels.map(channel => {
            const item = history.find(capture => channelKey(capture) === channel);
            return <option key={channel} value={channel}>{item?.channel_name ? `${platformLabel(item.platform)} · ${item.channel_name}` : channel}</option>;
          })}
        </select></label>}
        <ul>
          {visibleHistory.map(item => <li key={item.id}>
            <div className="live-capture-info">
              <h3>{item.name}</h3>
              {item.channel && <p>{platformLabel(item.platform)} · {item.channel_name ?? item.channel}</p>}
              <p><time dateTime={item.captured_at}>{dateLabel.format(new Date(item.captured_at))}</time> · {seconds(item.duration)} · {sizeLabel(item.size)} · {item.method === 'auto' ? 'AutoClipping IA' : item.method === 'direct' ? [platformLabel(item.platform), item.quality].filter(Boolean).join(' · ') : 'OBS Studio'}</p>
              {item.duration + 0.15 < item.requested_seconds &&
                <p>Se guardaron {Math.round(item.duration * 10) / 10} s de los {item.requested_seconds} s solicitados.</p>}
            </div>
            {item.video ? <div className="live-capture-actions">
              <button className="secondary" onClick={() => void openCapture(item, 'editor')}><Clapperboard size={15}/>Editor</button>
              <button className="secondary" onClick={() => void openCapture(item, 'analysis')}><Sparkles size={15}/>Analizar con Whisper</button>
              <button className="secondary" onClick={() => void openCapture(item, 'subtitles')}><Captions size={15}/>Subtítulos</button>
              <button className="secondary" onClick={() => void openCapture(item, 'export')}><Download size={15}/>Ir a exportar</button>
            </div> : <span className="live-note">Retirado de Mis vídeos</span>}
          </li>)}
        </ul>
      </div>
    </section>
  </div>;
}
