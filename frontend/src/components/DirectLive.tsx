import { useState } from 'react';
import { HardDrive, LoaderCircle, Radio, Square } from 'lucide-react';
import { request, seconds, sizeLabel, type StreamerTemplate } from '../api';

export const directLengths = [30, 60, 90, 120, 300] as const;
type DirectLength = typeof directLengths[number];
type BroadcastState = 'live' | 'scheduled' | 'vod' | 'offline' | 'ended';

interface DirectStatus {
  state: 'idle' | 'connecting' | 'capturing' | 'reconnecting' | 'stopping' | 'stopped' | 'ended' | 'error';
  quality: string | null;
  elapsed: number;
  buffer_seconds: number;
  buffer_ready?: boolean;
  bytes: number;
  max_bytes: number;
  saving: boolean;
  retries: number;
  max_retries: number;
  message: string | null;
}
interface ProbeResult {
  live: boolean;
  qualities: string[];
  broadcast_state?: BroadcastState;
}
export const captureLimits = [4, 6, 8, 10] as const;
export type CaptureLimit = typeof captureLimits[number];

export interface DirectChannel extends StreamerTemplate {
  quality: string | null;
  seconds: DirectLength;
  capture: DirectStatus;
  connection?: 'unknown' | 'checking' | 'online' | 'offline';
  qualities?: string[];
  broadcast_state?: BroadcastState | null;
  autoclip: { stage: string; options: { enabled: boolean } };
}
export interface ChannelOverview {
  channels: DirectChannel[];
  active: number;
  max_active: CaptureLimit;
  installed: boolean;
  bytes: number;
  max_bytes: number;
  free_bytes: number | null;
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
const autoLabels: Record<string, string> = {
  disabled: 'Desactivado', waiting: 'En espera', listening: 'Analizando audio',
  collecting: 'Reuniendo el clip', waiting_whisper: 'En cola para Whisper', transcribing: 'Transcribiendo', saving: 'Guardando',
  skipped: 'Candidato omitido', error: 'Error',
};
const activeStates: DirectStatus['state'][] = ['connecting', 'capturing', 'reconnecting', 'stopping'];
const connectionLabels = {
  unknown: 'Directo sin comprobar', checking: 'Comprobando…', online: 'Canal en directo',
  offline: 'El canal no está en directo',
};
const broadcastLabels: Record<BroadcastState, string> = {
  live: 'Canal en directo', scheduled: 'Transmisión programada', vod: 'Vídeo bajo demanda (VOD)',
  offline: 'El canal no está en directo', ended: 'Directo finalizado',
};
export const canSaveBuffer = (capture: DirectStatus) =>
  (capture.buffer_ready ?? capture.buffer_seconds > 0) && !capture.saving;
export const platformLabel = (platform: string | null | undefined) =>
  platform === 'kick' ? 'Kick' : platform === 'twitch' ? 'Twitch' : platform === 'youtube' ? 'YouTube' : 'Captura directa';

export function channelQuery(id: string) {
  return '?streamer=' + encodeURIComponent(id);
}

export function saveChannel(url: string, options?: Pick<Partial<DirectChannel>, 'quality' | 'seconds' | 'template_id'>, existingId?: string) {
  return request<StreamerTemplate>('/live/streamers' + (existingId ? channelQuery(existingId) : ''), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, ...options }),
  });
}

export function DirectControls({ entry, selected, installed, atLimit, saving, onSelect, onChange, onSave }: {
  entry: DirectChannel;
  selected: boolean;
  installed: boolean;
  atLimit: boolean;
  saving: boolean;
  onSelect: () => void;
  onChange: () => Promise<void>;
  onSave: () => Promise<void>;
}) {
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [working, setWorking] = useState<'probe' | 'start' | 'stop' | 'remove' | 'settings' | null>(null);
  const [error, setError] = useState('');
  const { capture, url, quality } = entry;
  const [platform, channel] = entry.id.split(':');
  const channelName = entry.name ?? channel;
  const running = activeStates.includes(capture.state);
  const connection = working === 'probe' ? 'checking' : entry.connection ?? (probe ? (probe.live ? 'online' : 'offline') : 'unknown');
  const probedQualities = entry.qualities ?? probe?.qualities;
  const qualities = running && capture.quality ? [capture.quality] : probedQualities?.length ? probedQualities :
    connection !== 'offline' && quality ? [quality] : [];
  const selectedQuality = running ? capture.quality : quality && qualities.includes(quality) ? quality : qualities[0];
  const canSave = canSaveBuffer(capture) && !saving && !working;
  const checking = connection === 'checking';
  const broadcast = entry.broadcast_state ?? probe?.broadcast_state;
  const stateLabel = running ? stateLabels[capture.state] : !checking && broadcast ? broadcastLabels[broadcast] : connectionLabels[connection];

  async function command(action: NonNullable<typeof working>, options?: Pick<Partial<DirectChannel>, 'quality' | 'seconds'>) {
    setWorking(action);
    setError('');
    try {
      if (action === 'remove') {
        await request('/live/streamers/' + encodeURIComponent(entry.id), { method: 'DELETE' });
      } else if (action === 'settings') {
        await saveChannel(url, options, entry.id);
      } else {
        const result = await request<ProbeResult | DirectStatus>(`/live/direct/${action}${channelQuery(entry.id)}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(action === 'start' ? { url, quality: selectedQuality } : { url }),
        });
        if (action === 'probe' && 'qualities' in result) {
          setProbe(result);
        }
      }
      await onChange();
    } catch (cause) {
      setError((cause as Error).message);
      await onChange();
    } finally {
      setWorking(null);
    }
  }

  return <article className="live-channel" aria-label={platformLabel(platform) + ' · ' + channelName}>
    <header className="live-channel-heading">
      <div><h3>{channelName}</h3><span>{platformLabel(platform)}</span></div>
      <button type="button" className="secondary" disabled={running || checking || !!working || saving || capture.saving}
        title="Retira el canal y su búfer temporal" onClick={() => void command('remove')}>Eliminar canal</button>
    </header>
    <div className="live-status-row">
      <span className="live-state" data-online={capture.state === 'capturing' || connection === 'online' || undefined}
        role="status"><i/>{stateLabel}</span>
      {!running && capture.state !== 'idle' && stateLabel !== stateLabels[capture.state] && <span>{stateLabels[capture.state]}</span>}
      {capture.state === 'reconnecting' && <span>{capture.retries}/{capture.max_retries} reintentos</span>}
      <span>AutoClipping · {autoLabels[entry.autoclip.stage]}</span>
    </div>
    <div className="live-capture-options">
      <label>Calidad del directo<select value={selectedQuality ?? ''} disabled={running || checking || !!working || !qualities.length}
        onChange={event => void command('settings', { quality: event.target.value })}>
        {!qualities.length && <option value="">Comprueba el directo</option>}
        {qualities.map(value => <option value={value} key={value}>{value === 'source' ? 'Fuente' : value === 'live' ? 'Disponible' : value}</option>)}
      </select></label>
      <button type="button" className="secondary" disabled={running || checking || !!working || !installed}
        onClick={() => void command('probe')}>Comprobar directo</button>
      <button type="button" className="secondary" disabled={!selectedQuality || !installed || running || atLimit || checking || !!working || capture.saving || connection === 'offline'}
        onClick={() => void command('start')}><Radio size={16}/>Iniciar captura</button>
      <button type="button" className="secondary" disabled={!running || capture.state === 'stopping' || !!working}
        onClick={() => void command('stop')}><Square size={14}/>Detener captura</button>
    </div>
    <dl className="live-capture-metrics">
      <div><dt>Tiempo de captura</dt><dd>{seconds(capture.elapsed)}</dd></div>
      <div><dt>Disponible en el búfer</dt><dd>{seconds(capture.buffer_ready === false ? 0 : capture.buffer_seconds)}</dd></div>
      <div><dt>Búfer en disco</dt><dd>{sizeLabel(capture.bytes)} / {sizeLabel(capture.max_bytes)}</dd></div>
    </dl>
    <div className="live-capture-options">
      <label>Guardar los últimos<select value={entry.seconds} disabled={!!working || saving}
        onChange={event => void command('settings', { seconds: Number(event.target.value) as DirectLength })}>
        {directLengths.map(value => <option value={value} key={value}>{value} s</option>)}
      </select></label>
      <button type="button" className="primary" disabled={!canSave} onClick={() => void onSave()}>
        {saving ? <LoaderCircle className="spin" size={16}/> : <HardDrive size={16}/>}
        {saving ? 'Guardando e importando…' : 'Guardar fragmento'}
      </button>
      <button type="button" className="secondary" aria-pressed={selected} onClick={onSelect}>AutoClipping y atajo</button>
    </div>
    {(error || capture.message) && <p className={error || capture.state === 'error' ? 'live-error' : 'live-note'}
      role={error || capture.state === 'error' ? 'alert' : 'status'}>{error || capture.message}</p>}
  </article>;
}
