import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowRight, Check, CheckCheck, ChevronDown, ChevronRight, CircleHelp, Clapperboard, Clock3, Crop, Download, Film, FolderOpen, Frame, HardDrive, LayoutGrid, LoaderCircle, Maximize, Monitor, Pause, Play, Plus, Scissors, Settings2, ShieldCheck, SkipBack, Upload, Volume2, VolumeX, WandSparkles, X } from 'lucide-react';
import { request, seconds, sizeLabel, uploadVideo, type ClipSettings, type Health, type Job, type Video } from './api';
import { Modal } from './components/Modal';
import { ratios, presets, statusLabel } from './presets';
import { AnalysisPanel } from './components/AnalysisPanel';

type View = 'editor' | 'library' | 'exports';

export default function App() {
  const [view, setView] = useState<View>('editor');
  const [videos, setVideos] = useState<Video[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [start, setStart] = useState(0); const [end, setEnd] = useState(30);
  const [title, setTitle] = useState('Mi primer clip');
  const [platform, setPlatform] = useState('tiktok'); const [ratio, setRatio] = useState('9:16');
  const [resolution, setResolution] = useState(1080); const [fit, setFit] = useState<'contain' | 'cover'>('contain');
  const [safeTop, setSafeTop] = useState(10); const [safeBottom, setSafeBottom] = useState(22);
  const [focusX, setFocusX] = useState(50); const [focusY, setFocusY] = useState(50);
  const [guides, setGuides] = useState(true); const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false); const [current, setCurrent] = useState(0);
  const [uploading, setUploading] = useState<number | null>(null); const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [roadmap, setRoadmap] = useState(false); const [help, setHelp] = useState(false);
  const [preview, setPreview] = useState<Job | null>(null); const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null); const player = useRef<HTMLVideoElement>(null);
  const selected = videos.find(v => v.id === selectedId) || null;
  const exports = jobs.filter(j => j.kind === 'export');
  const active = exports.filter(j => j.status === 'queued' || j.status === 'running');
  const canExport = !!selected && health?.status === 'ok' && end - start >= 0.1 && end <= selected.duration + 0.01 && end - start <= 3600;

  const refresh = useCallback(async () => {
    const [h, v, j] = await Promise.all([request<Health>('/health'), request<Video[]>('/videos'), request<Job[]>('/jobs')]);
    setHealth(h); setVideos(v); setJobs(j);
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
    player.current?.pause(); setPlaying(false); setSelectedId(video.id); setStart(0);
    setEnd(Math.min(presets[platform].duration, video.duration)); setCurrent(0);
    setTitle(`${video.name.replace(/\.[^.]+$/, '')} · clip 01`.slice(0, 100)); setView('editor'); setError('');
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
    if (player.current) player.current.currentTime = clamped; setCurrent(clamped);
  }
  async function togglePlay() {
    if (!player.current) return;
    if (playing) { player.current.pause(); return; }
    if (current < start || current >= end) seek(start);
    try { await player.current.play(); } catch { setError('No se pudo reproducir. Prueba otro vídeo o vuelve a cargar la página.'); }
  }
  function setIn(value: number) {
    const next = Math.max(0, Math.min(value, end - 0.1)); setStart(next); seek(next);
  }
  function setOut(value: number) {
    if (!selected) return;
    setEnd(Math.max(start + 0.1, Math.min(value, selected.duration)));
  }
  function applyPlatform(key: string) {
    const p = presets[key]; setPlatform(key); setRatio(p.ratio); setSafeTop(p.top); setSafeBottom(p.bottom);
    if (selected) setEnd(Math.min(selected.duration, start + p.duration));
  }
  async function exportClip() {
    if (!canExport || !selected || submitting) return;
    setSubmitting(true); setError('');
    const body: ClipSettings = { video_id: selected.id, title: title.trim() || 'Mi clip', start, end, ratio, resolution, fit, platform,
      safe_top: safeTop, safe_bottom: safeBottom, focus_x: focusX, focus_y: focusY };
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
  const ratioNumber = Number(ratio.split(':')[0]) / Number(ratio.split(':')[1]);
  const outputWidth = ratioNumber > 1 ? Math.round(resolution * ratioNumber / 2) * 2 : resolution;
  const outputHeight = ratioNumber > 1 ? resolution : Math.round(resolution / ratioNumber / 2) * 2;

  return <div className="app-shell">
    <input ref={input} type="file" className="sr-only" aria-label="Seleccionar vídeo" accept=".mp4,.mov,.mkv,.webm,.avi,.m4v,.mts,.m2ts" onChange={e => void importFile(e.target.files?.[0])}/>
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => { e.preventDefault(); setView('editor'); }}><div className="brand-mark"><Scissors size={23}/></div><span>clipzone<span className="brand-sub">STUDIO</span></span></a>
      <button className="primary sidebar-import" onClick={() => input.current?.click()} disabled={uploading !== null}><Plus size={18}/>Importar vídeo</button>
      <span className="nav-label">ESPACIO DE TRABAJO</span>
      <nav aria-label="Principal">
        <button className={`nav-item ${view === 'editor' ? 'selected' : ''}`} onClick={() => setView('editor')}><Clapperboard size={18}/>Editor de clips<ChevronRight size={14} className="nav-chevron"/></button>
        <button className={`nav-item ${view === 'library' ? 'selected' : ''}`} onClick={() => setView('library')}><FolderOpen size={18}/>Mis vídeos<span className="count">{videos.length}</span></button>
        <button className={`nav-item ${view === 'exports' ? 'selected' : ''}`} onClick={() => setView('exports')}><ArrowDownToLine size={18}/>Exportaciones{active.length > 0 ? <span className="activity-dot"/> : <span className="count">{exports.length}</span>}</button>
      </nav>
      <div className="nav-divider"/><span className="nav-label">INTELIGENCIA LOCAL</span>
      <button className="nav-item ai-nav" onClick={() => { setView('editor'); window.setTimeout(() => document.getElementById('ai-moments')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 40); }}><WandSparkles size={18}/>Momentos con IA<span className="tiny-tag">F2</span></button>
      <button className="nav-item upcoming" onClick={() => setRoadmap(true)}><Frame size={18}/>Subtítulos dinámicos<span className="tiny-tag">F3</span></button>
      <div className="sidebar-bottom"><div className="local-card"><div className="local-card-icon"><ShieldCheck size={18}/><span>Tu equipo. Tus archivos.</span></div><p>Procesamiento local.<br/>Sin suscripciones.</p><div className="local-line"><span className="activity-dot"/> MODO LOCAL</div></div>
        <button className="nav-item help-button" onClick={() => setHelp(true)}><CircleHelp size={18}/>Guía de inicio<ArrowRight size={14}/></button>
        <div className="profile"><div className="avatar">CZ</div><div><strong>Mi espacio local</strong><span>ClipZone Studio · v0.2</span></div><Monitor size={16}/></div>
      </div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="breadcrumbs"><LayoutGrid size={16}/><span>Mi espacio</span><ChevronRight size={13}/><strong>{view === 'editor' ? 'Editor de clips' : view === 'library' ? 'Mis vídeos' : 'Exportaciones'}</strong></div><div className="topbar-right"><span className="version-tag">FASE 02</span><span className={`server-status ${health?.status === 'ok' ? 'online' : ''}`}><i/>{health?.status === 'ok' ? 'Motor local listo' : health ? 'Faltan dependencias' : 'Sin conexión'}</span></div></header>
      <main onDragOver={e => { e.preventDefault(); if (e.dataTransfer.types.includes('Files')) setDragging(true); }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }} onDrop={e => { e.preventDefault(); setDragging(false); void importFile(e.dataTransfer.files[0]); }}>
        {dragging && <div className="drop-overlay"><Upload size={40}/><h2>Suelta tu próximo gran vídeo</h2><span>Se procesará en este equipo</span></div>}
        <div className="page-heading"><div><div className="eyebrow"><span/>{view === 'editor' ? 'CREA. RECORTA. COMPARTE.' : view === 'library' ? 'TU BIBLIOTECA LOCAL' : 'CONTENIDO LISTO PARA SALIR'}</div><h1>{view === 'editor' ? 'Un vídeo. Más posibilidades.' : view === 'library' ? 'Todo empieza por aquí.' : 'Tus próximos grandes clips.'}</h1><p>{view === 'editor' ? 'Encuentra el momento. Dale tu formato. Hazlo tuyo.' : view === 'library' ? 'Tus originales, siempre a mano para crear algo nuevo.' : 'Revisa el resultado y descarga tus clips cuando estén listos.'}</p></div><div className="heading-action">{view === 'editor' ? <><div className="step done"><span>01</span>Importa</div><div className="step-line"/><div className={`step ${selected ? 'done' : ''}`}><span>02</span>Edita</div><div className="step-line"/><div className="step"><span>03</span>Exporta</div></> : <button className="secondary" onClick={() => setView('editor')}><ArrowLeft size={16}/>Volver al editor</button>}</div></div>
        {error && <div className="alert error" role="alert"><CircleHelp size={17}/><span>{error}</span><button onClick={() => setError('')} aria-label="Cerrar error"><X size={16}/></button></div>}
        {notice && <div className="toast" role="status"><CheckCheck size={17}/>{notice}<button onClick={() => setNotice('')} aria-label="Cerrar aviso"><X size={15}/></button></div>}
        {health && health.status !== 'ok' && <div className="alert warning"><Settings2 size={17}/><span>Falta FFmpeg o FFprobe. Ejecuta <code>scripts/setup.ps1 -DownloadFFmpeg</code> y reinicia el servidor.</span></div>}
        {view === 'editor' && <>
          <div className="editor-grid">
<div className="editor-left">
            <section className="preview-panel panel">
              <div className="panel-heading"><div><span className="green-icon"><Play size={15}/></span><h2>Vista previa</h2><span className="small-tag">{ratio}</span></div><button className={`icon-button ${guides ? 'active-icon' : ''}`} onClick={() => setGuides(!guides)} title="Mostrar u ocultar zona segura" aria-label="Mostrar u ocultar zona segura" aria-pressed={guides}><Frame size={17}/></button></div>
              <div className={`stage ${selected ? 'has-video' : ''}`}>
                {selected ? <>
                  <div className="stage-label"><span className="activity-dot"/> ORIGINAL · {selected.width} × {selected.height}</div>
                  <div className="video-frame" style={{ aspectRatio: ratioNumber, width: `min(100%, calc(var(--preview-height) * ${ratioNumber}))` }}>
                    {selected.preview_status === 'ready' && selected.preview_url ? <video ref={player} src={selected.preview_url} muted={muted} playsInline preload="metadata" style={{ objectFit: fit, objectPosition: fit === 'cover' ? `${focusX}% ${focusY}%` : '50% 50%' }} onLoadedMetadata={() => { if (player.current) player.current.currentTime = start; }} onTimeUpdate={() => { const p = player.current; if (!p) return; if (p.currentTime >= end) { p.pause(); p.currentTime = end; } setCurrent(p.currentTime); }} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onClick={() => void togglePlay()} onError={() => setError('El navegador no pudo leer la vista previa. Reimporta el vídeo para generar un nuevo archivo.')}/>
                    : <div className="processing-preview">{selected.preview_status === 'processing' ? <><LoaderCircle className="spin" size={25}/><span>Preparando vista previa…</span><small>Puedes configurar y exportar mientras tanto.</small></> : <><CircleHelp size={24}/><span>No se pudo crear la vista previa.</span><small>Puedes intentar exportar el original.</small></>}</div>}
                    {guides && <div className="safe-guides" style={{ top: `${safeTop}%`, bottom: `${safeBottom}%` }}><span>ZONA SEGURA</span><div className="safe-caption">Guía de subtítulos</div></div>}
                  </div>
                  <div className="stage-footnote">{fit === 'contain' ? 'Imagen completa · sin deformación' : 'Recorte para llenar · sin deformación'}</div>
                </> : <div className="empty-stage"><div className="stage-corner tl"/><div className="stage-corner tr"/><div className="stage-corner bl"/><div className="stage-corner br"/><div className="upload-illustration"><div className="film-back"/><div className="film-front"><Film size={35}/></div><span><Plus size={17}/></span></div><h3>Tu próximo clip empieza aquí</h3><p>Arrastra un vídeo o búscalo en tu equipo.<br/>Los mejores momentos ya están dentro.</p><button className="primary" onClick={() => input.current?.click()} disabled={uploading !== null}>{uploading !== null ? <LoaderCircle className="spin" size={16}/> : <Upload size={16}/>} {uploading === null ? 'Seleccionar vídeo' : uploading < 100 ? `Importando ${uploading}%` : 'Analizando vídeo…'}</button><span className="file-formats">MP4, MOV, MKV, WebM y más · Hasta {health ? Math.round(health.max_upload_bytes / 1024 ** 3) : 20} GB</span></div>}
              </div>
              <div className="transport"><div className="transport-left"><button className="icon-button" disabled={!selected} onClick={() => seek(start)} aria-label="Ir al inicio del clip"><SkipBack size={17}/></button><button className="play-button" aria-label={playing ? 'Pausar' : 'Reproducir clip'} disabled={selected?.preview_status !== 'ready'} onClick={() => void togglePlay()}>{playing ? <Pause size={17} fill="currentColor"/> : <Play size={17} fill="currentColor"/>}</button><button className="icon-button" disabled={!selected} onClick={() => setMuted(!muted)} aria-label={muted ? 'Activar sonido' : 'Silenciar'}>{muted ? <VolumeX size={17}/> : <Volume2 size={17}/>}</button></div><div className="timecode"><strong>{seconds(current)}</strong><span>/</span>{seconds(selected?.duration || 0)}</div><button className="icon-button" disabled={!selected} aria-label="Pantalla completa del vídeo original" onClick={() => { void player.current?.requestFullscreen(); }}><Maximize size={16}/></button></div>
            </section>
            <section className="timeline-panel panel"><div className="panel-heading"><div><Scissors size={17}/><h2>Elige tu momento</h2></div><div className="duration-badge"><Clock3 size={13}/>{(selected ? end - start : 0).toFixed(1)} s seleccionados</div></div><div className="timeline-body"><div className="clip-fields"><label className="clip-title">Nombre del clip<input value={title} maxLength={100} onChange={e => setTitle(e.target.value)} placeholder="Nombre del clip"/></label><label>Entrada (s)<input aria-label="Entrada en segundos" type="number" min="0" max={Math.max(0, end - 0.1)} step="0.1" value={+start.toFixed(2)} disabled={!selected} onChange={e => setIn(+e.target.value)}/></label><span className="field-arrow"><ArrowRight size={16}/></span><label>Salida (s)<input aria-label="Salida en segundos" type="number" min={start + 0.1} max={selected?.duration} step="0.1" value={+end.toFixed(2)} disabled={!selected} onChange={e => setOut(+e.target.value)}/></label></div>
              <div className={`timeline-track ${selected ? 'ready' : ''}`} onClick={e => { if (selected) { const rect = e.currentTarget.getBoundingClientRect(); seek((e.clientX - rect.left) / rect.width * selected.duration); } }} style={selected ? { backgroundImage: `linear-gradient(#0d130e88,#0d130e88),url("${selected.thumbnail_url}")` } : {}}><div className="timeline-ruler">{[0, .25, .5, .75, 1].map(v => <span key={v}>{seconds((selected?.duration || 60) * v)}</span>)}</div>{selected ? <><div className="timeline-selection" style={{ left: `${start / selected.duration * 100}%`, width: `${(end - start) / selected.duration * 100}%` }}><span className="trim-grip left"/><span className="selection-title">{title}</span><span className="trim-grip right"/></div><div className="playhead" style={{ left: `${current / selected.duration * 100}%` }}/></> : <div className="timeline-empty"><Film size={15}/>Tu vídeo aparecerá aquí</div>}</div>
              <div className="trim-sliders"><label>Entrada<input aria-label="Recortar inicio" type="range" min="0" max={selected?.duration || 1} step="0.01" value={start} disabled={!selected} onChange={e => setIn(+e.target.value)}/></label><label>Salida<input aria-label="Recortar final" type="range" min="0" max={selected?.duration || 1} step="0.01" value={selected ? end : 1} disabled={!selected} onChange={e => setOut(+e.target.value)}/></label></div>
              <div className="timeline-bottom"><div className="quick-durations"><span>Duración rápida</span>{[15, 30, 60].map(d => <button key={d} disabled={!selected} onClick={() => { if (selected) setEnd(Math.min(selected.duration, start + d)); }}>{d} s</button>)}<button disabled={!selected} onClick={() => { if (selected) { setStart(0); setEnd(selected.duration); seek(0); } }}>Completo</button></div><span className="keyboard-hint">Ajuste preciso en segundos</span></div>
            </div></section>
</div>
<div className="editor-right">
            <aside className="settings-panel panel">
              <div className="panel-heading"><div><Settings2 size={17}/><h2>Configura tu clip</h2></div><span className="small-tag">MP4</span></div>
              <div className="settings-body"><section className="setting-section"><div className="field-heading"><label>Destino</label><span>Preset de edición</span></div><div className="platform-grid">{Object.entries(presets).filter(([key]) => key !== 'custom').map(([key, p]) => <button key={key} className={platform === key ? 'chosen' : ''} onClick={() => applyPlatform(key)} aria-pressed={platform === key}><b>{p.symbol}</b>{p.label}</button>)}</div><button className={`custom-preset ${platform === 'custom' ? 'chosen' : ''}`} onClick={() => applyPlatform('custom')} aria-pressed={platform === 'custom'}>↗ Formato libre</button></section>
                <section className="setting-section"><div className="field-heading"><label>Formato</label><span>Relación de aspecto</span></div><div className="ratio-grid">{ratios.map(r => <button key={r} className={ratio === r ? 'chosen' : ''} onClick={() => setRatio(r)} aria-pressed={ratio === r}><span className="ratio-shape" style={{ aspectRatio: r.replace(':', ' / ') }}/><span>{r}</span>{ratio === r && <Check size={11} className="ratio-check"/>}</button>)}</div></section>
                <section className="setting-section"><div className="field-heading"><label>Encuadre</label><Crop size={14}/></div><div className="segmented"><button className={fit === 'contain' ? 'chosen' : ''} onClick={() => setFit('contain')}>Ajustar completo</button><button className={fit === 'cover' ? 'chosen' : ''} onClick={() => setFit('cover')}>Llenar y recortar</button></div>{fit === 'cover' && <div className="focus-controls"><label>Foco horizontal <input aria-label="Foco horizontal" type="range" min="0" max="100" value={focusX} onChange={e => setFocusX(+e.target.value)}/></label><label>Foco vertical <input aria-label="Foco vertical" type="range" min="0" max="100" value={focusY} onChange={e => setFocusY(+e.target.value)}/></label></div>}<p className="field-note">{fit === 'contain' ? 'Conserva toda la imagen con bandas negras.' : 'Desplaza el foco para elegir qué parte conservar.'}</p></section>
                <section className="setting-section resolution-row"><label htmlFor="resolution">Resolución</label><div className="select-wrap"><select id="resolution" value={resolution} onChange={e => setResolution(+e.target.value)}><option value={1080}>1080p · Full HD</option><option value={720}>720p · HD</option><option value={480}>480p · Ligero</option></select><ChevronDown size={13}/></div></section>
                <section className="setting-section safe-section"><div className="field-heading"><label htmlFor="safe-guides">Zona segura de subtítulos</label><button id="safe-guides" role="switch" aria-checked={guides} aria-label="Guías de zona segura" className={`switch ${guides ? 'on' : ''}`} onClick={() => setGuides(!guides)}><span/></button></div><div className="safe-inputs"><label>Superior<div><input aria-label="Margen superior" type="number" min="0" max="35" value={safeTop} onChange={e => setSafeTop(Math.min(35, Math.max(0, +e.target.value)))}/><span>%</span></div></label><label>Inferior<div><input aria-label="Margen inferior" type="number" min="0" max="40" value={safeBottom} onChange={e => setSafeBottom(Math.min(40, Math.max(0, +e.target.value)))}/><span>%</span></div></label></div><p className="field-note">Guías orientativas, no se imprimen en el vídeo.<br/>Los subtítulos llegan en la fase 3.</p></section>
              </div>
            </aside>
            <div className="export-panel panel"><div className="export-summary"><div className="export-icon"><Download size={20}/></div><div><strong>Listo para tu siguiente historia</strong><span>{outputWidth} × {outputHeight} · H.264 + AAC · MP4</span></div></div><button className="primary export-button" disabled={!canExport || submitting} onClick={() => void exportClip()}>{submitting ? <LoaderCircle className="spin" size={17}/> : <ArrowDownToLine size={17}/>}Exportar clip<ArrowRight size={16}/></button><span className="export-note"><HardDrive size={12}/>Se guarda en este equipo</span></div>
</div>
          </div>
          <AnalysisPanel video={selected} output={{ ratio, resolution, fit, platform, safe_top: safeTop, safe_bottom: safeBottom, focus_x: focusX, focus_y: focusY }}
            onChoose={moment => { player.current?.pause(); setPlaying(false); setStart(moment.start); setEnd(moment.end); setTitle(moment.title.slice(0, 100)); seek(moment.start); document.querySelector('.preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }}
            onExported={newJobs => { setJobs(previous => [...newJobs, ...previous.filter(j => !newJobs.some(n => n.id === j.id))]); setView('exports'); setNotice(`${newJobs.length} clips en cola. Puedes revisar cada MP4 antes de descargarlo.`); window.scrollTo({ top: 0, behavior: 'smooth' }); }}/>
          <section className="source-strip"><div><FolderOpen size={16}/><h2>Vídeos del proyecto</h2><span>{videos.length}</span></div>{videos.length > 0 ? <div className="source-chips">{videos.slice(0, 5).map(v => <button key={v.id} className={v.id === selectedId ? 'active' : ''} onClick={() => selectVideo(v)}><Film size={14}/><span>{v.name}</span><small>{seconds(v.duration)}</small></button>)}</div> : <p>Importa tu primer original y empieza a crear.</p>}<button className="text-button" disabled={uploading !== null} onClick={() => input.current?.click()}><Plus size={15}/>Añadir vídeo</button></section>
        </>}
        {view === 'library' && <section className="library-grid">{videos.length ? videos.map(v => <button className="video-card panel" key={v.id} onClick={() => selectVideo(v)}><div className="video-thumb"><img src={v.thumbnail_url} alt=""/><span>{seconds(v.duration)}</span><div className="thumb-play"><Play size={24}/></div></div><div className="video-card-body"><h3>{v.name}</h3><p>{v.width} × {v.height} <span>·</span> {sizeLabel(v.size)}</p><div><span className="small-tag">{v.codec.toUpperCase()}</span><span>Abrir en el editor <ArrowRight size={13}/></span></div></div></button>) : <div className="empty-page panel"><FolderOpen size={36}/><h2>Un espacio para tus originales</h2><p>Importa un vídeo largo para crear tu primer clip.</p><button className="primary" onClick={() => input.current?.click()}><Plus size={16}/>Importar vídeo</button></div>}</section>}
        {view === 'exports' && <section className="exports-list"><div className="list-heading"><h2>Cola de exportación <span>{exports.length}</span></h2><span><span className="activity-dot"/>{active.length ? `${active.length} en proceso · uno a la vez` : 'Todo al día'}</span></div>{exports.length ? exports.map(job => <article key={job.id} className={`export-card panel ${job.status}`}><div className="export-card-icon">{job.status === 'completed' ? <Check size={24}/> : job.status === 'running' ? <LoaderCircle size={23} className="spin"/> : job.status === 'failed' ? <CircleHelp size={24}/> : <Film size={24}/>}</div><div className="export-card-info"><h3>{job.title}</h3><p>{job.settings?.ratio} <span>·</span> {job.settings?.resolution}p <span>·</span> {((job.settings?.end || 0) - (job.settings?.start || 0)).toFixed(1)} s <span>·</span> {presets[job.settings?.platform || 'custom'].label}</p><div className="job-status"><span>{statusLabel[job.status]}</span>{job.status === 'running' && <><div className="progress-track"><div style={{ width: `${job.progress}%` }}/></div><b>{job.progress}%</b></>}{job.size && <small>{sizeLabel(job.size)}</small>}</div>{job.error && <p className="job-error">{job.error}</p>}</div><div className="export-card-actions">{job.status === 'completed' ? <><button className="secondary" onClick={() => setPreview(job)}><Play size={15}/>Previsualizar</button><a className="primary" href={job.download_url!} download><Download size={15}/>Descargar</a></> : (job.status === 'running' || job.status === 'queued') ? <button className="secondary" onClick={() => void cancelJob(job.id)}><X size={14}/>Cancelar</button> : <button className="secondary" onClick={() => { const v = videos.find(v => v.id === job.video_id); if (v) { selectVideo(v); if (job.settings) { const s = job.settings; setStart(s.start); setEnd(s.end); setRatio(s.ratio); setFit(s.fit); setResolution(s.resolution); setPlatform(s.platform); setSafeTop(s.safe_top); setSafeBottom(s.safe_bottom); setFocusX(s.focus_x); setFocusY(s.focus_y); setTitle(s.title); } } }}>Volver a editar</button>}</div></article>) : <div className="empty-page panel"><Clapperboard size={38}/><h2>El próximo clip puede ser el tuyo</h2><p>Selecciona un momento en el editor y pulsa Exportar clip.</p><button className="primary" onClick={() => setView('editor')}>Ir al editor<ArrowRight size={16}/></button></div>}</section>}
        <footer className="workspace-footer"><span><ShieldCheck size={13}/>Hecho para crear. Diseñado para quedarse en tu equipo.</span><span>CLIPZONE STUDIO <i/> EDICIÓN LOCAL</span></footer>
      </main>
    </div>
    {uploading !== null && <div className="upload-toast" role="status"><LoaderCircle className="spin" size={19}/><div><strong>{uploading < 100 ? `Importando vídeo · ${uploading}%` : 'Verificando vídeo y miniatura…'}</strong><div className="progress-track"><div style={{ width: `${uploading}%` }}/></div></div></div>}
    {preview && <Modal title={preview.title} onClose={() => setPreview(null)}><video className="export-preview" src={preview.preview_url!} controls autoPlay playsInline/><div className="modal-footer"><span>Así se verá tu archivo exportado.</span><a className="primary" href={preview.download_url!} download><Download size={16}/>Descargar MP4</a></div></Modal>}
    {roadmap && <Modal title="Más posibilidades, por fases" onClose={() => setRoadmap(false)}><div className="roadmap"><div><span className="roadmap-number ready">01</span><div><h3>Tu editor local <span className="small-tag">DISPONIBLE</span></h3><p>Importa, recorta, encuadra y exporta. Sin servicios de pago.</p></div></div><div><span className="roadmap-number ready">02</span><div><h3>Encuentra los mejores momentos</h3><p>Transcripción con Whisper local, propuestas puntuadas y generación múltiple. Disponible en Momentos con IA.</p></div></div><div><span className="roadmap-number">03</span><div><h3>Palabras con personalidad</h3><p>Subtítulos dinámicos por palabra, estilos y zonas seguras. Pendiente de implementar.</p></div></div><div><span className="roadmap-number">04</span><div><h3>Un encuadre que te sigue</h3><p>Seguimiento de sujetos y exportaciones por lotes. Pendiente de implementar.</p></div></div></div></Modal>}
    {help && <Modal title="De tu vídeo a tu primer clip" onClose={() => setHelp(false)}><div className="help-content"><p><b>1. Importa.</b> Arrastra un archivo al editor o pulsa Importar vídeo. El original se copia a la biblioteca local.</p><p><b>2. Selecciona.</b> Ajusta Entrada y Salida en segundos o usa los controles de la línea de tiempo. La reproducción respeta ese intervalo.</p><p><b>3. Encuadra.</b> Elige una plataforma, formato y resolución. Usa Ajustar completo para conservar la imagen o Llenar y recortar para elegir un foco.</p><p><b>4. Exporta.</b> El motor prepara un MP4. En Exportaciones puedes revisar el resultado exacto antes de descargarlo.</p><div className="help-note"><ShieldCheck size={18}/><span>Los presets y márgenes son puntos de partida editables. Las guías no aparecen en el archivo final. En Momentos con IA puedes transcribir, revisar propuestas puntuadas y generar varios clips. Los subtítulos llegan en la fase 3.</span></div></div></Modal>}
  </div>;
}
