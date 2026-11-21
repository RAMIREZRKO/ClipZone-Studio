import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';
import { Captions, Plus, Save } from 'lucide-react';
import { request, seconds, type Analysis, type CaptionSegment, type CaptionStyle, type CaptionTrack, type Video } from '../api';
import { CaptionAppearance } from './CaptionAppearance';
import { NumericInput } from './NumericInput';

const json = (body: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});
const makeId = () => crypto.randomUUID().replaceAll('-', '');

const languages = [['original', 'Original del audio'], ['es', 'Español'], ['en', 'Inglés'], ['pt', 'Portugués'],
  ['fr', 'Francés'], ['de', 'Alemán'], ['it', 'Italiano'], ['ja', 'Japonés'], ['zh', 'Chino'],
  ['ru', 'Ruso'], ['ar', 'Árabe'], ['hi', 'Hindi'], ['ko', 'Coreano'], ['nl', 'Neerlandés'],
  ['pl', 'Polaco'], ['tr', 'Turco'], ['uk', 'Ucraniano']];

async function readSubtitleFile(file: File) {
  if (file.size > 1024 * 1024) throw new Error('El archivo SRT/VTT supera 1 MB.');
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  if (bytes[0] === 255 && bytes[1] === 254) return new TextDecoder('utf-16le').decode(buffer);
  if (bytes[0] === 254 && bytes[1] === 255) return new TextDecoder('utf-16be').decode(buffer);
  try { return new TextDecoder('utf-8', { fatal: true }).decode(buffer); }
  catch { return new TextDecoder('windows-1252').decode(buffer); }
}

export function SubtitlesPanel({ video, track, dirty, enabled, sidecars, style, splitFraming, language, time, clipStart, clipEnd,
  setEnabled, setSidecars, setStyle, setLanguage, setSegments, onTrack, onSeek }: {
  video: Video | null; track: CaptionTrack | null; dirty: boolean; enabled: boolean; time: number;
  clipStart: number; clipEnd: number;
  setEnabled: (enabled: boolean) => void; setSegments: Dispatch<SetStateAction<CaptionSegment[]>>;
  onTrack: (track: CaptionTrack) => void; onSeek: (time: number) => void;
  sidecars: boolean; setSidecars: (enabled: boolean) => void;
  style: CaptionStyle; setStyle: Dispatch<SetStateAction<CaptionStyle>>;
  splitFraming: boolean;
  language: string; setLanguage: (language: string) => void;
}) {
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [analysisId, setAnalysisId] = useState('');
  const [find, setFind] = useState('');
  const [replace, setReplace] = useState('');
  const [busy, setBusy] = useState(false);
  const [smallJob, setSmallJob] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState(false);
  const [page, setPage] = useState(0);
  const [localAvailable, setLocalAvailable] = useState(false);
  const segments = track?.segments ?? [];

  useEffect(() => {
    if (!video) return;
    const controller = new AbortController();
    request<{ local_available: boolean }>(`/videos/${video.id}/captions/translation`, { signal: controller.signal })
      .then(status => setLocalAvailable(status.local_available)).catch(() => setLocalAvailable(false));
    const refresh = async () => {
      try {
        const history = await request<Analysis[]>(`/videos/${video.id}/analyses`, { signal: controller.signal });
        const complete = history.filter(item => item.status === 'completed');
        setAnalyses(complete);
        setAnalysisId(previous => complete.some(item => item.id === previous) ? previous : complete[0]?.id ?? '');
        const job = history.find(item => item.id === smallJob);
        if (job?.status === 'completed') {
          setAnalysisId(job.id); setSmallJob(null);
          setMessage('Transcripción Small disponible para generar la pista.');
        } else if (job && (job.status === 'failed' || job.status === 'cancelled')) {
          setSmallJob(null); setError(job.error ?? 'La retranscripción se canceló.');
        }
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 3500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [video?.id, smallJob]);

  async function retranscribe() {
    if (!video || busy || smallJob) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const job = await request<Analysis>(`/videos/${video.id}/analyses`, json({
        model: 'small', transcript_window: [clipStart, clipEnd], reuse_transcript: false, cpu_threads: 2,
      }));
      setSmallJob(job.id);
      setMessage('El clip seleccionado está en la cola de Whisper Small.');
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  }

  async function write(generate: boolean) {
    if (!video || !track || busy) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const endpoint = `/videos/${video.id}/captions`;
      const payload = generate
        ? { analysis_id: analysisId, revision: track.revision }
        : { revision: track.revision, segments };
      onTrack(await request<CaptionTrack>(generate ? endpoint + '/generate' : endpoint, json(payload)));
      setMessage(generate ? 'Pista generada y guardada.' : 'Cambios guardados.');
      if (generate) { setEnabled(true); setPage(0); }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); setConfirm(false); }
  }

  function update(index: number, patch: Partial<CaptionSegment>) {
    setSegments(previous => previous.map((segment, i) => i === index ? { ...segment, ...patch } : segment));
  }

  function split(index: number) {
    const segment = segments[index];
    const tokens = segment.text.trim().split(/\s+/);
    if (tokens.length < 2 || segment.end - segment.start < .04) return;
    const half = Math.ceil(tokens.length / 2);
    const timed = segment.words.length === tokens.length && segment.words.every((word, i) => word.text === tokens[i]);
    const midpoint = segment.start + (segment.end - segment.start) * half / tokens.length;
    const boundary = timed ? segment.words[half].start : midpoint;
    const pivot = Math.max(segment.start + .01, Math.min(segment.end - .01, boundary));
    const left = { ...segment, end: pivot, text: tokens.slice(0, half).join(' '), words: segment.words.filter(w => w.end <= pivot), translations: {} };
    const right = { ...segment, id: makeId(), start: pivot, text: tokens.slice(half).join(' '), words: segment.words.filter(w => w.start >= pivot), translations: {} };
    if (Object.keys(segment.translations).length) {
      for (const [language, text] of Object.entries(segment.translations)) {
        const parts = text.trim().split(/\s+/);
        const index = Math.ceil(parts.length * half / tokens.length);
        (left.translations as Record<string, string>)[language] = parts.slice(0, index).join(' ');
        (right.translations as Record<string, string>)[language] = parts.slice(index).join(' ');
      }
    }
    setSegments([...segments.slice(0, index), left, right, ...segments.slice(index + 1)]);
  }

  function merge(index: number) {
    const first = segments[index];
    const second = segments[index + 1];
    if (!second) return;
    const languages = new Set([...Object.keys(first.translations), ...Object.keys(second.translations)]);
    const translations = Object.fromEntries([...languages].map(code => [code, [first.translations[code], second.translations[code]].filter(Boolean).join(' ')]));
    const text = [first.text, second.text].filter(Boolean).join(' ');
    if ([text, ...Object.values(translations)].some(part => part.length > 600)) {
      setError('La combinación supera los 600 caracteres de un segmento. Acorta el texto antes de combinar.');
      return;
    }
    const combined = { ...first, text,
      end: second.end, words: [...first.words, ...second.words].slice(0, 60), translations };
    setSegments([...segments.slice(0, index), combined, ...segments.slice(index + 2)]);
  }

  function add() {
    if (!video) return;
    const start = Math.max(0, Math.min(time, video.duration - .02));
    const end = Math.min(video.duration, start + 1.5);
    const newCue = { id: makeId(), start, end, text: '', words: [], translations: {} };
    const ordered = [...segments, newCue].sort((a, b) => a.start - b.start);
    setPage(Math.floor(ordered.indexOf(newCue) / 25));
    setSegments(ordered);
  }

  const lastPage = Math.max(0, Math.ceil(segments.length / 25) - 1);
  const activePage = Math.min(lastPage, page);
  const offset = activePage * 25;
  const translating = language !== 'original';
  const visible = segments.slice(offset, offset + 25);

  async function translatePage(file?: File) {
    if (!video || !track?.revision || !translating || busy || dirty) return;
    setError(''); setMessage(''); setBusy(true);
    try {
      const payload = file ? { content: await readSubtitleFile(file) } : { segment_ids: visible.map(segment => segment.id) };
      const endpoint = `/videos/${video.id}/captions/translation/${file ? 'import' : 'local'}`;
      const updated = await request<CaptionTrack>(endpoint, json({ ...payload, revision: track.revision, language }));
      onTrack(updated);
      setMessage(file ? 'Traducción importada. Conserva los tiempos de la pista original.' : 'Página traducida. Puedes corregir el texto antes de exportar.');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <section className="panel phase-panel" id="captions-editor" aria-label="Subtítulos dinámicos">
    <div className="panel-heading"><div><Captions size={18}/><h2>Subtítulos dinámicos</h2></div></div>
    {!video ? <p className="phase-body field-note">Importa y selecciona un vídeo para editar sus subtítulos.</p> : !track
      ? <div className="phase-body"><p>Cargando pista de subtítulos…</p><button className="secondary" onClick={async () => {
        try { onTrack(await request<CaptionTrack>(`/videos/${video.id}/captions`)); } catch (e) { setError((e as Error).message); }
      }}>Volver a cargar</button>{error && <p role="alert">{error}</p>}</div>
      : <fieldset className="phase-body caption-fieldset" disabled={busy}>
        <div className="phase-toolbar">
          <label><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}/> Activar subtítulos</label>
          <label><input type="checkbox" checked={sidecars} onChange={e => setSidecars(e.target.checked)}/> Archivos SRT y VTT</label>
          <span>Idioma original del audio: <strong>{track.audio_language?.toUpperCase() ?? 'Sin análisis'}</strong></span>
          <button className="primary" disabled={busy || !dirty} onClick={() => void write(false)}><Save size={16}/> Guardar subtítulos</button>
        </div>
        <div className="phase-toolbar">
          <label>Idioma de los subtítulos<select aria-label="Idioma de los subtítulos" value={language} onChange={e => setLanguage(e.target.value)}>
            {!languages.some(([code]) => code === language) && <option value={language}>{language.toUpperCase()}</option>}
            {languages.map(([code, label]) => <option value={code} key={code}>{label}</option>)}
          </select></label>
          {translating && <>
            <label>Importar traducción SRT/VTT<input aria-label="Importar traducción SRT/VTT" type="file" accept=".srt,.vtt"
              disabled={dirty || !track.revision || !segments.length} onChange={e => {
                if (e.target.files?.[0]) void translatePage(e.target.files[0]);
                e.target.value = '';
              }}/></label>
            {localAvailable && <button className="secondary" disabled={dirty || !track.revision || !visible.length || !track.audio_language || track.audio_language === language}
              onClick={() => void translatePage()}>Traducir página con Argos</button>}
          </>}
        </div>
        {translating && <p className="field-note">
          Edita el texto traducido o importa un SRT/VTT con la misma cantidad de segmentos y en el mismo orden.
          {' '}{!localAvailable && 'Argos local no está configurado. '}
          {dirty && 'Guarda la pista antes de importar o traducir automáticamente. '}
          Los segmentos sin traducción se omiten al exportar este idioma.
        </p>}
        {dirty && <p className="field-note">Guarda la pista para usar los cambios en Vista exacta y en la exportación.</p>}
        <CaptionAppearance style={style} onChange={setStyle} split={splitFraming}/>
        <div className="phase-toolbar">
          <label>Transcripción de origen<select value={analysisId} onChange={e => setAnalysisId(e.target.value)}>
            <option value="">Sin análisis seleccionado</option>
            {analyses.map(analysis => <option key={analysis.id} value={analysis.id}>{analysis.options.model} · {new Date(analysis.created_at).toLocaleString('es')}</option>)}
          </select></label>
          <button className="secondary" disabled={!analysisId || busy} onClick={() => segments.length ? setConfirm(true) : void write(true)}>Generar desde Whisper</button>
          <button className="secondary" disabled={busy || !!smallJob || !video?.has_audio || clipEnd - clipStart < .1}
            onClick={() => void retranscribe()}>Retranscribir clip con Whisper Small</button>
          <button className="secondary" disabled={busy} onClick={add}><Plus size={15}/> Añadir segmento</button>
        </div>
        {!analyses.length && <p className="field-note">Para generar la pista automáticamente, analiza primero el vídeo en <a href="#ai-moments">Momentos con IA</a>.</p>}
        {confirm && <div className="phase-toolbar alert" role="alert">
          <span>Se reemplazará la pista editada de este vídeo.</span><button className="secondary" onClick={() => setConfirm(false)}>Cancelar</button>
          <button className="primary" disabled={busy} onClick={() => void write(true)}>Reemplazar pista</button>
        </div>}
        <div className="phase-toolbar">
          <label>Buscar texto <input value={find} onChange={e => setFind(e.target.value)}/></label>
          <label>Reemplazar por <input value={replace} onChange={e => setReplace(e.target.value)}/></label>
          <button className="secondary" disabled={!find || busy} onClick={() => setSegments(segments.map(segment => translating
            ? { ...segment, translations: { ...segment.translations, [language]: (segment.translations[language] || '').replaceAll(find, replace) } }
            : { ...segment, text: segment.text.replaceAll(find, replace) }))}>Reemplazar todo</button>
        </div>
        {message && <p role="status">{message}</p>}{error && <p className="alert error" role="alert">{error}</p>}
        <div className="caption-list">
          {visible.map((segment, localIndex) => {
            const index = offset + localIndex;
            return <article className="caption-row" key={segment.id}>
              <div className="phase-toolbar">
                <button className="secondary" title="Ir al segmento" onClick={() => onSeek(segment.start)}>{seconds(segment.start)}</button>
                <label>Inicio <NumericInput min={0} max={video.duration} precision={3} step={.01}
                  value={segment.start} onCommit={start => update(index, { start })}/></label>
                <label>Final <NumericInput min={.01} max={video.duration} precision={3} step={.01}
                  value={segment.end} onCommit={end => update(index, { end })}/></label>
              </div>
              <label>Texto del segmento {index + 1}<textarea maxLength={600} value={segment.text} onChange={e => update(index, { text: e.target.value })}/></label>
              {translating && <label>Traducción del segmento {index + 1}<textarea value={segment.translations[language] ?? ''}
                maxLength={600} onChange={e => update(index, { translations: { ...segment.translations, [language]: e.target.value } })}/></label>}
              <div className="phase-toolbar">
                <button className="secondary" onClick={() => split(index)} disabled={busy || segment.text.trim().split(/\s+/).length < 2}>Dividir</button>
                <button className="secondary" onClick={() => merge(index)} disabled={busy || index >= segments.length - 1}>Combinar con siguiente</button>
                <button className="secondary danger-link" disabled={busy} onClick={() => setSegments(segments.filter(item => item.id !== segment.id))}>Eliminar segmento</button>
              </div>
            </article>;
          })}
        </div>
        {lastPage > 0 && <div className="phase-toolbar">
          <button className="secondary" disabled={activePage === 0} onClick={() => setPage(activePage - 1)}>Anterior</button>
          <span>Página {activePage + 1} de {lastPage + 1}</span>
          <button className="secondary" disabled={activePage === lastPage} onClick={() => setPage(activePage + 1)}>Siguiente</button>
        </div>}
      </fieldset>}
  </section>;
}
