import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowRight, Check, CheckCheck, ChevronDown, ChevronRight, CircleHelp, Clapperboard, Clock3, Crop, Download, Film, FolderOpen, Frame, HardDrive, LayoutGrid, LoaderCircle, Maximize, Monitor, Pause, Play, Plus, Radio, Scissors, Settings2, ShieldCheck, SkipBack, Upload, Volume2, VolumeX, WandSparkles, X } from 'lucide-react';
import { request, seconds, sizeLabel, uploadVideo, type CaptionTrack, type ClipSettings, type GraphicLayer, type Health, type Job, type RenderOptions, type SourceGeometry, type SplitLayout, type Video } from './api';
import { Modal } from './components/Modal';
import { ratios, presets, statusLabel } from './presets';
import { AnalysisPanel } from './components/AnalysisPanel';
import { Timeline } from './components/Timeline';
import { NumericInput } from './components/NumericInput';
import { earliestClipEnd, formatTimecode, latestClipStart, MIN_CLIP_SECONDS, roundTimelineTime } from './timelineTime';
import { BlurBackdrop } from './components/BlurBackdrop';
import { SubtitlesPanel } from './components/SubtitlesPanel';
import { captionPresets } from './components/CaptionAppearance';
import { CaptionOverlay } from './components/CaptionOverlay';
import { CampaignPanel, GraphicOverlay } from './components/CampaignPanel';
import { LivePanel, type LiveDestination } from './components/LivePanel';
import { defaultSplitLayout, normalizeSplitLayout, SplitCanvas, SplitControls, SplitRegionEditor } from './components/SplitFraming';
import { emptyGameplay, splitGeometry } from './splitFramingGeometry';

import { DiskWarning, RemoveButton, RemoveDialog, SelectionBar, StoragePanel, type RemovalTarget } from './components/StoragePanel';

type View = 'editor' | 'library' | 'exports' | 'storage' | 'live';
const viewNames: Record<View, string> = { editor: 'Editor de clips', library: 'Mis vídeos', exports: 'Exportaciones', storage: 'Almacenamiento', live: 'ClipZone Live' };
const pageCopy: Record<View, { eyebrow?: string; heading: string; description: string }> = {
  editor: { eyebrow: 'CREA. RECORTA. COMPARTE.', heading: 'Un vídeo. Más posibilidades.', description: 'Encuentra el momento. Dale tu formato. Hazlo tuyo.' },
  library: { eyebrow: 'TU BIBLIOTECA LOCAL', heading: 'Todo empieza por aquí.', description: 'Tus originales, siempre a mano para crear algo nuevo.' },
  exports: { eyebrow: 'CONTENIDO LISTO PARA SALIR', heading: 'Tus próximos grandes clips.', description: 'Revisa el resultado y descarga tus clips cuando estén listos.' },
  storage: { eyebrow: 'DATOS LOCALES', heading: 'Almacenamiento', description: 'Consulta el espacio ocupado y libera archivos temporales.' },
  live: { heading: 'ClipZone Live', description: 'Guarda fragmentos de directos autorizados mediante captura directa u OBS Studio.' },
};
const liveTargets = { editor: 'clip-editor', analysis: 'ai-moments', subtitles: 'captions-editor', export: 'clip-export' };
const playerVolumeKey = 'clipzone.player.volume';

function readPlayerVolume() {
  const fallback = { level: 100, lastAudibleLevel: 100 };
  try {
    const saved = JSON.parse(localStorage.getItem(playerVolumeKey) ?? 'null');
    if (!saved || !Number.isInteger(saved.level) || saved.level < 0 || saved.level > 100) return fallback;
    const level: number = saved.level;
    const lastAudibleLevel: number = saved.lastAudibleLevel;
    return { level, lastAudibleLevel: level || (
      Number.isInteger(lastAudibleLevel) && lastAudibleLevel > 0 && lastAudibleLevel <= 100 ? lastAudibleLevel : 100
    ) };
  } catch {
    return fallback;
  }
}

export default function App() {
  const [view, setView] = useState<View>('editor');
  const [videos, setVideos] = useState<Video[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [start, setStart] = useState(0); const [end, setEnd] = useState(30);
  const [title, setTitle] = useState('Mi primer clip');
  const [platform, setPlatform] = useState('tiktok'); const [ratio, setRatio] = useState('9:16');
  const [resolution, setResolution] = useState(1080); const [fit, setFit] = useState<ClipSettings['fit']>('contain');
  const [blur, setBlur] = useState(55);
  const [splitLayout, setSplitLayout] = useState<SplitLayout>(defaultSplitLayout);
  const [splitDraft, setSplitDraft] = useState<{ base: SplitLayout; layout: SplitLayout } | null>(null);
  const [splitRegion, setSplitRegion] = useState<'camera' | 'gameplay'>('camera');
  const [sourceGeometry, setSourceGeometry] = useState<{ url: string; ratio: number } | null>(null);
  const [legacyGeometry, setLegacyGeometry] = useState<{ id: string; source: SourceGeometry | null } | null>(null);
  const [monitor, setMonitor] = useState<'live' | 'original' | 'exact'>('live');
  const [previewRequest, setPreviewRequest] = useState<{ id: string; key: string } | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [safeTop, setSafeTop] = useState(10); const [safeBottom, setSafeBottom] = useState(22);
  const [focusX, setFocusX] = useState(50); const [focusY, setFocusY] = useState(50);
  const [guides, setGuides] = useState(true); const [playing, setPlaying] = useState(false);
  const [playerVolume, setPlayerVolume] = useState(readPlayerVolume);
  const [current, setCurrent] = useState(0);
  const [uploading, setUploading] = useState<number | null>(null); const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [roadmap, setRoadmap] = useState(false); const [help, setHelp] = useState(false);
  const [preview, setPreview] = useState<Job | null>(null); const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null); const player = useRef<HTMLVideoElement>(null);
  const [selectedVideos, setSelectedVideos] = useState<string[]>([]);
  const [selectedExports, setSelectedExports] = useState<string[]>([]);
  const [removal, setRemoval] = useState<{ kind: 'videos' | 'exports'; targets: RemovalTarget[] } | null>(null);
  const refreshSequence = useRef(0);
  const selected = videos.find(v => v.id === selectedId) || null;
  const [captionsEnabled, setCaptionsEnabled] = useState(false);
  const [captionSidecars, setCaptionSidecars] = useState(false);
  const [captionStyle, setCaptionStyle] = useState(captionPresets.classic);
  const [captionLanguage, setCaptionLanguage] = useState('original');
  const [graphics, setGraphics] = useState<GraphicLayer[]>([]);
  const [activeGraphic, setActiveGraphic] = useState<string | null>(null);
  const [tracks, setTracks] = useState<Record<string, { track: CaptionTrack; dirty: boolean }>>({});
  const captionState = selectedId ? tracks[selectedId] : undefined;
  const captionTrack = captionState?.track ?? null;
  const needsCaptionTrack = captionsEnabled || captionSidecars;
  const captionRenderBlocked = needsCaptionTrack && !!captionState?.dirty;
  const ratioNumber = Number(ratio.split(':')[0]) / Number(ratio.split(':')[1]);
  const outputWidth = ratioNumber > 1 ? Math.round(resolution * ratioNumber / 2) * 2 : resolution;
  const outputHeight = ratioNumber > 1 ? resolution : Math.round(resolution / ratioNumber / 2) * 2;
  const splitPreview = splitDraft?.base === splitLayout ? splitDraft.layout : splitLayout;
  const sourceWidth = selected?.width;
  const sourceHeight = selected?.height;
  const displayWidth = selected?.display_width;
  const savedGeometry = legacyGeometry?.id === selectedId ? legacyGeometry : null;
  const splitSource = useMemo(() => sourceWidth && sourceHeight && displayWidth
    ? { width: sourceWidth, height: sourceHeight, display_width: displayWidth } : savedGeometry?.source,
  [sourceWidth, sourceHeight, displayWidth, savedGeometry]);
  const splitPlan = useMemo(() => fit === 'split' && splitSource
    ? splitGeometry(splitPreview, outputWidth, outputHeight, splitSource) : null,
  [fit, splitPreview, outputWidth, outputHeight, splitSource]);
  const splitStatus = splitSource ? emptyGameplay : savedGeometry ? 'No se pudieron leer las dimensiones del original.' : 'Leyendo dimensiones del original…';

  useEffect(() => {
    if (fit !== 'split' || !selectedId || displayWidth || savedGeometry) return;
    const controller = new AbortController();
    request<SourceGeometry>(`/videos/${selectedId}/geometry`, { signal: controller.signal })
      .then(source => { if (!controller.signal.aborted) setLegacyGeometry({ id: selectedId, source }); })
      .catch(() => { if (!controller.signal.aborted) setLegacyGeometry({ id: selectedId, source: null }); });
    return () => controller.abort();
  }, [fit, selectedId, displayWidth, savedGeometry]);

  function saveTrack(track: CaptionTrack) {
    setTracks(previous => ({ ...previous, [track.id]: { track, dirty: false } }));
  }

  useEffect(() => {
    if (!selectedId || captionState) return;
    const controller = new AbortController();
    request<CaptionTrack>(`/videos/${selectedId}/captions`, { signal: controller.signal }).then(saveTrack).catch(e => {
      if (!controller.signal.aborted) setError((e as Error).message);
    });
    return () => controller.abort();
  }, [selectedId, !!captionState]);

  function seekInEditor(time: number) {
    player.current?.pause();
    setMonitor('live');
    if (!exact) seek(time);
    else setCurrent(time);
    document.querySelector('.preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  const exports = jobs.filter(j => j.kind === 'export');
  const active = exports.filter(j => j.status === 'queued' || j.status === 'running');
  const canExport = !!selected && health?.status === 'ok' && end - start >= MIN_CLIP_SECONDS - 1e-9 && end <= selected.duration + 0.01 && end - start <= 3600
    && !captionRenderBlocked && (fit !== 'split' || !!splitPlan);
  const removableExports = exports.filter(job => job.status !== 'queued' && job.status !== 'running');
  const markedVideos = videos.filter(video => selectedVideos.includes(video.id));
  const markedExports = removableExports.filter(job => selectedExports.includes(job.id));
  const videoTarget = (video: Video) => ({ id: video.id, name: video.name, related: exports.filter(j => j.video_id === video.id).length });
  const exportTarget = (job: Job) => ({ id: job.id, name: job.title });
  const toggleMarked = (ids: string[], id: string) => ids.includes(id) ? ids.filter(value => value !== id) : [...ids, id];

  function onRemoved(ids: string[], warnings: string[]) {
    refreshSequence.current++;
    if (removal?.kind === 'videos') {
      setVideos(previous => previous.filter(item => !ids.includes(item.id)));
      setSelectedVideos(previous => previous.filter(id => !ids.includes(id)));
      if (selectedId && ids.includes(selectedId)) {
        player.current?.pause();
        setSelectedId(null); setMonitor('live'); setPlaying(false); setCurrent(0);
      }
    } else {
      setJobs(previous => previous.filter(item => !ids.includes(item.id)));
      setSelectedExports(previous => previous.filter(id => !ids.includes(id)));
    }
    if (ids.length) setNotice(ids.length + ' elementos retirados.');
    if (warnings.length) setError([...new Set(warnings)].join(' '));
    void refresh().catch(e => setError((e as Error).message));
  }

  const renderOptions = { ratio, resolution, fit, platform, safe_top: safeTop, safe_bottom: safeBottom,
    focus_x: focusX, focus_y: focusY, blur_strength: blur, split_layout: fit === 'split' ? splitPreview : null,
    graphics,
    captions: needsCaptionTrack && captionTrack?.revision ? {
      enabled: captionsEnabled, sidecars: captionSidecars, style: captionStyle, language: captionLanguage, revision: captionTrack.revision,
    } : null };
  function applyComposition(options: RenderOptions) {
    setRatio(options.ratio); setResolution(options.resolution); setFit(options.fit); setPlatform(options.platform);
    setSafeTop(options.safe_top); setSafeBottom(options.safe_bottom); setFocusX(options.focus_x); setFocusY(options.focus_y);
    setBlur(options.blur_strength ?? 55);
    setSplitLayout(normalizeSplitLayout(options.split_layout));
    setSplitDraft(null);
    setCaptionsEnabled(options.captions?.enabled ?? false);
    setCaptionSidecars(options.captions?.sidecars ?? false);
    setCaptionLanguage(options.captions?.language ?? 'original');
    if (options.captions) setCaptionStyle(options.captions.style);
    setGraphics(options.graphics ?? []);
    setActiveGraphic(null);
  }
  const clip = selected ? { ...renderOptions, video_id: selected.id, title: title.trim() || 'Mi clip', start, end } : null;
  const previewKey = JSON.stringify({ ...renderOptions, video_id: selectedId, start, end });
  const draft = !captionRenderBlocked && previewRequest?.key === previewKey ? jobs.find(j => j.id === previewRequest.id) : undefined;
  const exact = monitor === 'exact';
  const exactReady = exact && draft?.status === 'completed';
  const sourceUrl = exact ? (exactReady ? draft.preview_url : null) : selected?.preview_url;
  const sourceOffset = exactReady ? start : 0;
  const volume = playerVolume.level;
  const muted = volume === 0;

  useLayoutEffect(() => {
    if (player.current) player.current.volume = volume / 100;
  }, [volume, sourceUrl, view]);

  useEffect(() => {
    try { localStorage.setItem(playerVolumeKey, JSON.stringify(playerVolume)); }
    catch { /* La sesión conserva el ajuste si el navegador bloquea el almacenamiento. */ }
  }, [playerVolume]);

  function changeVolume(level: number) {
    setPlayerVolume(previous => ({ level, lastAudibleLevel: level || previous.lastAudibleLevel }));
  }

  function toggleMute() {
    setPlayerVolume(previous => ({ ...previous, level: previous.level === 0 ? previous.lastAudibleLevel : 0 }));
  }

  const audioAction = muted ? 'Activar sonido' : 'Silenciar';

  useEffect(() => {
    if (exact && !exactReady) setPlaying(false);
  }, [exact, exactReady]);

  async function preparePreview() {
    player.current?.pause();
    setPlaying(false);
    setMonitor('exact');
    if (!clip || !canExport || preparing || (draft && ['queued', 'running', 'completed'].includes(draft.status))) return;
    setPreparing(true);
    setError('');
    try {
      const job = await request<Job>('/clips/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(clip) });
      setPreviewRequest({ id: job.id, key: previewKey });
      setJobs(previous => [job, ...previous.filter(item => item.id !== job.id)]);
    } catch (e) { setError((e as Error).message); }
    finally { setPreparing(false); }
  }

  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    const [h, v, j] = await Promise.all([request<Health>('/health'), request<Video[]>('/videos'), request<Job[]>('/jobs')]);
    if (sequence === refreshSequence.current) { setHealth(h); setVideos(v); setJobs(j); }
  }, []);
  useEffect(() => {
    let alive = true;
    const tick = async () => { try { if (alive) await refresh(); } catch { if (alive) setHealth(null); } };
    void tick(); const timer = window.setInterval(tick, 1800);
    return () => { alive = false; window.clearInterval(timer); };
  }, [refresh]);
  useEffect(() => { if (!notice) return; const t = window.setTimeout(() => setNotice(''), 6000); return () => clearTimeout(t); }, [notice]);
  useEffect(() => { if (view !== 'editor') { player.current?.pause(); setPlaying(false); } }, [view]);

  function selectVideo(video: Video) {
    player.current?.pause(); setPlaying(false); setMonitor('live'); setSelectedId(video.id); setStart(0);
    setSplitDraft(null);
    setEnd(Math.min(presets[platform].duration, video.duration)); setCurrent(0);
    setTitle(`${video.name.replace(/\.[^.]+$/, '')} · clip 01`.slice(0, 100)); setView('editor'); setError('');
  }
  const addCapturedVideo = useCallback((video: Video) => {
    refreshSequence.current++;
    setVideos(previous => previous.some(item => item.id === video.id) ? previous : [video, ...previous]);
  }, []);

  function openCapturedVideo(video: Video, destination: LiveDestination, options?: RenderOptions) {
    addCapturedVideo(video);
    selectVideo(video);
    setEnd(video.duration);
    if (options) applyComposition(options);
    window.setTimeout(() => {
      const target = document.getElementById(liveTargets[destination]);
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (destination === 'export') target?.querySelector('button')?.focus({ preventScroll: true });
    }, 40);
  }
  async function importFile(file?: File) {
    if (!file || uploading !== null) return;
    if (health?.status !== 'ok') { setError('El servidor local necesita FFmpeg y FFprobe. Revisa la instalación.'); return; }
    if (file.size > health.max_upload_bytes) { setError('Este archivo supera el límite local de importación.'); return; }
    setError(''); setUploading(0);
    try {
      const video = await uploadVideo(file, setUploading);
      setVideos(v => [video, ...v.filter(item => item.id !== video.id)]); selectVideo(video);
      setNotice('Vídeo importado. Elige el fragmento que quieres contar.');
    } catch (e) { setError((e as Error).message); }
    finally { setUploading(null); if (input.current) input.current.value = ''; }
  }
  function seek(time: number) {
    if (!selected) return;
    const clamped = Math.max(0, Math.min(time, selected.duration));
    const position = exact ? Math.max(start, Math.min(end, clamped)) : clamped;
    if (player.current?.readyState) player.current.currentTime = position - sourceOffset;
    setCurrent(position);
  }
  function scrub(time: number) {
    player.current?.pause();
    if (exact && (time < start || time > end)) {
      setMonitor('live');
      setCurrent(time);
    } else {
      seek(time);
    }
  }
  async function togglePlay() {
    if (!player.current) return;
    if (playing) { player.current.pause(); return; }
    if (monitor !== 'original' && (current < start || current >= end)) seek(start);
    try { await player.current.play(); } catch { setError('No se pudo reproducir. Prueba otro vídeo o vuelve a cargar la página.'); }
  }
  function setIn(value: number) {
    if (!selected || !Number.isFinite(value)) return;
    const next = Math.max(0, Math.min(roundTimelineTime(value), latestClipStart(end)));
    if (next === start) return;
    leaveExactPreview();
    setStart(next);
  }
  function setOut(value: number) {
    if (!selected || !Number.isFinite(value)) return;
    const next = value >= selected.duration ? selected.duration :
      Math.min(selected.duration, Math.max(earliestClipEnd(start, selected.duration), roundTimelineTime(value)));
    if (next === end) return;
    leaveExactPreview();
    setEnd(next);
  }
  function leaveExactPreview() {
    if (!exact) return;
    player.current?.pause();
    setMonitor('live');
    setPlaying(false);
  }
  function applyPlatform(key: string) {
    const p = presets[key]; setPlatform(key); setRatio(p.ratio); setSafeTop(p.top); setSafeBottom(p.bottom);
    if (selected) setEnd(Math.min(selected.duration, start + p.duration));
  }
  async function exportClip() {
    if (!canExport || !selected || submitting) return;
    setSubmitting(true); setError('');
    const body = clip;
    try {
      const job = await request<Job>('/clips', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      setJobs(j => [job, ...j]); setView('exports'); setNotice('Exportación en cola. Puedes seguir creando clips.');
    } catch (e) { setError((e as Error).message); }
    finally { setSubmitting(false); }
  }
  async function cancelJob(id: string) {
    try { const updated = await request<Job>(`/jobs/${id}/cancel`, { method: 'POST' }); setJobs(j => j.map(item => item.id === id ? updated : item)); }
    catch (e) { setError((e as Error).message); }
  }
  const displayRatio = monitor === 'original' && selected
    ? (sourceGeometry && sourceGeometry.url === sourceUrl ? sourceGeometry.ratio : (selected.display_width ?? selected.width) / selected.height)
    : outputWidth / outputHeight;

  function updatePlayback() {
    const video = player.current;
    if (!video) return;
    const position = video.currentTime + sourceOffset;
    if (monitor === 'live' && position >= end && !video.paused) {
      video.pause();
      video.currentTime = end;
      setCurrent(end);
    } else {
      setCurrent(exact ? Math.min(end, position) : position);
    }
  }

  return <div className="app-shell">
    <input ref={input} type="file" className="sr-only" aria-label="Seleccionar vídeo" accept=".mp4,.mov,.mkv,.webm,.avi,.m4v,.mts,.m2ts" onChange={e => void importFile(e.target.files?.[0])}/>
    <aside className="sidebar">
      <div className="sidebar-scroll">
        <a className="brand" href="#" aria-label="ClipZone Studio" onClick={e => { e.preventDefault(); setView('editor'); }}><div className="brand-mark"><Scissors size={23}/></div><span>clipzone<span className="brand-sub">STUDIO</span></span></a>
        <button className="primary sidebar-import" title="Importar vídeo" onClick={() => input.current?.click()} disabled={uploading !== null}><Plus size={18}/>Importar vídeo</button>
        <span className="nav-label">ESPACIO DE TRABAJO</span>
        <nav aria-label="Principal">
          <button className={`nav-item ${view === 'editor' ? 'selected' : ''}`} onClick={() => setView('editor')} title="Editor de clips"><Clapperboard size={18}/>Editor de clips<ChevronRight size={14} className="nav-chevron"/></button>
          <button className={`nav-item ${view === 'live' ? 'selected' : ''}`} onClick={() => setView('live')} title="ClipZone Live"><Radio size={18}/>ClipZone Live</button>
          <button className={`nav-item ${view === 'library' ? 'selected' : ''}`} onClick={() => setView('library')} title="Mis vídeos"><FolderOpen size={18}/>Mis vídeos<span className="count">{videos.length}</span></button>
          <button className={`nav-item ${view === 'exports' ? 'selected' : ''}`} onClick={() => setView('exports')} title="Exportaciones"><ArrowDownToLine size={18}/>Exportaciones{active.length > 0 ? <span className="activity-dot"/> : <span className="count">{exports.length}</span>}</button>
          <button title="Almacenamiento" className={`nav-item ${view === 'storage' ? 'selected' : ''}`} onClick={() => setView('storage')}><HardDrive size={18}/>Almacenamiento</button>
        </nav>
        <div className="nav-divider"/><span className="nav-label">INTELIGENCIA LOCAL</span>
        <button className="nav-item ai-nav" onClick={() => { setView('editor'); window.setTimeout(() => document.getElementById('ai-moments')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 40); }}><WandSparkles size={18}/>Momentos con IA<span className="tiny-tag">F2</span></button>
        <button className="nav-item ai-nav" title="Subtítulos dinámicos" onClick={() => {
          setView('editor');
          window.setTimeout(() => document.getElementById('captions-editor')?.scrollIntoView({ behavior: 'smooth' }), 40);
        }}><Frame size={18}/>Subtítulos dinámicos</button>
        <button className="nav-item ai-nav" title="Gráficos y plantillas" onClick={() => {
          setView('editor');
          window.setTimeout(() => document.getElementById('campaign-editor')?.scrollIntoView({ behavior: 'smooth' }), 40);
        }}><LayoutGrid size={18}/>Gráficos y plantillas</button>
        <div className="sidebar-bottom">
          <div className="local-card"><div className="local-card-icon"><ShieldCheck size={18}/><span>Tu equipo. Tus archivos.</span></div><p>Procesamiento local.<br/>Sin suscripciones.</p><div className="local-line"><span className="activity-dot"/> MODO LOCAL</div></div>
          <button className="nav-item help-button" onClick={() => setHelp(true)}><CircleHelp size={18}/>Guía de inicio<ArrowRight size={14}/></button>
        </div>
      </div>
      <div className="profile"><div className="avatar">CZ</div><div><strong>Mi espacio local</strong><span>ClipZone Studio{health ? ` · v${health.version}` : ''}</span></div><Monitor size={16}/></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="breadcrumbs"><LayoutGrid size={16}/><span>Mi espacio</span><ChevronRight size={13}/><strong>{viewNames[view]}</strong></div><div className="topbar-right"><span className="version-tag">FASE 03</span><span className={`server-status ${health?.status === 'ok' ? 'online' : ''}`}><i/>{health?.status === 'ok' ? 'Motor local listo' : health ? 'Faltan dependencias' : 'Sin conexión'}</span></div></header>
      <main onDragOver={e => { e.preventDefault(); if (e.dataTransfer.types.includes('Files')) setDragging(true); }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }} onDrop={e => { e.preventDefault(); setDragging(false); void importFile(e.dataTransfer.files[0]); }}>
        {dragging && <div className="drop-overlay"><Upload size={40}/><h2>Suelta tu próximo gran vídeo</h2><span>Se procesará en este equipo</span></div>}
        <div className="page-heading"><div>{pageCopy[view].eyebrow && <div className="eyebrow"><span/>{pageCopy[view].eyebrow}</div>}<h1>{pageCopy[view].heading}</h1><p>{pageCopy[view].description}</p></div><div className="heading-action">{view === 'editor' ? <><div className="step done"><span>01</span>Importa</div><div className="step-line"/><div className={`step ${selected ? 'done' : ''}`}><span>02</span>Edita</div><div className="step-line"/><div className="step"><span>03</span>Exporta</div></> : <button className="secondary" onClick={() => setView('editor')}><ArrowLeft size={16}/>Volver al editor</button>}</div></div>
        {view !== 'storage' && health?.storage && <DiskWarning space={health.storage}/>}
        {error && <div className="alert error" role="alert"><CircleHelp size={17}/><span>{error}</span><button onClick={() => setError('')} aria-label="Cerrar error"><X size={16}/></button></div>}
        {notice && <div className="toast" role="status"><CheckCheck size={17}/>{notice}<button onClick={() => setNotice('')} aria-label="Cerrar aviso"><X size={15}/></button></div>}
        {health && health.status !== 'ok' && <div className="alert warning"><Settings2 size={17}/><span>Falta FFmpeg o FFprobe. Ejecuta <code>scripts/setup.ps1 -DownloadFFmpeg</code> y reinicia el servidor.</span></div>}
        <div hidden={view !== 'live'}><LivePanel active={view === 'live'} onImported={addCapturedVideo} onOpen={openCapturedVideo}/></div>
        {view === 'editor' && <>
          <div className="editor-grid" id="clip-editor">
<div className="editor-left">
            <section className="preview-panel panel">
              <div className="panel-heading"><div><span className="green-icon"><Play size={15}/></span><h2>Vista previa</h2><span className="small-tag">{ratio}</span></div><button className={`icon-button ${guides ? 'active-icon' : ''}`} onClick={() => setGuides(!guides)} title="Mostrar u ocultar zona segura" aria-label="Mostrar u ocultar zona segura" aria-pressed={guides}><Frame size={17}/></button></div>
              {selected && <div className="monitor-modes" aria-label="Modo de previsualización">
                <button className="secondary" aria-pressed={monitor === 'original'} onClick={() => { player.current?.pause(); setMonitor('original'); }}>Original</button>
                <button className="secondary" aria-pressed={monitor === 'live'} onClick={() => { player.current?.pause(); setMonitor('live'); }}>Encuadre en directo</button>
                <button className="secondary" aria-pressed={exact} disabled={!canExport} onClick={() => void preparePreview()}>Vista exacta</button>
              </div>}
              <div className={`stage ${selected ? 'has-video' : ''}`}>
                {selected ? <>
                  <div className="stage-label">{exact ? 'VISTA DE EXPORTACIÓN' : monitor === 'original' ? 'ORIGINAL' : 'ENCUADRE EN DIRECTO'}</div>
                  <div className="video-frame" style={{ aspectRatio: displayRatio, width: `min(100%, calc(var(--preview-height) * ${displayRatio}))` }}>
                    {sourceUrl ? <>
                      {monitor === 'live' && fit === 'blur' && <BlurBackdrop player={player} source={sourceUrl} aspect={displayRatio} strength={blur}/>}
                      <video key={sourceUrl} ref={player} src={sourceUrl} muted={muted} playsInline preload="auto"
                        className={monitor === 'live' && fit === 'split' ? 'split-source-video' : undefined}
                        style={{ objectFit: monitor === 'live' && fit === 'cover' ? 'cover' : 'contain',
                          objectPosition: monitor === 'live' && fit === 'cover' ? `${focusX}% ${focusY}%` : '50% 50%' }}
                        onLoadedMetadata={() => {
                          if (player.current) {
                            if (!exact && player.current.videoHeight) {
                              setSourceGeometry({ url: sourceUrl, ratio: player.current.videoWidth / player.current.videoHeight });
                            }
                            const position = exact ? Math.max(start, Math.min(end, current)) : current;
                            player.current.currentTime = position - sourceOffset;
                          }
                        }}
                        onTimeUpdate={updatePlayback} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
                        onEnded={() => setPlaying(false)} onClick={() => void togglePlay()}
                        onError={() => setError('No se pudo reproducir el archivo de vista previa.')}/>
                      {fit === 'split' && monitor === 'live' && (splitPlan && splitSource
                        ? <SplitCanvas player={player} source={sourceUrl} geometry={splitPlan} inverted={splitPreview.inverted}
                          sourceGeometry={splitSource}/>
                        : <div className="processing-preview" role="status">{splitStatus}</div>)}
                      {fit === 'split' && monitor === 'original' && <SplitRegionEditor layout={splitPreview} selected={splitRegion}
                        onSelect={setSplitRegion} onRect={(key, rect) => setSplitLayout(previous => ({
                          ...previous, [key]: { ...previous[key], rect },
                        }))}/>}
                    </> : <div className="processing-preview">
                      {exact ? <>
                        {preparing || draft?.status === 'running' || draft?.status === 'queued' ? <>
                          <LoaderCircle className="spin" size={24}/><span role="status">Renderizando · {draft?.progress ?? 0}%</span>
                          {draft && <button className="secondary" onClick={() => void cancelJob(draft.id)}>Cancelar vista previa</button>}
                        </> : <>
                          <span>{fit === 'split' && !splitPlan ? splitStatus : captionRenderBlocked ? 'Guarda los subtítulos para actualizar Vista exacta.' : draft?.error ? 'Falló el render de la vista previa.' : 'Genera la vista con los ajustes actuales.'}</span>
                          <button className="secondary" disabled={!canExport} onClick={() => void preparePreview()}>Generar vista exacta</button>
                        </>}
                      </> : <span>{selected.preview_status === 'processing' ? 'Preparando vídeo…' : 'El archivo de vista previa no está disponible.'}</span>}
                    </div>}
                    {monitor === 'live' && current >= start && current < end && graphics.length > 0 &&
                      <GraphicOverlay layers={graphics} time={current - start} ratio={displayRatio} format={ratio} resolution={resolution} canvasWidth={outputWidth}
                        seam={splitPlan ? (splitPreview.inverted ? splitPlan.gameplay.height : splitPlan.camera.height) * 100 / outputHeight : null}
                        selected={activeGraphic} select={setActiveGraphic}
                        move={(id, x, y) => setGraphics(previous => previous.map(layer => layer.id === id
                          ? { ...layer, x, y, ...(layer.hook ? { anchor: 'free' as const } : {}) } : layer))}/>}
                    {monitor === 'live' && sourceUrl && captionsEnabled && captionTrack && <CaptionOverlay segments={captionTrack.segments}
                      time={current} playing={playing} style={captionStyle} language={captionLanguage} ratio={ratio} resolution={resolution} safeTop={safeTop} safeBottom={safeBottom}
                      splitLayout={fit === 'split' ? (splitPreview.camera_share === splitLayout.camera_share ? splitLayout : splitPreview) : null}
                      clipStart={start} clipEnd={end}/>}
                    {guides && monitor === 'live' && <div className="safe-guides" style={{ top: `${safeTop}%`, bottom: `${safeBottom}%` }}><span>ZONA SEGURA</span><div className="safe-caption">Guía de subtítulos</div></div>}
                  </div>
                </> : <div className="empty-stage"><div className="stage-corner tl"/><div className="stage-corner tr"/><div className="stage-corner bl"/><div className="stage-corner br"/><div className="upload-illustration"><div className="film-back"/><div className="film-front"><Film size={35}/></div><span><Plus size={17}/></span></div><h3>Tu próximo clip empieza aquí</h3><p>Arrastra un vídeo o búscalo en tu equipo.<br/>Los mejores momentos ya están dentro.</p><button className="primary" onClick={() => input.current?.click()} disabled={uploading !== null}>{uploading !== null ? <LoaderCircle className="spin" size={16}/> : <Upload size={16}/>} {uploading === null ? 'Seleccionar vídeo' : uploading < 100 ? `Importando ${uploading}%` : 'Analizando vídeo…'}</button><span className="file-formats">MP4, MOV, MKV, WebM y más · Hasta {health ? Math.round(health.max_upload_bytes / 1024 ** 3) : 20} GB</span></div>}
              </div>
              <div className="transport">
                <div className="transport-left">
                  <button className="icon-button" disabled={!selected} onClick={() => seek(start)}
                    aria-label="Ir al inicio del clip" title="Ir al inicio del clip"><SkipBack size={17}/></button>
                  <button className="play-button" aria-label={playing ? 'Pausar' : 'Reproducir clip'}
                    title={playing ? 'Pausar' : 'Reproducir clip'} disabled={!sourceUrl} onClick={() => void togglePlay()}>
                    {playing ? <Pause size={17} fill="currentColor"/> : <Play size={17} fill="currentColor"/>}
                  </button>
                </div>
                <div className="transport-audio">
                  <button className="icon-button" disabled={!selected} onClick={toggleMute} aria-label={audioAction} title={audioAction}>
                    {muted ? <VolumeX size={17}/> : <Volume2 size={17}/>}
                  </button>
                  <input type="range" min={0} max={100} step={1} value={volume} disabled={!selected}
                    aria-label="Volumen del reproductor" aria-valuetext={volume + '%'} onChange={event => changeVolume(event.target.valueAsNumber)}/>
                  <output aria-hidden="true">{volume}%</output>
                </div>
                <div className="timecode"><strong>{formatTimecode(current, true)}</strong><span>/</span>{formatTimecode(selected?.duration || 0, true)}</div>
                <button className="icon-button transport-fullscreen" disabled={!selected} aria-label="Pantalla completa" title="Pantalla completa"
                  onClick={() => { void player.current?.closest('.stage')?.requestFullscreen(); }}><Maximize size={16}/></button>
              </div>
            </section>
            <section className="timeline-panel panel"><div className="panel-heading"><div><Scissors size={17}/><h2>Elige tu momento</h2></div><div className="duration-badge"><Clock3 size={13}/>{(selected ? end - start : 0).toFixed(2)} s seleccionados</div></div><div className="timeline-body"><div className="clip-fields"><label className="clip-title">Nombre del clip<input value={title} maxLength={100} onChange={e => setTitle(e.target.value)} placeholder="Nombre del clip"/></label></div>
              <Timeline key={selectedId ?? 'empty'} video={selected} start={start} end={end} current={current} title={title} seek={scrub} setIn={setIn} setOut={setOut}/>
              <div className="timeline-bottom"><div className="quick-durations"><span>Duración rápida</span>{[15, 30, 60].map(d => <button key={d} disabled={!selected} onClick={() => { if (selected) setOut(start + d); }}>{d} s</button>)}<button disabled={!selected} onClick={() => { if (selected) { leaveExactPreview(); setStart(0); setEnd(selected.duration); if (exact) setCurrent(0); else seek(0); } }}>Completo</button></div></div>
            </div></section>
</div>
<div className="editor-right">
            <aside className="settings-panel panel">
              <div className="panel-heading"><div><Settings2 size={17}/><h2>Configura tu clip</h2></div><span className="small-tag">MP4</span></div>
              <div className="settings-body"><section className="setting-section"><div className="field-heading"><label>Destino</label><span>Preset de edición</span></div><div className="platform-grid">{Object.entries(presets).filter(([key]) => key !== 'custom').map(([key, p]) => <button key={key} className={platform === key ? 'chosen' : ''} onClick={() => applyPlatform(key)} aria-pressed={platform === key}><b>{p.symbol}</b>{p.label}</button>)}</div><button className={`custom-preset ${platform === 'custom' ? 'chosen' : ''}`} onClick={() => applyPlatform('custom')} aria-pressed={platform === 'custom'}>↗ Formato libre</button></section>
                <section className="setting-section"><div className="field-heading"><label>Formato</label><span>Relación de aspecto</span></div><div className="ratio-grid">{ratios.map(r => <button key={r} className={ratio === r ? 'chosen' : ''} onClick={() => setRatio(r)} aria-pressed={ratio === r}><span className="ratio-shape" style={{ aspectRatio: r.replace(':', ' / ') }}/><span>{r}</span>{ratio === r && <Check size={11} className="ratio-check"/>}</button>)}</div></section>
                <section className="setting-section"><div className="field-heading"><label>Encuadre</label><Crop size={14}/></div><div className="segmented"><button className={fit === 'contain' ? 'chosen' : ''} onClick={() => setFit('contain')} aria-pressed={fit === 'contain'}>Ajustar completo</button><button className={fit === 'cover' ? 'chosen' : ''} onClick={() => setFit('cover')} aria-pressed={fit === 'cover'}>Llenar y recortar</button><button className={fit === 'blur' ? 'chosen' : ''} aria-pressed={fit === 'blur'} onClick={() => setFit('blur')}>Fondo difuminado</button><button className={fit === 'split' ? 'chosen' : ''} aria-pressed={fit === 'split'} onClick={() => { setFit('split'); leaveExactPreview(); }}>Streamer + Gameplay</button></div>{fit === 'blur' && <label className="blur-control">Intensidad <input aria-label="Intensidad del desenfoque" type="range" min="0" max="100" value={blur} onChange={e => setBlur(+e.target.value)}/><output>{blur}%</output></label>}{fit === 'cover' && <div className="focus-controls"><label>Foco horizontal <input aria-label="Foco horizontal" type="range" min="0" max="100" value={focusX} onChange={e => setFocusX(+e.target.value)}/></label><label>Foco vertical <input aria-label="Foco vertical" type="range" min="0" max="100" value={focusY} onChange={e => setFocusY(+e.target.value)}/></label></div>}{fit === 'split' && <SplitControls layout={splitLayout} onChange={setSplitLayout} selected={splitRegion}
                  onPreview={layout => setSplitDraft(layout ? { base: splitLayout, layout } : null)}
                  onSelect={setSplitRegion} canEdit={!!sourceUrl || !!selected?.preview_url}
                  onEditSource={() => { player.current?.pause(); setMonitor('original'); document.querySelector('.preview-panel')?.scrollIntoView({ block: 'center' }); }}/>}
                {fit !== 'split' && <p className="field-note">{fit === 'contain' ? 'Conserva toda la imagen con bandas negras.' : fit === 'cover' ? 'Desplaza el foco para elegir qué parte conservar.' : 'La imagen completa se muestra sobre un fondo ampliado.'}</p>}</section>
                <section className="setting-section resolution-row"><label htmlFor="resolution">Resolución</label><div className="select-wrap"><select id="resolution" value={resolution} onChange={e => setResolution(+e.target.value)}><option value={1080}>1080p · Full HD</option><option value={720}>720p · HD</option><option value={480}>480p · Ligero</option></select><ChevronDown size={13}/></div></section>
                <section className="setting-section safe-section"><div className="field-heading"><label htmlFor="safe-guides">Zona segura de subtítulos</label><button id="safe-guides" role="switch" aria-checked={guides} aria-label="Guías de zona segura" className={`switch ${guides ? 'on' : ''}`} onClick={() => setGuides(!guides)}><span/></button></div><div className="safe-inputs"><label>Superior<div><NumericInput aria-label="Margen superior" min={0} max={35} value={safeTop} onCommit={setSafeTop}/><span>%</span></div></label><label>Inferior<div><NumericInput aria-label="Margen inferior" min={0} max={40} value={safeBottom} onCommit={setSafeBottom}/><span>%</span></div></label></div><p className="field-note">Guías orientativas, no se imprimen en el vídeo.<br/>Para añadir texto sincronizado, abre Subtítulos dinámicos.</p></section>
              </div>
            </aside>
            <div className="export-panel panel" id="clip-export"><div className="export-summary"><div className="export-icon"><Download size={20}/></div><div><strong>Listo para tu siguiente historia</strong><span>{outputWidth} × {outputHeight} · H.264 + AAC · MP4</span></div></div><button className="primary export-button" disabled={!canExport || submitting} onClick={() => void exportClip()}>{submitting ? <LoaderCircle className="spin" size={17}/> : <ArrowDownToLine size={17}/>}Exportar clip<ArrowRight size={16}/></button><span className="export-note"><HardDrive size={12}/>Se guarda en este equipo</span></div>
</div>
          </div>
          <SubtitlesPanel key={selectedId ?? 'empty'} video={selected} track={captionTrack} dirty={!!captionState?.dirty}
            clipStart={start} clipEnd={end}
            enabled={captionsEnabled} setEnabled={setCaptionsEnabled} time={current} sidecars={captionSidecars} setSidecars={setCaptionSidecars}
            style={captionStyle} setStyle={setCaptionStyle} splitFraming={fit === 'split'} language={captionLanguage} setLanguage={setCaptionLanguage} onTrack={saveTrack} onSeek={seekInEditor}
            setSegments={update => {
              if (captionTrack) setTracks(previous => {
                const track = previous[captionTrack.id]?.track ?? captionTrack;
                const segments = typeof update === 'function' ? update(track.segments) : update;
                return { ...previous, [track.id]: { track: { ...track, segments }, dirty: true } };
              });
            }}/>
          <CampaignPanel layers={graphics} options={{
            ...renderOptions,
            captions: needsCaptionTrack ? { enabled: captionsEnabled, sidecars: captionSidecars, language: captionLanguage, style: captionStyle, revision: null } : null,
          }} onLayers={setGraphics} onApply={applyComposition} duration={end - start} videoId={selected?.id} start={start} end={end} title={title}
            onSelect={(id, time) => { setActiveGraphic(id); seekInEditor(Math.min(end - .001, start + time)); }}/>
          <AnalysisPanel video={selected} output={renderOptions} renderBlocked={captionRenderBlocked}
            onChoose={moment => { setMonitor('live'); player.current?.pause(); setPlaying(false); setStart(moment.start); setEnd(moment.end); setTitle(moment.title.slice(0, 100)); if (!exact) seek(moment.start); else setCurrent(moment.start); document.querySelector('.preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }}
            onExported={newJobs => { setJobs(previous => [...newJobs, ...previous.filter(j => !newJobs.some(n => n.id === j.id))]); setView('exports'); setNotice(`${newJobs.length} clips en cola. Puedes revisar cada MP4 antes de descargarlo.`); window.scrollTo({ top: 0, behavior: 'smooth' }); }}/>
          <section className="source-strip"><div><FolderOpen size={16}/><h2>Vídeos del proyecto</h2><span>{videos.length}</span></div>{videos.length > 0 ? <div className="source-chips">{videos.slice(0, 5).map(v => <button key={v.id} className={v.id === selectedId ? 'active' : ''} onClick={() => selectVideo(v)}><Film size={14}/><span>{v.name}</span><small>{seconds(v.duration)}</small></button>)}</div> : <p>Importa tu primer original y empieza a crear.</p>}<button className="text-button" disabled={uploading !== null} onClick={() => input.current?.click()}><Plus size={15}/>Añadir vídeo</button></section>
        </>}
        {view === 'library' && <>
          {videos.length > 0 && <SelectionBar count={markedVideos.length} all={markedVideos.length === videos.length}
            onAll={() => setSelectedVideos(markedVideos.length === videos.length ? [] : videos.map(v => v.id))}
            onRemove={() => setRemoval({ kind: 'videos', targets: markedVideos.map(videoTarget) })}/>}
          <section className="library-grid">{videos.length ? videos.map(video => <article className="video-card panel" key={video.id}>
            <button className="video-card-open" onClick={() => selectVideo(video)}>
              <div className="video-thumb"><img src={video.thumbnail_url} alt=""/><span>{seconds(video.duration)}</span><div className="thumb-play"><Play size={24}/></div></div>
              <div className="video-card-body"><h3>{video.name}</h3><p>{video.width} × {video.height} · {sizeLabel(video.size)}</p><span>Abrir en el editor</span></div>
            </button>
            <div className="library-actions">
              <label><input type="checkbox" aria-label={`Seleccionar vídeo ${video.name}`} checked={selectedVideos.includes(video.id)} onChange={() => setSelectedVideos(previous => toggleMarked(previous, video.id))}/> Seleccionar</label>
              <RemoveButton onClick={() => setRemoval({ kind: 'videos', targets: [videoTarget(video)] })}>Eliminar</RemoveButton>
            </div>
          </article>) : <div className="empty-page panel"><FolderOpen size={36}/><h2>Mis vídeos</h2><p>Importa un vídeo para empezar.</p>
            <button className="primary" onClick={() => input.current?.click()}><Plus size={16}/>Importar vídeo</button></div>}</section>
        </>}
        {view === 'storage' && <StoragePanel space={health?.storage} onCleaned={() => void refresh().catch(e => setError((e as Error).message))}/>}
        {view === 'exports' && <section className="exports-list"><div className="list-heading"><h2>Cola de exportación <span>{exports.length}</span></h2><span><span className="activity-dot"/>{active.length ? `${active.length} en proceso · uno a la vez` : 'Todo al día'}</span></div>
          {removableExports.length > 0 && <SelectionBar count={markedExports.length} all={markedExports.length === removableExports.length}
            onAll={() => setSelectedExports(markedExports.length === removableExports.length ? [] : removableExports.map(j => j.id))}
            onRemove={() => setRemoval({ kind: 'exports', targets: markedExports.map(exportTarget) })}/>}
          {exports.length ? exports.map(job => <article key={job.id} className={`export-card panel ${job.status}`}>
            <label className="export-select"><input type="checkbox" aria-label={`Seleccionar exportación ${job.title}`}
              disabled={job.status === 'queued' || job.status === 'running'} checked={selectedExports.includes(job.id)}
              onChange={() => setSelectedExports(previous => toggleMarked(previous, job.id))}/></label><div className="export-card-icon">{job.status === 'completed' ? <Check size={24}/> : job.status === 'running' ? <LoaderCircle size={23} className="spin"/> : job.status === 'failed' ? <CircleHelp size={24}/> : <Film size={24}/>}</div><div className="export-card-info"><h3>{job.title}</h3><p>{job.settings?.ratio} <span>·</span> {job.settings?.resolution}p <span>·</span> {((job.settings?.end || 0) - (job.settings?.start || 0)).toFixed(1)} s <span>·</span> {presets[job.settings?.platform || 'custom'].label}</p><div className="job-status"><span>{statusLabel[job.status]}</span>{job.status === 'running' && <><div className="progress-track"><div style={{ width: `${job.progress}%` }}/></div><b>{job.progress}%</b></>}{job.size && <small>{sizeLabel(job.size)}</small>}</div>{job.error && <p className="job-error">{job.error}</p>}</div><div className="export-card-actions">{job.status === 'completed' ? <><button className="secondary" onClick={() => setPreview(job)}><Play size={15}/>Previsualizar</button><a className="primary" href={job.download_url!} download><Download size={15}/>Descargar</a>
            {job.subtitles && <><a className="secondary" href={job.subtitles.srt} download>SRT</a><a className="secondary" href={job.subtitles.vtt} download>VTT</a></>}
          </> : (job.status === 'running' || job.status === 'queued') ? <button className="secondary" onClick={() => void cancelJob(job.id)}><X size={14}/>Cancelar</button> : <button className="secondary" onClick={() => { const v = videos.find(v => v.id === job.video_id); if (v) { selectVideo(v); if (job.settings) { const s = job.settings; setStart(s.start); setEnd(s.end); applyComposition(s); setTitle(s.title); } } }}>Volver a editar</button>}
          <RemoveButton disabled={job.status === 'queued' || job.status === 'running'}
            onClick={() => setRemoval({ kind: 'exports', targets: [exportTarget(job)] })}>Eliminar</RemoveButton></div></article>) : <div className="empty-page panel"><Clapperboard size={38}/><h2>El próximo clip puede ser el tuyo</h2><p>Selecciona un momento en el editor y pulsa Exportar clip.</p><button className="primary" onClick={() => setView('editor')}>Ir al editor<ArrowRight size={16}/></button></div>}</section>}
        <footer className="workspace-footer"><span><ShieldCheck size={13}/>Hecho para crear. Diseñado para quedarse en tu equipo.</span><span>CLIPZONE STUDIO <i/> EDICIÓN LOCAL</span></footer>
      </main>
    </div>
    {uploading !== null && <div className="upload-toast" role="status"><LoaderCircle className="spin" size={19}/><div><strong>{uploading < 100 ? `Importando vídeo · ${uploading}%` : 'Verificando vídeo y miniatura…'}</strong><div className="progress-track"><div style={{ width: `${uploading}%` }}/></div></div></div>}
    {removal && <RemoveDialog kind={removal.kind} targets={removal.targets} close={() => setRemoval(null)} onRemoved={onRemoved}/>}
    {preview && <Modal title={preview.title} onClose={() => setPreview(null)}><video className="export-preview" src={preview.preview_url!} controls autoPlay playsInline/><div className="modal-footer"><span>Así se verá tu archivo exportado.</span><a className="primary" href={preview.download_url!} download><Download size={16}/>Descargar MP4</a></div></Modal>}
    {roadmap && <Modal title="Más posibilidades, por fases" onClose={() => setRoadmap(false)}><div className="roadmap"><div><span className="roadmap-number ready">01</span><div><h3>Tu editor local <span className="small-tag">DISPONIBLE</span></h3><p>Importa, recorta, encuadra y exporta. Sin servicios de pago.</p></div></div><div><span className="roadmap-number ready">02</span><div><h3>Encuentra los mejores momentos</h3><p>Transcripción con Whisper local, propuestas puntuadas y generación múltiple. Disponible en Momentos con IA.</p></div></div><div><span className="roadmap-number ready">03</span><div><h3>Palabras con personalidad</h3><p>Subtítulos editables, estilos por palabra y capas para campañas.</p></div></div><div><span className="roadmap-number">04</span><div><h3>Un encuadre que te sigue</h3><p>Seguimiento de sujetos y exportaciones por lotes. Pendiente de implementar.</p></div></div></div></Modal>}
    {help && <Modal title="De tu vídeo a tu primer clip" onClose={() => setHelp(false)}><div className="help-content"><p><b>1. Importa.</b> Arrastra un archivo al editor o pulsa Importar vídeo. El original se copia a la biblioteca local.</p><p><b>2. Selecciona.</b> Ajusta Entrada y Salida en segundos o usa los controles de la línea de tiempo. La reproducción respeta ese intervalo.</p><p><b>3. Encuadra.</b> Elige una plataforma, formato y resolución. Usa Ajustar completo para conservar la imagen o Llenar y recortar para elegir un foco.</p><p><b>4. Exporta.</b> El motor prepara un MP4. En Exportaciones puedes revisar el resultado exacto antes de descargarlo.</p><div className="help-note"><ShieldCheck size={18}/><span>Los presets y márgenes son puntos de partida editables. Las guías no aparecen en el archivo final. En Momentos con IA puedes transcribir, revisar propuestas puntuadas y generar varios clips. Para añadir texto sincronizado, abre Subtítulos dinámicos.</span></div><p><button className="secondary" onClick={() => { setHelp(false); setRoadmap(true); }}>Ver plan de desarrollo</button></p></div></Modal>}
  </div>;
}
