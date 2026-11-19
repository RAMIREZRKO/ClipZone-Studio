import { useLayoutEffect, useRef, useState, type PointerEvent, type RefObject } from 'react';
import type { SourceGeometry, SourceRect, SplitLayout, SplitRegion } from '../api';
import { decodedCrop, type PanelGeometry, type SplitGeometry } from '../splitFramingGeometry';
import { NumericInput } from './NumericInput';

type RegionKey = 'camera' | 'gameplay';
type Corner = 'nw' | 'ne' | 'sw' | 'se';
const regionNames = { camera: 'Cámara', gameplay: 'Gameplay' };
const regionKeys = ['camera', 'gameplay'] as const;
const corners = ['nw', 'ne', 'sw', 'se'] as const;
const shares = [20, 25, 30, 40, 50];
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const roundRect = (value: number) => Math.round(value * 10000) / 10000;
const floorRect = (value: number) => Math.floor((value + 1e-9) * 10000) / 10000;
const minSize = .02;

export const defaultSplitLayout: SplitLayout = {
  camera_share: 25, inverted: false,
  camera: { rect: { x: .02, y: .02, width: .26, height: .26 }, zoom: 100, pan_x: 0, pan_y: 0 },
  gameplay: { rect: { x: 0, y: 0, width: 1, height: 1 }, zoom: 100, pan_x: 0, pan_y: 0 },
};

export function normalizeSplitLayout(layout: SplitLayout | null | undefined): SplitLayout {
  if (!layout) return defaultSplitLayout;
  const region = ({ rect, zoom, pan_x, pan_y }: SplitRegion): SplitRegion => ({ rect, zoom, pan_x, pan_y });
  return { camera_share: layout.camera_share, inverted: layout.inverted, camera: region(layout.camera), gameplay: region(layout.gameplay) };
}

export function SplitControls({ layout, onChange, onPreview, selected, onSelect, onEditSource, canEdit }: {
  layout: SplitLayout; onChange: (layout: SplitLayout) => void; onPreview: (layout: SplitLayout | null) => void;
  selected: RegionKey; onSelect: (key: RegionKey) => void;
  onEditSource: () => void; canEdit: boolean;
}) {
  const [custom, setCustom] = useState(false);
  const region = layout[selected];
  const rect = region.rect;
  const withRegion = (patch: Partial<SplitRegion>) => ({ ...layout, [selected]: { ...region, ...patch } });
  const previewNumber = (apply: (value: number) => SplitLayout) => ({
    onCommit: (value: number) => onChange(apply(value)),
    onPreview: (value: number | null) => onPreview(value === null ? null : apply(value)),
  });
  const distribution = custom || !shares.includes(layout.camera_share) ? 'custom' : String(layout.camera_share);
  return <div className="split-controls">
    <label>Distribución vertical<select value={distribution} onChange={event => {
      setCustom(event.target.value === 'custom');
      if (event.target.value !== 'custom') onChange({ ...layout, camera_share: Number(event.target.value) });
    }}>
      {shares.map(share => <option key={share} value={share}>{share}% cámara / {100 - share}% gameplay</option>)}
      <option value="custom">Distribución personalizada</option>
    </select></label>
    {distribution === 'custom' && <label>Altura de cámara (%)<NumericInput min={10} max={90} precision={1} step={1}
      value={layout.camera_share} {...previewNumber(camera_share => ({ ...layout, camera_share }))}/></label>}
    <label className="split-invert"><input type="checkbox" checked={layout.inverted}
      onChange={event => onChange({ ...layout, inverted: event.target.checked })}/>Invertir cámara y gameplay</label>
    <div className="split-region-tabs" role="group" aria-label="Región que se ajusta">
      {regionKeys.map(key => <button type="button" className="secondary" aria-pressed={key === selected}
        onClick={() => onSelect(key)} key={key}>{regionNames[key]}</button>)}
    </div>
    <button type="button" className="secondary" disabled={!canEdit} onClick={onEditSource}>Editar regiones en Original</button>
    <div className="split-fields">
      <label>Zoom (%)<NumericInput min={100} max={300} value={region.zoom} {...previewNumber(zoom => withRegion({ zoom }))}/></label>
      <label>Centro horizontal del recorte
        <NumericInput min={-100} max={100} value={region.pan_x} {...previewNumber(pan_x => withRegion({ pan_x }))}/></label>
      <label>Centro vertical del recorte
        <NumericInput min={-100} max={100} value={region.pan_y} {...previewNumber(pan_y => withRegion({ pan_y }))}/></label>
    </div>
    <details>
      <summary>Coordenadas del recorte</summary>
      <div className="split-fields">
        {([
          ['x', 'X (%)', 0, 1 - rect.width], ['y', 'Y (%)', 0, 1 - rect.height],
          ['width', 'Ancho (%)', minSize, 1 - rect.x], ['height', 'Alto (%)', minSize, 1 - rect.y],
        ] as const).map(([key, label, min, max]) => <label key={key}>{label}
          <NumericInput min={roundRect(min) * 100} max={floorRect(max) * 100} precision={2} step={1}
            value={Number((rect[key] * 100).toFixed(2))}
            {...previewNumber(value => withRegion({ rect: { ...rect, [key]: roundRect(value / 100) } }))}/>
        </label>)}
      </div>
    </details>
    <button type="button" className="secondary" onClick={() => {
      setCustom(false);
      onChange({ ...defaultSplitLayout, camera: { ...defaultSplitLayout.camera, rect: layout.camera.rect },
        gameplay: { ...defaultSplitLayout.gameplay, rect: layout.gameplay.rect } });
    }}>Restablecer encuadre</button>
  </div>;
}

export function SplitRegionEditor({ layout, selected, onSelect, onRect }: {
  layout: SplitLayout; selected: RegionKey; onSelect: (key: RegionKey) => void; onRect: (key: RegionKey, rect: SourceRect) => void;
}) {
  const plane = useRef<HTMLDivElement>(null);
  const gesture = useRef<{ key: RegionKey; corner?: Corner; pointer: number; x: number; y: number; rect: SourceRect; width: number; height: number } | null>(null);

  function start(event: PointerEvent, key: RegionKey, corner?: Corner) {
    if (event.button !== 0 || !plane.current || gesture.current) return;
    event.stopPropagation();
    const { width, height } = plane.current.getBoundingClientRect();
    gesture.current = { key, corner, pointer: event.pointerId, x: event.clientX, y: event.clientY, rect: layout[key].rect, width, height };
    plane.current.setPointerCapture(event.pointerId);
    onSelect(key);
  }

  function move(event: PointerEvent) {
    const drag = gesture.current;
    if (!drag || event.pointerId !== drag.pointer) return;
    const dx = (event.clientX - drag.x) / drag.width;
    const dy = (event.clientY - drag.y) / drag.height;
    const rect = drag.rect;
    if (!drag.corner) {
      onRect(drag.key, {
        ...rect, x: roundRect(clamp(rect.x + dx, 0, floorRect(1 - rect.width))),
        y: roundRect(clamp(rect.y + dy, 0, floorRect(1 - rect.height))),
      });
      return;
    }
    const right = rect.x + rect.width;
    const bottom = rect.y + rect.height;
    const fromLeft = drag.corner.endsWith('w');
    const fromTop = drag.corner.startsWith('n');
    const x = fromLeft ? roundRect(clamp(rect.x + dx, 0, floorRect(right - minSize))) : rect.x;
    const y = fromTop ? roundRect(clamp(rect.y + dy, 0, floorRect(bottom - minSize))) : rect.y;
    onRect(drag.key, {
      x, y,
      width: Math.min(floorRect(1 - x), roundRect((fromLeft ? right : clamp(right + dx, x + minSize, 1)) - x)),
      height: Math.min(floorRect(1 - y), roundRect((fromTop ? bottom : clamp(bottom + dy, y + minSize, 1)) - y)),
    });
  }

  return <div className="split-region-plane" ref={plane} onPointerMove={move} onLostPointerCapture={() => { gesture.current = null; }}>
    {regionKeys.map(key => {
      const rect = layout[key].rect;
      return <div data-region={key} data-selected={selected === key} key={key} className="split-source-rect"
        style={{ left: rect.x * 100 + '%', top: rect.y * 100 + '%', width: rect.width * 100 + '%', height: rect.height * 100 + '%' }}>
        <button type="button" className="split-rect-label" aria-label={'Mover región ' + regionNames[key]}
          onPointerDown={event => start(event, key)} onClick={() => onSelect(key)}>{regionNames[key]}</button>
        {selected === key && <>
          <div className="split-rect-drag" onPointerDown={event => start(event, key)}/>
          {corners.map(corner => <span key={corner} className={'split-handle ' + corner} aria-hidden="true"
            onPointerDown={event => start(event, key, corner)}/>)}
        </>}
      </div>;
    })}
  </div>;
}

function drawPanel(ctx: CanvasRenderingContext2D, buffer: HTMLCanvasElement, video: HTMLVideoElement,
  source: SourceGeometry, panel: PanelGeometry, top: number) {
  const sample = decodedCrop(panel.crop, source, video);
  if (buffer.width !== sample.width) buffer.width = sample.width;
  if (buffer.height !== sample.height) buffer.height = sample.height;
  const isolated = buffer.getContext('2d', { alpha: false });
  if (!isolated) return;
  // Interpolate only after copying the selected pixels into an isolated frame.
  isolated.imageSmoothingEnabled = false;
  isolated.drawImage(video, -sample.x, -sample.y);
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, top, panel.width, panel.height);
  ctx.clip();
  ctx.drawImage(buffer, (panel.width - panel.scaledWidth) / 2,
    top + (panel.height - panel.scaledHeight) / 2, panel.scaledWidth, panel.scaledHeight);
  ctx.restore();
}

export function SplitCanvas({ player, source, geometry, inverted, sourceGeometry }: {
  player: RefObject<HTMLVideoElement | null>; source: string; geometry: SplitGeometry; inverted: boolean;
  sourceGeometry: SourceGeometry;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { camera, gameplay } = geometry;
  useLayoutEffect(() => {
    const video = player.current;
    const ctx = canvasRef.current?.getContext('2d', { alpha: false });
    if (!video || !ctx) return;
    const cameraBuffer = document.createElement('canvas');
    const gameBuffer = document.createElement('canvas');
    const draw = () => {
      if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth || !video.videoHeight) return;
      drawPanel(ctx, cameraBuffer, video, sourceGeometry, camera, inverted ? gameplay.height : 0);
      drawPanel(ctx, gameBuffer, video, sourceGeometry, gameplay, inverted ? 0 : camera.height);
    };
    let callback = 0;
    const onFrame = () => { draw(); callback = video.requestVideoFrameCallback(onFrame); };
    const mediaEvents = ['loadeddata', 'canplay', 'seeked', 'resize'];
    for (const event of mediaEvents) video.addEventListener(event, draw);
    callback = video.requestVideoFrameCallback(onFrame);
    draw();
    return () => {
      video.cancelVideoFrameCallback(callback);
      for (const event of mediaEvents) video.removeEventListener(event, draw);
    };
  }, [player, source, camera, gameplay, inverted, sourceGeometry]);
  return <canvas ref={canvasRef} width={camera.width} height={camera.height + gameplay.height}
    className="split-canvas" aria-label="Composición en directo de cámara y gameplay"/>;
}
