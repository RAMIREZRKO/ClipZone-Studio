import { useCallback, useEffect, useRef, useState } from 'react';
import { Clapperboard, Sparkles } from 'lucide-react';
import { request, seconds, sizeLabel, type CampaignTemplate, type RenderOptions, type Video } from '../api';
import { platformLabel } from './DirectLive';
import { NumericInput } from './NumericInput';

interface Options {
  enabled: boolean;
  model: 'tiny' | 'base' | 'small';
  duration: 30 | 60 | 90;
  sensitivity: 'low' | 'balanced' | 'high';
  minimum_score: number;
  before: number;
  after: number;
  per_hour: number;
  interval: number;
}
interface Status {
  options: Options;
  stage: string;
  message: string | null;
  detected: number;
  filtered: number;
  skipped: number;
  bytes: number;
  max_bytes: number;
  vad: boolean;
  whisper: boolean;
  models: { id: string; installed: boolean }[];
}
interface Candidate {
  id: string;
  title: string;
  duration: number;
  score: number;
  reason: string;
  excerpt: string;
  created_at: string;
  platform: string;
  channel: string;
  status: 'pending' | 'kept' | 'discarded';
  preview_url: string | null;
  thumbnail_url: string | null;
  video: Video | null;
}
const states: Record<string, string> = {
  disabled: 'Modo automático desactivado', waiting: 'Esperando captura directa',
  listening: 'Analizando señales del audio', collecting: 'Esperando segundos posteriores al evento',
  transcribing: 'Transcribiendo candidato con Whisper', saving: 'Guardando candidato',
  skipped: 'Candidato omitido', error: 'Error de AutoClipping',
};
const date = new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' });

export function AutoClipping({ active, directMethod, onKeep, onEdit }: {
  active: boolean;
  directMethod: boolean;
  onKeep: (video: Video) => void;
  onEdit: (video: Video, options?: RenderOptions) => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState<Options | null>(null);
  const [rows, setRows] = useState<Candidate[]>([]);
  const [message, setMessage] = useState('');
  const [pollError, setPollError] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [splitTemplates, setSplitTemplates] = useState<CampaignTemplate[]>([]);
  const [templateId, setTemplateId] = useState('');
  const selectedTemplate = splitTemplates.find(template => template.id === templateId);
  const sequence = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const current = ++sequence.current;
    try {
      const [next, candidates] = await Promise.all([
        request<Status>('/live/auto/status', { signal }),
        request<Candidate[]>('/live/auto/candidates', { signal }),
      ]);
      if (signal?.aborted || current !== sequence.current) return;
      setStatus(next);
      setDraft(previous => previous ?? next.options);
      setRows(candidates);
      setPollError('');
    } catch (cause) {
      if (!signal?.aborted && current === sequence.current) setPollError((cause as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!active) {
      setPreview(null);
      return;
    }
    const controller = new AbortController();
    request<CampaignTemplate[]>('/templates', { signal: controller.signal }).then(templates => {
      setSplitTemplates(templates.filter(template => template.options.fit === 'split'));
    }).catch(() => {
      if (!controller.signal.aborted) setSplitTemplates([]);
    });
    const update = () => { if (!document.hidden) void refresh(controller.signal); };
    update();
    const timer = window.setInterval(update, 2500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [active, refresh]);

  async function configure(options: Options) {
    setBusy(true);
    setMessage('');
    try {
      const next = await request<Status>('/live/auto/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options),
      });
      sequence.current++;
      setStatus(next);
      setDraft(next.options);
    } catch (cause) {
      setMessage((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function review(item: Candidate, action: 'keep' | 'discard' | 'edit') {
    if (action === 'edit' && item.video) {
      onEdit(item.video, selectedTemplate?.options);
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
        if (action === 'edit') onEdit(changed.video, selectedTemplate?.options);
      }
    } catch (cause) {
      setMessage((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const enabled = status?.options.enabled ?? false;
  const modelReady = status?.models.some(model => model.id === draft?.model && model.installed);
  const valid = draft && draft.before + draft.after <= draft.duration;
  const canEnable = directMethod && status?.vad && status.whisper && modelReady && valid;
  const edit = <K extends keyof Options>(key: K, value: Options[K]) =>
    setDraft(previous => previous ? { ...previous, [key]: value } : previous);

  return <section className="panel live-auto" aria-labelledby="live-auto-heading">
    <div className="panel-heading">
      <div><Sparkles size={18}/><h2 id="live-auto-heading">AutoClipping IA</h2></div>
      <button type="button" className="secondary" aria-pressed={enabled} disabled={busy || !draft || (!enabled && !canEnable)}
        onClick={() => draft && void configure(enabled && status ? { ...status.options, enabled: false } : { ...draft, enabled: true })}>
        {enabled ? 'Desactivar modo automático' : 'Activar modo automático'}
      </button>
    </div>
    <div className="live-body">
      <div className="live-status-row"><span role="status">{status ? states[status.stage] : 'Consultando AutoClipping…'}</span>
        {status && <span>{status.detected} detecciones · {status.filtered} filtradas · {status.skipped} omitidas</span>}
        {status && <span>{sizeLabel(status.bytes)} / {sizeLabel(status.max_bytes)} en revisión</span>}
      </div>
      <p className="live-note">Activa el análisis en fuentes autorizadas de Captura directa. Los candidatos reciben una estimación editorial de 0 a 100.</p>
      {splitTemplates.length > 0 && <label className="split-template-choice">Plantilla para editar candidatos
        <select value={selectedTemplate?.id ?? ''} onChange={event => setTemplateId(event.target.value)}>
          <option value="">Usar los ajustes del editor</option>
          {splitTemplates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
        </select>
      </label>}
      {status?.message && <p className="live-note" role="status">{status.message}</p>}
      {(message || pollError) && <p className="live-error" role="alert">{message || pollError}</p>}
      {status && (!status.vad || !status.whisper || !modelReady) && <p className="live-note">
        {status.vad ? 'Instala Whisper y el modelo elegido desde Momentos con IA.' : 'Instala backend/requirements-autoclip.txt para detectar actividad de voz.'}
      </p>}
      {draft && <form onSubmit={event => { event.preventDefault(); void configure({ ...draft, enabled }); }}>
        <fieldset className="live-auto-fields" disabled={busy}>
          <label>Sensibilidad<select value={draft.sensitivity} onChange={event => edit('sensitivity', event.target.value as Options['sensitivity'])}>
            <option value="low">Baja</option><option value="balanced">Equilibrada</option><option value="high">Alta</option>
          </select></label>
          <label>Modelo para AutoClipping<select value={draft.model} onChange={event => edit('model', event.target.value as Options['model'])}>
            {(['tiny', 'base', 'small'] as const).map(model => <option key={model}
              value={model}>{model[0].toUpperCase() + model.slice(1)}{status?.models.some(item => item.id === model && item.installed) ? '' : ' · pendiente de instalar'}</option>)}
          </select></label>
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
          <button type="submit" className="secondary" disabled={!valid || (enabled && !modelReady)}>Guardar ajustes automáticos</button>
        </fieldset>
        {!valid && <p className="live-error">La suma de los segundos anteriores y posteriores debe caber en el clip.</p>}
      </form>}
      <h3>Historial de candidatos</h3>
      {!rows.length && <p className="live-note">Todavía no hay candidatos guardados.</p>}
      <ul className="live-auto-history">
        {rows.map(item => {
          const src = item.preview_url ?? item.video?.preview_url;
          const thumb = item.thumbnail_url ?? item.video?.thumbnail_url;
          return <li key={item.id}>
            <div className="live-auto-row">
              {thumb ? <img src={thumb} alt=""/> : <div className="live-auto-thumb"><Clapperboard size={24}/></div>}
              <div className="live-capture-info">
                <h4>{item.title}</h4>
                <p><strong>{item.score}/100</strong> · {seconds(item.duration)} · {platformLabel(item.platform)} · {item.channel}</p>
                <p><time dateTime={item.created_at}>{date.format(new Date(item.created_at))}</time> · {
                  item.status === 'pending' ? 'Pendiente' : item.status === 'kept' ? 'Conservado' : 'Descartado'}</p>
                <p>{item.reason}</p>
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
