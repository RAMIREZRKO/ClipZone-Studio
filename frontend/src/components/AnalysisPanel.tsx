import { useEffect, useState } from 'react';
import { ArrowDownToLine, CheckCheck, CircleHelp, FileText, LoaderCircle, Play, Sparkles, WandSparkles, X } from 'lucide-react';
import { request, seconds, type AICapabilities, type Analysis, type AnalysisOptions, type AnalysisResult, type Job, type Moment, type RenderOptions, type Video } from '../api';
import { presets } from '../presets';

interface Props {
  video: Video | null;
  output: RenderOptions;
  onChoose: (moment: Moment) => void;
  onExported: (jobs: Job[]) => void;
}

export function AnalysisPanel({ video, output, onChoose, onExported }: Props) {
  const [capabilities, setCapabilities] = useState<AICapabilities | null>(null);
  const [options, setOptions] = useState<AnalysisOptions>({ model: 'tiny', language: 'es', min_duration: 15, max_duration: 45, max_clips: 8, reuse_transcript: true });
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [analysisId, setAnalysisId] = useState('');
  const [result, setResult] = useState<{ id: string; data: AnalysisResult } | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const active = analyses.find(a => a.id === analysisId);
  const running = analyses.find(a => a.status === 'running' || a.status === 'queued');
  const data = result?.id === analysisId ? result.data : null;
  const installed = capabilities?.models.some(m => m.id === options.model && m.installed);
  const ready = capabilities && Object.values(capabilities.dependencies).every(Boolean) && installed;

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const caps = await request<AICapabilities>('/ai/capabilities');
        if (alive) setCapabilities(caps);
      } catch { /* El estado del motor se muestra en la barra superior. */ }
    };
    void poll();
    const timer = window.setInterval(poll, 6000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    setAnalyses([]); setAnalysisId(''); setResult(null); setChecked(new Set()); setError('');
    if (!video) return;
    let alive = true;
    const poll = async () => {
      try {
        const list = await request<Analysis[]>(`/videos/${video.id}/analyses`);
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
    if (!active || !checked.size || generating) return;
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
        <label>Modelo<select aria-label="Modelo Whisper" value={options.model} onChange={e => setOptions({ ...options, model: e.target.value })}>
          {(capabilities?.models || [{ id: 'tiny', label: 'Tiny', size_mb: 76, installed: false }]).map(m => <option key={m.id} value={m.id}>{m.label} · {m.installed ? 'instalado' : `${m.size_mb} MB, sin instalar`}</option>)}
        </select></label>
        <label>Idioma del audio<select aria-label="Idioma del audio" value={options.language} onChange={e => setOptions({ ...options, language: e.target.value })}>
          <option value="auto">Detectar automáticamente</option><option value="es">Español</option><option value="en">Inglés</option><option value="pt">Portugués</option><option value="fr">Francés</option><option value="de">Alemán</option><option value="it">Italiano</option>
        </select></label>
        <div className="analysis-duration"><label>Mínimo (s)<input aria-label="Duración mínima IA" type="number" min={1} max={180} step={1} value={options.min_duration} onChange={e => setOptions({ ...options, min_duration: +e.target.value })}/></label><label>Máximo (s)<input aria-label="Duración máxima IA" type="number" min={1} max={180} step={1} value={options.max_duration} onChange={e => setOptions({ ...options, max_duration: +e.target.value })}/></label></div>
        <label>Máximo de propuestas<input aria-label="Máximo de propuestas" type="number" min={1} max={20} value={options.max_clips} onChange={e => setOptions({ ...options, max_clips: +e.target.value })}/></label>
        <label className="analysis-checkbox"><input type="checkbox" checked={options.reuse_transcript} onChange={e => setOptions({ ...options, reuse_transcript: e.target.checked })}/>Reutilizar transcripción si ya existe</label>
        {!ready && capabilities && <div className="ai-setup"><CircleHelp size={16}/><div><strong>Prepara la IA en este equipo</strong><p>Instala Whisper y un modelo gratuito una sola vez. Después podrás analizar sin conexión.</p><code>{`powershell -ExecutionPolicy Bypass -File .\scripts\setup-ai.ps1 -Model ${options.model}`}</code></div></div>}
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
          <p className="score-explanation">Puntuación editorial de 0 a 100: gancho, continuidad, cierre y actividad de voz. Revisa el contexto antes de compartir.</p>
          {data.moments.length ? <div className="moments-grid">{data.moments.map((moment, index) => <article className={`moment-card ${checked.has(moment.id) ? 'is-checked' : ''}`} key={moment.id}>
            <div className="moment-top"><label><input type="checkbox" aria-label={`Seleccionar momento ${index + 1}`} checked={checked.has(moment.id)} onChange={() => toggle(moment.id)}/>MOMENTO {String(index + 1).padStart(2, '0')}</label><span className="moment-score" title="Puntuación editorial"><strong>{moment.score}</strong>/100</span></div>
            <h4>{moment.title}</h4><p className="moment-excerpt">{moment.text}</p><p className="moment-reason"><Sparkles size={12}/>{moment.reason}</p>
            <div className="moment-bottom"><span>{seconds(moment.start)} → {seconds(moment.end)}<small>{(moment.end - moment.start).toFixed(1)} s</small></span><button className="secondary" onClick={() => onChoose(moment)}><Play size={13}/>Revisar en editor</button></div>
          </article>)}</div> : <div className="analysis-empty"><FileText size={28}/><h3>{data.transcript.words.length ? 'No hay fragmentos con esta duración' : 'No se detectó habla suficiente'}</h3><p>{data.transcript.words.length ? 'Prueba una duración mínima menor y reutiliza la transcripción.' : 'Prueba un vídeo con voz clara o un modelo de mayor precisión.'}</p></div>}
          <details className="transcript"><summary><FileText size={15}/>Ver transcripción completa</summary><div>{data.transcript.words.map((word, i) => <button key={i} title={seconds(word.start)} onClick={() => onChoose({ id: '', start: word.start, end: Math.min(video?.duration || word.end, Math.max(word.end, word.start + .2)), title: word.text, text: word.text, score: 0, reason: '', metrics: { speech: 0, hook: 0, closure: 0, energy: 0 } })}>{word.text}{' '}</button>)}</div></details>
          {data.moments.length > 0 && <div className="batch-toolbar"><div><strong>{checked.size} seleccionados</strong><span>{presets[output.platform].label} · {output.ratio} · {output.resolution}p · encuadre del editor</span></div><button className="primary" disabled={!checked.size || generating} onClick={() => void generate()}>{generating ? <LoaderCircle className="spin" size={16}/> : <ArrowDownToLine size={16}/>}Generar seleccionados</button></div>}
        </>}
        {!active && <div className="analysis-empty"><WandSparkles size={33}/><h3>Deja que el contenido marque el corte.</h3><p>Elige una duración y analiza tu vídeo.<br/>Aquí aparecerán propuestas puntuadas para seleccionar y generar.</p></div>}
      </div>
    </div>
  </section>;
}
