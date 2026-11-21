import { useCallback, useEffect, useRef, useState } from 'react';
import { Clapperboard, Sparkles } from 'lucide-react';
import { request, seconds, sizeLabel, type CampaignTemplate, type RenderOptions, type StreamerTemplate, type Video } from '../api';
import { channelQuery, platformLabel, saveChannel } from './DirectLive';
import { NumericInput } from './NumericInput';

const modes = {
  gameplay: { label: 'Gameplay', hint: 'Da más peso a las acciones y resultados del juego mencionados cerca del evento.' },
  irl: { label: 'IRL / Just Chatting', hint: 'Muestrea el habla sostenida y busca relatos, bromas, discusiones y respuestas interesantes en la transcripción.' },
  mixed: { label: 'Mixto', hint: 'Combina las señales de gameplay con el análisis de conversaciones.' },
} as const;
type DetectionMode = keyof typeof modes;
const candidateLimits = [1, 5, 10, 20] as const;
type CandidateLimit = typeof candidateLimits[number];

interface CandidateStorage {
  bytes: number;
  max_bytes: number;
  available_bytes?: number;
  candidate_limit_gb?: CandidateLimit;
}

interface Options {
  enabled: boolean;
  model: 'tiny' | 'base' | 'small';
  detection_mode: DetectionMode;
  duration: 30 | 60 | 90;
  sensitivity: 'low' | 'balanced' | 'high';
  minimum_score: number;
  before: number;
  after: number;
  per_hour: number;
  interval: number;
}
interface Status extends CandidateStorage {
  options: Options;
  stage: string;
  message: string | null;
  detected: number;
  filtered: number;
  skipped: number;
  detection_modes?: SavedMode[];
  diagnostics?: {
    audio_segments: number; audio_failures: number; transcriptions: number; generated: number; deferred: number;
    last_score: number | null; best_score: number | null; last_error: string | null;
    omissions: Record<string, number>; filters: Record<string, number>;
  };
  vad: boolean;
  whisper: boolean;
  models: { id: string; installed: boolean }[];
}
type SavedMode = DetectionMode | 'reaction';
type RawStatus = Omit<Status, 'options'> & { options: Omit<Options, 'detection_mode'> & { detection_mode: string } };

function normalizeStatus(status: RawStatus): Status {
  const mode = status.options.detection_mode;
  const canonical = mode === 'reaction' || mode === 'irl' ? 'irl' : mode === 'gameplay' ? 'gameplay' : 'mixed';
  return { ...status, options: { ...status.options, detection_mode: canonical } };
}

interface Candidate {
  id: string;
  title: string;
  duration: number;
  score: number;
  reason: string;
  excerpt: string;
  detection_mode?: SavedMode;
  detection_type?: Exclude<SavedMode, 'mixed'>;
  metrics?: Record<string, number>;
  created_at: string;
  platform: string;
  channel: string;
  channel_name?: string;
  status: 'pending' | 'kept' | 'discarded';
  preview_url: string | null;
  thumbnail_url: string | null;
  video: Video | null;
}
const states: Record<string, string> = {
  disabled: 'Modo automático desactivado', waiting: 'Esperando captura directa',
  listening: 'Analizando señales del audio', collecting: 'Esperando segundos posteriores al evento',
  waiting_whisper: 'En cola para Whisper',
  transcribing: 'Transcribiendo candidato con Whisper', saving: 'Guardando candidato',
  skipped: 'Candidato omitido', error: 'Error de AutoClipping',
};
const diagnosticLabels: Record<string, string> = {
  nearby_signal: 'Señal cercana a otra pendiente', backlog_limit: 'Cola de señales llena',
  overlap: 'Solapamiento con un candidato guardado', hour_limit: 'Límite por hora',
  saved_interval: 'Intervalo desde el último clip guardado', expired_signal: 'Señal caducada',
  incomplete_buffer: 'Búfer anterior o posterior incompleto', no_audio: 'Fragmento sin audio utilizable',
  whisper_queue_timeout: 'Espera agotada en la cola de Whisper', whisper_cancelled: 'Análisis cancelado',
  candidate_storage: 'Espacio insuficiente para otro candidato', incomplete_render: 'MP4 incompleto',
  buffer_budget: 'Tamaño superior al margen del búfer',
  weak_reaction: 'Reacción vocal insuficiente', no_editorial_evidence: 'Sin contexto que confirme el momento',
  no_transcribed_voice: 'Sin voz transcrita en el evento', low_confidence: 'Confianza baja de Whisper',
  repetitive_speech: 'Texto repetitivo o con poco contenido', short_context: 'Contexto escaso',
  no_irl_context: 'Conversación sin desarrollo editorial',
  under_threshold: 'Puntuación por debajo del mínimo',
};
const metricLabels: Record<string, string> = {
  voice: 'Voz cerca del evento', alignment: 'Coincidencia temporal', confidence: 'Confianza de Whisper',
  coherence: 'Variedad y coherencia del texto', context: 'Contexto transcrito', repetition: 'Repetición (penaliza)',
  intensity: 'Intensidad del audio',
  dialogue: 'Estructura de la conversación',
};
const date = new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' });

export function AutoClipping({ active, streamer, onKeep, onEdit, onConfig }: {
  active: boolean;
  streamer: { id: string; url: string; platform: string; channel: string; name?: string } | null;
  onKeep: (video: Video) => void;
  onEdit: (video: Video, options?: RenderOptions) => void;
  onConfig: () => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState<Options | null>(null);
  const [rows, setRows] = useState<Candidate[]>([]);
  const [message, setMessage] = useState('');
  const [pollError, setPollError] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [splitTemplates, setSplitTemplates] = useState<CampaignTemplate[]>([]);
  const [links, setLinks] = useState<StreamerTemplate[]>([]);
  const [streamerFilter, setStreamerFilter] = useState('');
  const streamKey = (item: { platform: string; channel: string }) => `${item.platform}:${item.channel}`;
  const templateFor = (key: string) => splitTemplates.find(template => template.id === links.find(link => link.id === key)?.template_id);
  const selectedTemplate = streamer ? templateFor(streamKey(streamer)) : undefined;
  const query = streamer ? channelQuery(streamer.id) : '';
  const sequence = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const current = ++sequence.current;
    const [raw, candidates] = await Promise.allSettled([
      request<RawStatus>('/live/auto/status' + query, { signal }),
      request<Candidate[]>('/live/auto/candidates', { signal }),
    ]);
    if (signal?.aborted || current !== sequence.current) return;
    if (raw.status === 'fulfilled') {
      const next = normalizeStatus(raw.value);
      setStatus(next);
      setDraft(previous => previous ?? next.options);
    }
    if (candidates.status === 'fulfilled') setRows(candidates.value);
    const failure = raw.status === 'rejected' ? raw.reason : candidates.status === 'rejected' ? candidates.reason : null;
    setPollError(failure ? (failure as Error).message : '');
  }, [query]);

  useEffect(() => {
    if (!active) {
      setPreview(null);
      return;
    }
    const controller = new AbortController();
    request<CampaignTemplate[]>('/templates', { signal: controller.signal }).then(templates => {
      setSplitTemplates(templates.filter(template => !template.example && !template.kind && template.options.fit === 'split'));
    }).catch(() => {
      if (!controller.signal.aborted) setSplitTemplates([]);
    });
    request<StreamerTemplate[]>('/live/streamers', { signal: controller.signal }).then(setLinks)
      .catch(cause => { if (!controller.signal.aborted) setMessage((cause as Error).message); });
    const update = () => { if (!document.hidden) void refresh(controller.signal); };
    update();
    const timer = window.setInterval(update, 2500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [active, refresh]);

  async function configure(changes: Partial<Options>, keepDraft = false) {
    if (!status) return;
    setBusy(true);
    setMessage('');
    try {
      const options = status.detection_modes ? changes : { ...status.options, ...changes };
      const body = options.detection_mode === 'irl' && !status.detection_modes?.includes('irl')
        ? { ...options, detection_mode: 'reaction' } : options;
      const next = normalizeStatus(await request<RawStatus>('/live/auto/config' + query, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }));
      sequence.current++;
      setStatus(next);
      setDraft(previous => keepDraft && previous ? { ...previous, enabled: next.options.enabled } : next.options);
      onConfig();
    } catch (cause) {
      setMessage((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function configureStorage(limit_gb: CandidateLimit) {
    setBusy(true);
    setMessage('');
    try {
      const storage = await request<CandidateStorage>('/live/auto/storage', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit_gb }),
      });
      sequence.current++;
      setStatus(previous => previous ? { ...previous, ...storage } : previous);
    } catch (cause) {
      setMessage((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function bindTemplate(templateId: string) {
    if (!streamer) return;
    setBusy(true); setMessage('');
    try {
      const link = await saveChannel(streamer.url, { template_id: templateId || null }, streamer.id);
      setLinks(previous => [...previous.filter(item => item.id !== link.id), link]);
    } catch (cause) { setMessage((cause as Error).message); }
    finally { setBusy(false); }
  }

  async function review(item: Candidate, action: 'keep' | 'discard' | 'edit') {
    if (action === 'edit' && item.video) {
      onEdit(item.video, templateFor(streamKey(item))?.options);
      return;
    }
    setBusy(true);
    setMessage('');
    setPreview(null);
    try {
      const changed = await request<Candidate>(`/live/auto/candidates/${item.id}/${action === 'discard' ? 'discard' : 'keep'}`,
        { method: 'POST' });
      sequence.current++;
      setRows(previous => previous.map(row => row.id === changed.id ? changed : row));
      if (changed.video) {
        onKeep(changed.video);
        if (action === 'edit') onEdit(changed.video, templateFor(streamKey(changed))?.options);
      }
    } catch (cause) {
      setMessage((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const enabled = status?.options.enabled ?? false;
  const modelReady = status?.models.some(model => model.id === 'tiny' && model.installed);
  const streamers = [...new Set(rows.map(streamKey))].sort();
  const valid = draft && draft.before + draft.after <= draft.duration;
  const canEnable = status?.vad && status.whisper && modelReady && valid;
  const edit = <K extends keyof Options>(key: K, value: Options[K]) =>
    setDraft(previous => previous ? { ...previous, [key]: value } : previous);

  return <section className="panel live-auto" aria-labelledby="live-auto-heading">
    <div className="panel-heading">
      <div><Sparkles size={18}/><h2 id="live-auto-heading">AutoClipping IA{streamer ? ` · ${streamer.name ?? streamer.channel}` : ''}</h2></div>
      {streamer && <button type="button" className="secondary" aria-pressed={enabled} disabled={busy || !draft || (!enabled && !canEnable)}
        onClick={() => draft && void (enabled ? configure({ enabled: false }, true) : configure({ ...draft, enabled: true }))}>
        {enabled ? 'Desactivar modo automático' : 'Activar modo automático'}
      </button>}
    </div>
    <div className="live-body">
      {status?.candidate_limit_gb !== undefined && <label className="live-capture-limit">Límite de almacenamiento de candidatos
        <select value={status.candidate_limit_gb} disabled={busy}
          onChange={event => void configureStorage(Number(event.target.value) as CandidateLimit)}>
          {candidateLimits.map(limit => <option key={limit} value={limit}>{limit} GB</option>)}
        </select>
      </label>}
      {streamer && <><div className="live-status-row"><span role="status">{status ? states[status.stage] : 'Consultando AutoClipping…'}</span>
        {status && <span>{status.detected} detecciones · {status.filtered} filtradas · {status.skipped} omitidas</span>}
        {status && <span>{sizeLabel(status.bytes)} / {status.candidate_limit_gb ? `${status.candidate_limit_gb} GB` : sizeLabel(status.max_bytes)} en revisión</span>}
      </div>
      {splitTemplates.length > 0 && <label className="split-template-choice">Plantilla para editar candidatos
        <span>{platformLabel(streamer.platform)} · {streamer.name ?? streamer.channel}</span>
        <select value={selectedTemplate?.id ?? ''} disabled={busy} onChange={event => void bindTemplate(event.target.value)}>
          <option value="">Usar los ajustes del editor</option>
          {splitTemplates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
        </select>
      </label>}
      {status?.message && <p className="live-note" role="status">{status.message}</p>}
      {status?.diagnostics && <details className="live-note">
        <summary>Diagnóstico del canal</summary>
        <p>{status.diagnostics.audio_segments} segmentos con audio · {status.diagnostics.audio_failures} errores de audio ·
          {' '}{status.diagnostics.transcriptions} transcripciones · {status.diagnostics.generated} candidatos guardados ·
          {' '}{status.diagnostics.deferred} señales en espera</p>
        <p>Última puntuación {status.diagnostics.last_score ?? '—'} · Mejor {status.diagnostics.best_score ?? '—'} ·
          {' '}Mínimo {status.options.minimum_score}{status.available_bytes !== undefined &&
            ` · ${sizeLabel(status.available_bytes)} disponibles en la cuota de candidatos`}</p>
        {status.diagnostics.last_error && <p className="live-error">Último error. {status.diagnostics.last_error}</p>}
        {[
          ['Motivos de omisión', status.diagnostics.omissions],
          ['Motivos de filtrado', status.diagnostics.filters],
        ].map(([label, reasons]) => typeof reasons !== 'string' && Object.keys(reasons).length > 0 &&
          <div key={String(label)}><strong>{String(label)}</strong>
            <ul>{Object.entries(reasons).map(([code, count]) =>
              <li key={code}>{diagnosticLabels[code] ?? code} · {count}</li>)}</ul>
          </div>)}
      </details>}
      {status && (!status.vad || !status.whisper || !modelReady) && <p className="live-note">
        {status.vad ? 'Instala Whisper Tiny desde Momentos con IA.' : 'Instala backend/requirements-autoclip.txt para detectar actividad de voz.'}
      </p>}
      {draft && <form onSubmit={event => {
        event.preventDefault();
        const { enabled: _enabled, ...preferences } = draft;
        void configure(preferences);
      }}>
        <fieldset className="live-auto-fields" disabled={busy}>
          <label>Modo de detección<select value={draft.detection_mode} aria-describedby="live-auto-mode-description"
            onChange={event => edit('detection_mode', event.target.value as DetectionMode)}>
            {Object.entries(modes).map(([id, mode]) => <option key={id} value={id}>{mode.label}</option>)}
          </select></label>
          <label>Sensibilidad<select value={draft.sensitivity} onChange={event => edit('sensitivity', event.target.value as Options['sensitivity'])}>
            <option value="low">Baja</option><option value="balanced">Equilibrada</option><option value="high">Alta</option>
          </select></label>
          <span>Modelo para AutoClipping · Whisper Tiny</span>
          <label>Duración automática<select value={draft.duration} onChange={event => edit('duration', Number(event.target.value) as Options['duration'])}>
            {[30, 60, 90].map(value => <option key={value} value={value}>{value} s</option>)}
          </select></label>
          {([
            ['minimum_score', 'Puntuación mínima', 0, 100],
            ['before', 'Segundos anteriores', 0, 80],
            ['after', 'Segundos posteriores', 0, 30],
            ['per_hour', 'Máximo de clips por hora', 1, 20],
            ['interval', 'Intervalo mínimo (s)', 5, 600],
          ] as const).map(([key, label, min, max]) => <label key={key}>{label}<NumericInput min={min} max={max}
            value={draft[key]} onCommit={value => edit(key, value)}/></label>)}
          <button type="submit" className="secondary" disabled={!valid}>Guardar ajustes automáticos</button>
        </fieldset>
        <p className="live-note" id="live-auto-mode-description">{modes[draft.detection_mode ?? 'mixed'].hint}</p>
        {!valid && <p className="live-error">La suma de los segundos anteriores y posteriores debe caber en el clip.</p>}
      </form>}</>}
      {(message || pollError) && <p className="live-error" role="alert">{message || pollError}</p>}
      <h3>Historial de candidatos</h3>
      {streamers.length > 0 && <label>Filtrar candidatos por streamer <select value={streamerFilter}
        onChange={event => setStreamerFilter(event.target.value)}><option value="">Todos</option>
        {streamers.map(key => {
          const item = rows.find(row => streamKey(row) === key);
          return <option key={key} value={key}>{item?.channel_name ? `${platformLabel(item.platform)} · ${item.channel_name}` : key}</option>;
        })}
      </select></label>}
      {!rows.length && <p className="live-note">Todavía no hay candidatos guardados.</p>}
      <ul className="live-auto-history">
        {rows.filter(item => !streamerFilter || streamKey(item) === streamerFilter).map(item => {
          const src = item.preview_url ?? item.video?.preview_url;
          const thumb = item.thumbnail_url ?? item.video?.thumbnail_url;
          return <li key={item.id}>
            <div className="live-auto-row">
              {thumb ? <img src={thumb} alt=""/> : <div className="live-auto-thumb"><Clapperboard size={24}/></div>}
              <div className="live-capture-info">
                <h4>{item.title}</h4>
                <p><strong>{item.score}/100</strong> · {seconds(item.duration)} · {platformLabel(item.platform)} · {item.channel_name ?? item.channel}</p>
                <p><time dateTime={item.created_at}>{date.format(new Date(item.created_at))}</time> · {
                  item.status === 'pending' ? 'Pendiente' : item.status === 'kept' ? 'Conservado' : 'Descartado'}</p>
                <p>{item.reason}</p>
                {!item.detection_mode && <p>Puntuación anterior al cambio de detección.</p>}
                {item.detection_type && item.metrics && <details><summary>Señales de la puntuación</summary>
                  <p>{item.detection_type === 'reaction' ? 'Reacción vocal' : modes[item.detection_type]?.label ?? 'Modo anterior'}.
                    {item.detection_type !== 'irl' && ' La intensidad aporta hasta 4 puntos.'}</p>
                  <ul>{Object.entries(item.metrics).filter(([key]) => key in metricLabels).map(([key, value]) =>
                    <li key={key}>{metricLabels[key]} · {value}%</li>)}</ul>
                </details>}
                {item.excerpt && <details><summary>Contexto transcrito</summary><p>{item.excerpt}</p></details>}
              </div>
              <div className="live-capture-actions">
                {src && <button className="secondary" aria-expanded={preview === item.id}
                  onClick={() => setPreview(preview === item.id ? null : item.id)}>{preview === item.id ? 'Cerrar reproducción' : 'Reproducir'}</button>}
                {(item.status === 'pending' || item.video) && <button className="secondary" disabled={busy}
                  onClick={() => void review(item, 'edit')}>Editar</button>}
                {item.status === 'pending' && <>
                  <button className="secondary" disabled={busy} onClick={() => void review(item, 'keep')}>Conservar</button>
                  <button className="secondary" disabled={busy} onClick={() => void review(item, 'discard')}>Descartar</button>
                </>}
              </div>
            </div>
            {preview === item.id && src && <video className="live-auto-preview" src={src} controls autoPlay playsInline/>}
          </li>;
        })}
      </ul>
    </div>
  </section>;
}
