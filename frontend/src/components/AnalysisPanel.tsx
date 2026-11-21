import { useEffect, useState } from 'react';
import { ArrowDownToLine, CheckCheck, CircleHelp, FileText, LoaderCircle, Play, Sparkles, WandSparkles, X } from 'lucide-react';
import { request, seconds, type AICapabilities, type Analysis, type AnalysisOptions, type AnalysisResult, type Job, type Moment, type RenderOptions, type Video } from '../api';
import { presets } from '../presets';
import { bytes } from './StoragePanel';
import { NumericInput } from './NumericInput';

interface Props {
  video: Video | null;
  output: RenderOptions;
  onChoose: (moment: Moment) => void;
  onExported: (jobs: Job[]) => void;
  renderBlocked?: boolean;
}

export function AnalysisPanel({ video, output, onChoose, onExported, renderBlocked }: Props) {
  const [capabilities, setCapabilities] = useState<AICapabilities | null>(null);
  const [options, setOptions] = useState<AnalysisOptions>({
    model: 'base', language: 'auto', min_duration: 15, max_duration: 45,
    max_clips: 8, reuse_transcript: true, cpu_threads: 4,
  });
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [analysisId, setAnalysisId] = useState('');
  const [result, setResult] = useState<{ id: string; data: AnalysisResult } | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [modelAction, setModelAction] = useState(false);
  const [modelError, setModelError] = useState('');
  const active = analyses.find(a => a.id === analysisId);
  const running = analyses.find(a => a.status === 'running' || a.status === 'queued');
  const data = result?.id === analysisId ? result.data : null;
  const selectedModel = capabilities?.models.find(model => model.id === options.model);
  const engineReady = !!capabilities && Object.values(capabilities.dependencies).every(Boolean);
  const ready = engineReady && selectedModel?.installed;
  const download = capabilities?.downloads[options.model];
  const downloading = Object.entries(capabilities?.downloads ?? {})
    .find(([, state]) => state.status === 'downloading' || state.status === 'cancelling');

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const caps = await request<AICapabilities>('/ai/capabilities');
        if (alive) setCapabilities(caps);
      } catch { /* El estado del motor se muestra en la barra superior. */ }
    };
    void poll();
    const timer = window.setInterval(poll, 1500);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  async function modelRequest(action: 'download' | 'cancel', model: string) {
    setModelAction(true);
    setModelError('');
    try {
      await request(`/ai/models/${model}/${action}`, { method: 'POST' });
      setCapabilities(await request<AICapabilities>('/ai/capabilities'));
    } catch (e) {
      setModelError((e as Error).message);
    } finally {
      setModelAction(false);
    }
  }

  useEffect(() => {
    setAnalyses([]); setAnalysisId(''); setResult(null); setChecked(new Set()); setError('');
    if (!video) return;
    let alive = true;
    const poll = async () => {
      try {
        const list = (await request<Analysis[]>(`/videos/${video.id}/analyses`)).filter(item => !item.options.transcript_window);
        if (alive) {
          setAnalyses(list);
          setAnalysisId(previous => list.some(a => a.id === previous) ? previous : list[0]?.id || '');
        }
      } catch (e) { if (alive) setError((e as Error).message); }
    };
    void poll();
    const timer = window.setInterval(poll, 1500);
    return () => { alive = false; window.clearInterval(timer); };
  }, [video?.id]);

  useEffect(() => { setChecked(new Set()); }, [analysisId]);
  useEffect(() => { if (active) setOptions({ ...active.options }); }, [active?.id]);
  useEffect(() => {
    if (!active || active.status !== 'completed') return;
    let alive = true;
    request<AnalysisResult>(`/analyses/${active.id}/result`).then(data => {
      if (alive) setResult({ id: active.id, data });
    }).catch(e => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [active?.id, active?.status]);

  function editOption<Key extends keyof AnalysisOptions>(key: Key, value: AnalysisOptions[Key]) {
    setOptions(previous => ({ ...previous, [key]: value }));
  }

  async function analyze() {
    if (!video || !ready || running || busy) return;
    setError('');
    if (options.min_duration > options.max_duration || options.min_duration > video.duration) {
      setError('Revisa las duraciones: la mínima debe caber en el vídeo y no superar la máxima.'); return;
    }
    setBusy(true);
    try {
      const job = await request<Analysis>(`/videos/${video.id}/analyses`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options),
      });
      setAnalyses(list => [job, ...list]); setAnalysisId(job.id);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function cancel() {
    if (!running) return;
    try {
      const item = await request<Analysis>(`/analyses/${running.id}/cancel`, { method: 'POST' });
      setAnalyses(list => list.map(a => a.id === item.id ? item : a));
    } catch (e) { setError((e as Error).message); }
  }

  async function generate() {
    if (!active || !checked.size || generating || renderBlocked) return;
    setGenerating(true); setError('');
    try {
      const response = await request<{ jobs: Job[] }>('/clips/batch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...output, analysis_id: active.id, moment_ids: [...checked] }),
      });
      setChecked(new Set()); onExported(response.jobs);
    } catch (e) { setError((e as Error).message); }
    finally { setGenerating(false); }
  }

  function toggle(id: string) {
    setChecked(previous => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }

  return <section className="analysis-panel panel" id="ai-moments" aria-label="Momentos con IA">
    <div className="panel-heading"><div><WandSparkles size={18}/><h2>Momentos con IA</h2><span className="small-tag">WHISPER LOCAL</span></div><span className="analysis-private">Sin subir tu audio</span></div>
    <div className="analysis-layout">
      <div className="analysis-controls">
        <h3>Encuentra lo que merece un clip.</h3>
        <p>Transcribe el vídeo y descubre fragmentos para revisar y compartir.</p>
        <label>Modelo<select aria-label="Modelo Whisper" value={options.model} onChange={e => editOption('model', e.target.value)}>
          {!capabilities && <option value={options.model}>Comprobando modelos…</option>}
          {capabilities?.models.map(m => <option key={m.id} value={m.id}>{m.label.split(' · ')[0]} · {m.installed ? 'instalado' : m.integrity === 'invalid' ? 'archivo dañado' : m.integrity === 'unreadable' ? 'no se puede leer' : 'sin instalar'}</option>)}
        </select></label>
        {selectedModel && <span className="field-note model-description">{selectedModel.label.split(' · ')[1]}</span>}
        {selectedModel && !selectedModel.installed && <button className="secondary model-install" disabled={modelAction || !!downloading}
          onClick={() => void modelRequest('download', selectedModel.id)}>Instalar {selectedModel.label.split(' · ')[0]} · {selectedModel.size_mb} MB</button>}
        {downloading && <div className="model-progress" role="status">
          <strong>{downloading[1].status === 'cancelling' ? 'Cancelando' : 'Descargando'} {downloading[0]}</strong>
          <span>{bytes(downloading[1].received)}{downloading[1].total ? ` / ${bytes(downloading[1].total)}` : ' recibidos'}</span>
          <progress max={100} value={downloading[1].total ? Math.min(100, downloading[1].received / downloading[1].total * 100) : undefined}
            aria-label="Progreso de descarga del modelo"/>
          <button className="secondary" disabled={modelAction || downloading[1].status === 'cancelling'}
            onClick={() => void modelRequest('cancel', downloading[0])}>Cancelar descarga</button>
        </div>}
        {(modelError || download?.error) && <p className="analysis-warning" role="alert">{modelError || download?.error}</p>}
        {download?.status === 'failed' && <p className="field-note">Registro local en <code>data/whisper-downloads.log</code>.</p>}
        {download?.status === 'cancelled' && <p className="field-note">Descarga cancelada.</p>}
        <label>Procesamiento en CPU<select aria-label="Hilos de Whisper" value={options.cpu_threads ?? 4}
          onChange={event => editOption('cpu_threads', Number(event.target.value))}>
          <option value={2}>2 hilos · menor carga</option><option value={4}>4 hilos · recomendado</option><option value={6}>6 hilos · más CPU</option>
        </select></label>
        <label>Idioma del audio<select aria-label="Idioma del audio" value={options.language} onChange={e => editOption('language', e.target.value)}>
          <option value="auto">Detectar automáticamente</option><option value="es">Español</option><option value="en">Inglés</option><option value="pt">Portugués</option><option value="fr">Francés</option><option value="de">Alemán</option><option value="it">Italiano</option>
        </select></label>
        {data && <p className="field-note">
          {active?.options.language === 'auto' ? 'Idioma detectado del audio' : 'Idioma del audio (selección manual)'}: {data.transcript.language === 'auto' ? 'Indeterminado' : data.transcript.language.toUpperCase()}.
        </p>}
        <div className="analysis-duration"><label>Mínimo (s)<NumericInput aria-label="Duración mínima IA" min={1} max={180} precision={2} step={1}
          value={options.min_duration} onCommit={value => editOption('min_duration', value)}/></label>
          <label>Máximo (s)<NumericInput aria-label="Duración máxima IA" min={1} max={180} precision={2} step={1}
            value={options.max_duration} onCommit={value => editOption('max_duration', value)}/></label></div>
        <label>Máximo de propuestas<NumericInput aria-label="Máximo de propuestas" min={1} max={20}
          value={options.max_clips} onCommit={value => editOption('max_clips', value)}/></label>
        <label className="analysis-checkbox"><input type="checkbox" checked={options.reuse_transcript} onChange={e => editOption('reuse_transcript', e.target.checked)}/>Reutilizar transcripción si ya existe</label>
        {!engineReady && capabilities && <div className="ai-setup"><CircleHelp size={16}/><div><strong>Instala el motor local de Whisper</strong><p>Ejecuta este comando en PowerShell desde la carpeta del proyecto.</p><code>{capabilities.install_command}</code></div></div>}
        {video && !video.has_audio && <p className="analysis-warning">Este vídeo no tiene pista de audio.</p>}
        <button className="primary" disabled={!video || !video.has_audio || !ready || !!running || busy} onClick={() => void analyze()}>{busy ? <LoaderCircle className="spin" size={16}/> : <Sparkles size={16}/>}Analizar vídeo</button>
        {!video && <span className="field-note">Importa y selecciona un vídeo para empezar.</span>}
      </div>
      <div className="analysis-results">
        {error && <div className="alert error" role="alert"><CircleHelp size={16}/><span>{error}</span><button onClick={() => setError('')} aria-label="Cerrar error de IA"><X size={15}/></button></div>}
        {analyses.length > 0 && <div className="analysis-history"><label htmlFor="analysis-history">Análisis guardados</label><select id="analysis-history" value={analysisId} onChange={e => setAnalysisId(e.target.value)}>{analyses.map((a, i) => <option key={a.id} value={a.id}>{i === 0 ? 'Último' : `Anterior ${i}`} · {a.options.model} · {a.options.min_duration}–{a.options.max_duration} s · {a.status === 'completed' ? 'listo' : a.stage.toLowerCase()}</option>)}</select></div>}
        {active && (active.status === 'queued' || active.status === 'running') && <div className="analysis-progress" role="status"><LoaderCircle className="spin" size={22}/><div><strong>{active.stage}</strong><p>Puedes seguir recortando mientras Whisper trabaja en tu equipo.</p><div className="progress-track"><div style={{ width: `${active.progress}%` }}/></div></div><span>{active.progress}%</span><button className="secondary" onClick={() => void cancel()}><X size={13}/>Cancelar análisis</button></div>}
        {active?.status === 'failed' && <div className="alert error" role="alert"><CircleHelp size={16}/><span>{active.error}</span></div>}
        {active?.status === 'cancelled' && <p className="analysis-warning">Análisis cancelado. Puedes iniciarlo de nuevo.</p>}
        {data && <>
          <div className="moments-toolbar"><div><h3>{data.moments.length} momentos propuestos</h3><span>{data.transcript.words.length} palabras · {data.transcript.language.toUpperCase()}{active?.reused_transcript ? ' · transcripción reutilizada' : ''}</span></div>{data.moments.length > 0 && <button className="secondary" onClick={() => setChecked(checked.size === data.moments.length ? new Set() : new Set(data.moments.map(m => m.id)))}><CheckCheck size={14}/>{checked.size === data.moments.length ? 'Desmarcar todos' : 'Seleccionar todos'}</button>}</div>
          {active?.elapsed_seconds !== undefined && <p className="field-note">
            {active.options.model} · CPU ({active.options.cpu_threads ?? 4} hilos) · {active.elapsed_seconds.toFixed(1)} s
            {active.reused_transcript ? ' para volver a puntuar' : ' de análisis'}
          </p>}
          <p className="score-explanation">Estimación editorial de 0 a 100 basada en gancho, continuidad, cierre y actividad de voz. Revisa el contexto antes de compartir.</p>
          {data.moments.length ? <div className="moments-grid">{data.moments.map((moment, index) => <article className={`moment-card ${checked.has(moment.id) ? 'is-checked' : ''}`} key={moment.id}>
            <div className="moment-top"><label><input type="checkbox" aria-label={`Seleccionar momento ${index + 1}`} checked={checked.has(moment.id)} onChange={() => toggle(moment.id)}/>MOMENTO {String(index + 1).padStart(2, '0')}</label><span className="moment-score" title="Puntuación editorial"><strong>{moment.score}</strong>/100</span></div>
            <h4>{moment.title}</h4><p className="moment-excerpt">{moment.text}</p><p className="moment-reason"><Sparkles size={12}/>{moment.reason}</p>
            <div className="moment-bottom"><span>{seconds(moment.start)} → {seconds(moment.end)}<small>{(moment.end - moment.start).toFixed(1)} s</small></span><button className="secondary" onClick={() => onChoose(moment)}><Play size={13}/>Revisar en editor</button></div>
          </article>)}</div> : <div className="analysis-empty"><FileText size={28}/><h3>{data.transcript.words.length ? 'No hay fragmentos con esta duración' : 'No se detectó habla suficiente'}</h3><p>{data.transcript.words.length ? 'Prueba una duración mínima menor y reutiliza la transcripción.' : 'Prueba un vídeo con voz clara o un modelo de mayor precisión.'}</p></div>}
          <details className="transcript"><summary><FileText size={15}/>Ver transcripción completa</summary><div>{data.transcript.words.map((word, i) => <button key={i} title={seconds(word.start)} onClick={() => onChoose({ id: '', start: word.start, end: Math.min(video?.duration || word.end, Math.max(word.end, word.start + .2)), title: word.text, text: word.text, score: 0, reason: '', metrics: { speech: 0, hook: 0, closure: 0, energy: 0 } })}>{word.text}{' '}</button>)}</div></details>
          {data.moments.length > 0 && <div className="batch-toolbar"><div><strong>{checked.size} seleccionados</strong><span>{presets[output.platform].label} · {output.ratio} · {output.resolution}p · encuadre del editor</span>{renderBlocked && <p className="field-note">Guarda los subtítulos antes de generar clips.</p>}</div><button className="primary" disabled={!checked.size || generating || renderBlocked} onClick={() => void generate()}>{generating ? <LoaderCircle className="spin" size={16}/> : <ArrowDownToLine size={16}/>}Generar seleccionados</button></div>}
        </>}
        {!active && <div className="analysis-empty"><WandSparkles size={33}/><h3>Deja que el contenido marque el corte.</h3><p>Elige una duración y analiza tu vídeo.<br/>Aquí aparecerán propuestas puntuadas para seleccionar y generar.</p></div>}
      </div>
    </div>
  </section>;
}
