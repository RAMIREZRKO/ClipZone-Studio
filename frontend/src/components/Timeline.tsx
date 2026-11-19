import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { Film, Minus, Plus } from 'lucide-react';
import { type Video } from '../api';
import { earliestClipEnd, formatTimecode, latestClipStart, roundTimelineTime } from '../timelineTime';

type Handle = 'cursor' | 'in' | 'out';
type Drag = { handle: Handle; pointerId: number; offset: number; frame: number };

export function Timeline({ video, start, end, current, title, seek, setIn, setOut }: {
  video: Video | null; start: number; end: number; current: number; title: string;
  seek: (value: number) => void; setIn: (value: number) => void; setOut: (value: number) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const viewport = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const duration = video?.duration || 60;
  const maxIn = latestClipStart(end);
  const minOut = earliestClipEnd(start, duration);
  const percent = (value: number) => `${value / duration * 100}%`;
  const following = useRef(true);
  const actions = useRef({ cursor: seek, in: setIn, out: setOut });

  useLayoutEffect(() => {
    actions.current = { cursor: seek, in: setIn, out: setOut };
  }, [seek, setIn, setOut]);

  useEffect(() => () => {
    if (drag.current) cancelAnimationFrame(drag.current.frame);
  }, []);

  useEffect(() => {
    const pane = viewport.current;
    const strip = track.current;
    if (!pane || !strip || drag.current || !following.current) return;
    const x = strip.offsetLeft + strip.clientLeft + (current / duration) * strip.clientWidth;
    if (x < pane.scrollLeft || x > pane.scrollLeft + pane.clientWidth - 12) {
      pane.scrollLeft = x - pane.clientWidth / 3;
    }
  }, [current, duration, zoom]);

  function changeZoom(next: number) {
    const pane = viewport.current;
    const strip = track.current;
    setZoom(next);
    following.current = true;
    requestAnimationFrame(() => {
      if (!pane || !strip) return;
      pane.scrollLeft = strip.offsetLeft + (current / duration) * strip.clientWidth - pane.clientWidth / 2;
    });
  }

  const handles = {
    cursor: { label: 'Posición de reproducción', value: current, min: 0, max: duration },
    in: { label: 'Ajustar entrada', value: start, min: 0, max: maxIn },
    out: { label: 'Ajustar salida', value: end, min: minOut, max: duration },
  };

  function move(handle: Handle, value: number) {
    const { min, max } = handles[handle];
    following.current = handle === 'cursor';
    const time = value >= duration ? duration : roundTimelineTime(value);
    actions.current[handle](Math.min(max, Math.max(min, time)));
  }

  function onHandleKey(event: KeyboardEvent, handle: Handle) {
    const { min, max, value } = handles[handle];
    const step = event.shiftKey ? 1 : 0.01;
    let next: number;
    switch (event.key) {
      case 'ArrowLeft': case 'ArrowDown': next = value - step; break;
      case 'ArrowRight': case 'ArrowUp': next = value + step; break;
      case 'Home': next = min; break;
      case 'End': next = max; break;
      default: return;
    }
    event.preventDefault();
    move(handle, next);
  }

  function timeAt(clientX: number, strip: HTMLDivElement) {
    const left = strip.getBoundingClientRect().left + strip.clientLeft;
    return (clientX - left) / strip.clientWidth * duration;
  }

  function beginDrag(event: PointerEvent<HTMLDivElement>) {
    if (!video || event.button !== 0 || drag.current) return;
    const strip = event.currentTarget;
    const grip = (event.target as Element).closest<HTMLDivElement>('[data-timeline-handle]');
    const handle = (grip?.dataset.timelineHandle ?? 'cursor') as Handle;
    const time = timeAt(event.clientX, strip);
    const offset = grip ? handles[handle].value - time : 0;
    event.preventDefault();
    (grip ?? strip.querySelector<HTMLDivElement>('[data-timeline-handle="cursor"]'))?.focus({ preventScroll: true });
    strip.setPointerCapture(event.pointerId);
    drag.current = { handle, pointerId: event.pointerId, offset, frame: 0 };
    if (!grip) move(handle, time);
  }

  function continueDrag(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    const pane = viewport.current;
    const strip = event.currentTarget;
    if (!pane) return;
    const { left, right } = pane.getBoundingClientRect();
    const x = Math.min(right, Math.max(left, event.clientX));
    const pan = x < left + 24 ? -12 : x > right - 24 ? 12 : 0;
    cancelAnimationFrame(active.frame);
    move(active.handle, timeAt(x, strip) + active.offset);
    if (!pan || zoom === 1) return;
    const panWhileDragging = () => {
      if (drag.current !== active) return;
      const previous = pane.scrollLeft;
      pane.scrollLeft += pan;
      if (pane.scrollLeft === previous) return;
      move(active.handle, timeAt(x, strip) + active.offset);
      active.frame = requestAnimationFrame(panWhileDragging);
    };
    active.frame = requestAnimationFrame(panWhileDragging);
  }

  function stopDrag(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    cancelAnimationFrame(drag.current.frame);
    drag.current = null;
  }

  function renderHandle(handle: Handle) {
    const { label, min, max, value } = handles[handle];
    return <div role="slider" tabIndex={0} className={`timeline-handle ${handle}`}
      data-timeline-handle={handle} aria-label={label} aria-valuemin={min} aria-valuemax={max}
      aria-valuenow={value} aria-valuetext={formatTimecode(value, true)} title={label}
      style={{ left: percent(value) }} onKeyDown={event => onHandleKey(event, handle)}/>;
  }

  // Choose whole centisecond intervals so the ruler stays readable at every zoom level.
  const targetTick = duration / (4 * zoom);
  const tickUnit = 10 ** Math.floor(Math.log10(Math.max(targetTick, 0.01)));
  const tickStep = ([1, 2, 5, 10].find(value => value * tickUnit >= targetTick) ?? 1) * tickUnit;
  const ticks = Array.from({ length: Math.ceil(duration / tickStep - 0.35) }, (_, i) => i * tickStep);
  if (ticks[0] !== 0) ticks.unshift(0);
  ticks.push(duration);

  const cursorTime = Math.min(duration, roundTimelineTime(current));
  return <>
    <div className="timeline-tools">
      <dl className="timeline-times">
        <div><dt>Entrada</dt><dd>{formatTimecode(video ? start : 0, true)}</dd></div>
        <div className="timeline-current"><dt>Cursor</dt><dd>{formatTimecode(video ? current : 0, true)}</dd></div>
        <div><dt>Salida</dt><dd>{formatTimecode(video ? end : 0, true)}</dd></div>
      </dl>
      <div className="timeline-zoom">
        <button type="button" className="icon-button" title="Alejar línea de tiempo" aria-label="Alejar línea de tiempo" disabled={zoom === 1} onClick={() => changeZoom(zoom / 2)}><Minus size={17}/></button>
        <output aria-label="Zoom de línea de tiempo">{zoom}×</output>
        <button type="button" className="icon-button" title="Acercar línea de tiempo" aria-label="Acercar línea de tiempo" disabled={!video || zoom === 32} onClick={() => changeZoom(zoom * 2)}><Plus size={17}/></button>
      </div>
    </div>
    <div ref={viewport} className="timeline-viewport" onWheel={event => { if (event.deltaX || event.shiftKey) following.current = false; }}>
      <div ref={track} className={`timeline-track ${video ? 'ready' : ''}`} style={{ width: `calc(${zoom * 100}% - 32px)`,
        backgroundImage: video ? `linear-gradient(#0d130e88,#0d130e88),url("${video.thumbnail_url}")` : undefined }}
        onPointerDown={beginDrag} onPointerMove={continueDrag} onLostPointerCapture={stopDrag}>
        <div className="timeline-ruler" aria-hidden="true">{ticks.map(value =>
          <span key={value} style={{ left: percent(value) }}>{formatTimecode(value, tickStep < 1)}</span>
        )}</div>
        {video ? <>
          <div className="timeline-selection" style={{ left: percent(start), width: percent(end - start) }}><span className="selection-title">{title}</span></div>
          <div className="playhead" aria-hidden="true" style={{ left: percent(current) }}/>
          {renderHandle('in')}
          {renderHandle('cursor')}
          {renderHandle('out')}
        </> : <div className="timeline-empty"><Film size={15}/>Tu vídeo aparecerá aquí</div>}
      </div>
    </div>
    <div className="timeline-actions">
      <button type="button" className="secondary" disabled={!video || cursorTime > maxIn} onClick={() => setIn(cursorTime)}>Marcar entrada aquí</button>
      <button type="button" className="secondary" disabled={!video || cursorTime < minOut} onClick={() => setOut(cursorTime)}>Marcar salida aquí</button>
      {video && <details className="timeline-precision">
        <summary>Ajuste de precisión</summary>
        <div className="timeline-precision-fields">
          <label>Entrada (s)<input aria-label="Entrada en segundos" type="number" min={0} max={maxIn} step="0.01"
            value={roundTimelineTime(start)} onChange={event => setIn(event.target.valueAsNumber)}/></label>
          <label>Salida (s)<input aria-label="Salida en segundos" type="number" min={minOut} max={duration} step="0.01"
            value={roundTimelineTime(end)} onChange={event => setOut(event.target.valueAsNumber)}/></label>
        </div>
        <p>Flechas sobre un control: 0,01 s. Mayús + flecha: 1 s.</p>
      </details>}
    </div>
  </>;
}

