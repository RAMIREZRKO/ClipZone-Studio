import { Fragment, useEffect, useRef, useState, type PointerEvent } from 'react';
import { Image, Layers, Plus, Save } from 'lucide-react';
import { request, type CampaignTemplate, type GraphicLayer, type RenderOptions } from '../api';
import { NumericInput } from './NumericInput';
import { TextLayerEditor } from './TextLayerEditor';
import { automaticName, defaultTextStyle, layerLook } from './textStyles';

const makeId = () => crypto.randomUUID().replaceAll('-', '');

export function CampaignPanel({ layers, options, onLayers, onApply, onSelect, duration, videoId, start, end, title }: {
  layers: GraphicLayer[]; options: RenderOptions; onLayers: (update: (previous: GraphicLayer[]) => GraphicLayer[]) => void;
  onApply: (options: RenderOptions) => void; onSelect: (id: string, time: number) => void; duration: number;
  videoId?: string; start: number; end: number; title: string;
}) {
  const [templates, setTemplates] = useState<CampaignTemplate[]>([]);
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [suggestions, setSuggestions] = useState<{ videoId: string; start: number; end: number; titles: string[] } | null>(null);
  const [lastAdded, setLastAdded] = useState('');
  const styles = templates.filter(item => item.kind);
  const suggested = suggestions?.videoId === videoId && suggestions?.start === start && suggestions?.end === end ? suggestions?.titles : null;
  const active = templates.find(item => item.id === selected);
  useEffect(() => {
    request<CampaignTemplate[]>('/templates').then(setTemplates).catch(e => setError((e as Error).message));
  }, []);

  const change = (id: string, patch: Partial<GraphicLayer>) => onLayers(items => items.map(item => item.id === id ? { ...item, ...patch } : item));
  function makeLayer(kind: GraphicLayer['kind'], label: string): GraphicLayer {
    return { id: makeId(), kind, name: label.slice(0, 80), text: '',
      asset_id: null, font: 'Arial', color: '#ffffff', x: 50, y: 23, size: kind === 'text' ? 42 : 25, opacity: 100, start: 0, end: null };
  }

  function addLayer(layer: GraphicLayer) {
    setLastAdded(layer.id);
    onLayers(items => items.length < 12 ? [...items, layer] : items);
  }

  function newText(text: string) {
    return { ...makeLayer('text', automaticName(text)), text, auto_name: true, text_style: defaultTextStyle };
  }

  function addHook(text: string) {
    const hook = layers.find(item => item.hook);
    if (hook) {
      change(hook.id, { text, ...(hook.auto_name ? { name: automaticName(text) } : {}),
        text_style: layerLook(hook).text_style });
      setLastAdded(hook.id);
      return;
    }
    addLayer({ ...newText(text), hook: true, text_style: { ...defaultTextStyle, outline_width: 3 },
      anchor: options.fit === 'split' ? 'split' : 'free', size: 44, end: duration > 3 ? 3 : null });
  }

  async function suggest() {
    if (!videoId || busy) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const titles = await request<string[]>(`/videos/${videoId}/hook-titles?start=${start}&end=${end}`);
      setSuggestions({ videoId, start, end, titles });
      if (!titles.length) setMessage('Analiza o retranscribe el fragmento con Whisper para obtener sugerencias.');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function upload(file?: File, layerId?: string) {
    if (!file || busy || (!layerId && layers.length >= 12)) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const body = new FormData();
      body.append('file', file);
      const asset = await request<{ id: string; name: string }>('/assets', { method: 'POST', body });
      if (layerId) change(layerId, { asset_id: asset.id });
      else addLayer({ ...makeLayer('image', asset.name), asset_id: asset.id });
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function save(update: boolean, style?: { name: string; layer: GraphicLayer }) {
    const label = style?.name ?? name.trim();
    if (!label || busy) return false;
    setBusy(true); setError(''); setMessage('');
    try {
      const template = await request<CampaignTemplate>('/templates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: update && active && !active.example ? active.id : null, name: label,
          ...(style ? { kind: style.layer.hook ? 'hook' : 'text', options: { graphics: [style.layer] } } : { options }) }),
      });
      setTemplates(previous => [template, ...previous.filter(item => item.id !== template.id)]);
      if (!style) setSelected(template.id);
      setMessage(style ? style.layer.hook ? 'Estilo de gancho guardado.' : 'Estilo de texto guardado.' : 'Plantilla guardada.');
      return true;
    } catch (e) { setError((e as Error).message); return false; }
    finally { setBusy(false); }
  }

  return <section className="panel phase-panel" id="campaign-editor" aria-label="Gráficos y plantillas">
    <div className="panel-heading"><div><Layers size={18}/><h2>Gráficos y plantillas</h2></div></div>
    <div className="phase-body">
      <div className="phase-toolbar">
        <label>Plantilla<select aria-label="Plantilla de campaña" value={selected} onChange={e => {
          const template = templates.find(item => item.id === e.target.value);
          setSelected(e.target.value);
          if (template) setName(template.example ? template.name + ' personalizada' : template.name);
        }}>
          <option value="">Selecciona una plantilla</option>
          {templates.filter(template => !template.kind).map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
        </select></label>
        <button className="secondary" disabled={!active || busy} onClick={() => { if (active) { onApply(active.options); setMessage('Plantilla aplicada al editor y a los próximos clips seleccionados.'); } }}>Aplicar plantilla</button>
        <label>Nombre de plantilla<input maxLength={80} value={name} onChange={e => setName(e.target.value)}/></label>
        <button className="secondary" disabled={!name.trim() || busy} onClick={() => void save(false)}><Save size={15}/> Guardar como plantilla</button>
        {active && !active.example && <button className="secondary" disabled={!name.trim() || busy} onClick={() => void save(true)}>Actualizar plantilla</button>}
      </div>
      <p className="field-note">Las capas se colocan sobre la vista en directo. Los tiempos de las capas empiezan en el segundo cero de cada clip.</p>
      <div className="phase-toolbar">
        <label><span><Image size={15}/> Agregar PNG</span><input type="file" accept="image/png,.png" aria-label="Agregar PNG"
          disabled={busy || layers.length >= 12} onChange={e => { void upload(e.target.files?.[0]); e.target.value = ''; }}/></label>
        <button className="secondary" disabled={busy || layers.length >= 12} onClick={() => addLayer(newText('Tu mensaje promocional'))}>
          <Plus size={15}/> Agregar texto
        </button>
        <button className="secondary" disabled={busy || layers.length >= 12 || layers.some(layer => layer.hook)}
          onClick={() => addHook(title.trim() || 'Texto gancho')}>Crear texto gancho</button>
        <button className="secondary" disabled={busy || !videoId || end <= start || (layers.length >= 12 && !layers.some(layer => layer.hook))}
          onClick={() => void suggest()}>Sugerir títulos con IA</button>
        {suggested?.length ? <label>Sugerencias para el gancho<select value="" onChange={event => {
          if (event.target.value) addHook(event.target.value);
        }}><option value="">Elige un título</option>{suggested.map(text => <option key={text}>{text}</option>)}</select></label> : null}
        <span>{layers.length} de 12 capas</span>
      </div>
      {error && <p role="alert" className="alert error">{error}</p>}
      {message && <p role="status">{message}</p>}
      {layers.map((layer, index) => <details className="graphic-row" key={layer.id}
        open={layers.length === 1 || layer.id === lastAdded || undefined}>
        <summary>{layer.name}{layer.hidden ? ' · Oculta' : ''}{layer.kind === 'image' && !layer.asset_id ? ' · falta el PNG' : ''}</summary>
        <div className="phase-toolbar graphic-actions">
          <button type="button" className="secondary" disabled={layers.length >= 12} onClick={() => addLayer({
            ...layer, id: makeId(), name: Array.from(layer.name).slice(0, 72).join('') + ' · copia', auto_name: false,
          })}>Duplicar capa</button>
          <button type="button" className="secondary" onClick={() => change(layer.id, { hidden: !layer.hidden })}>
            {layer.hidden ? 'Mostrar capa' : 'Ocultar capa'}
          </button>
          <button type="button" className="secondary danger-link"
            onClick={() => onLayers(items => items.filter(item => item.id !== layer.id))}>Eliminar capa</button>
        </div>
        {layer.kind === 'text' ? <TextLayerEditor layer={layer} duration={duration} split={options.fit === 'split'}
          styles={styles} busy={busy} change={patch => change(layer.id, patch)} position={() => onSelect(layer.id, layer.start)}
          saveStyle={name => save(false, { name, layer })}/> : <>
        <div className="phase-toolbar">
          <label>Nombre de capa<input value={layer.name} maxLength={80} onChange={e => change(layer.id, { name: e.target.value })}/></label>
          <label>{layer.asset_id ? 'Cambiar PNG' : 'Asignar PNG'}
            <input type="file" accept="image/png,.png" aria-label={`PNG de la capa ${index + 1}`} disabled={busy}
              onChange={e => { void upload(e.target.files?.[0], layer.id); e.target.value = ''; }}/>
          </label>
        </div>
        <div className="phase-toolbar">
          {([['x', 'Horizontal (%)', 0], ['y', 'Vertical (%)', 0], ['size', 'Tamaño', 5], ['opacity', 'Opacidad (%)', 0]] as const)
            .map(([field, label, min]) => <label key={field}>{label}
              <NumericInput min={min} max={100} precision={field === 'x' || field === 'y' ? 1 : 0}
                value={layer[field]} onCommit={value => change(layer.id, field === 'y' ? { y: value, anchor: 'free' } : { [field]: value })}/>
            </label>)}
        </div>
        <div className="phase-toolbar">
          <label><input type="checkbox" checked={layer.start === 0 && layer.end === null} onChange={e => change(layer.id,
            e.target.checked ? { start: 0, end: null } : { end: Math.max(.1, duration || 3) })}/> Todo el clip</label>
          <label>Aparece (s)<NumericInput min={0} max={3600} precision={2} value={layer.start}
            onCommit={start => change(layer.id, { start })}/></label>
          <label>Desaparece (s)<NumericInput min={.01} max={3600} precision={2} value={layer.end} placeholder="Final"
            onCommit={end => change(layer.id, { end })}/></label>
          {layer.end !== null && <button type="button" className="secondary" onClick={() => change(layer.id, { end: null })}>Hasta el final del clip</button>}
          <button className="secondary" disabled={layer.hidden} onClick={() => onSelect(layer.id, layer.start)}>Posicionar en el vídeo</button>
        </div>
        </>}
      </details>)}
    </div>
  </section>;
}

function TextRaster({ layer, format, resolution, y, children }: {
  layer: GraphicLayer; format: string; resolution: number; y: number;
  children: (bitmap: { image: string; width?: number } | null) => React.ReactNode;
}) {
  const { id, text, font, size, color, opacity, hook, text_style } = layer;
  const legacy = !text_style && !/[\p{Extended_Pictographic}\p{Emoji_Presentation}\u20e3]/u.test(text);
  const payload = JSON.stringify({ ratio: format, resolution,
    layer: { id, kind: 'text', text, font, size, color, opacity, hook, text_style, x: 50, y: 50 } });
  const [art, setArt] = useState<{ payload: string; image: string; width?: number } | null>(null);
  const active = art?.payload === payload ? art : null;
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      request<{ image: string; width?: number }>(legacy ? '/graphics/hook' : '/graphics/text', { method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' }, body: payload })
        .then(result => { if (!controller.signal.aborted) setArt({ payload, ...result }); })
        .catch(() => { /* Conserva el texto editable mientras el rasterizado no esté disponible. */ });
    }, 45);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [legacy, payload]);
  return <>{legacy && active && <img className="hook-raster" alt="" draggable={false} src={'data:image/png;base64,' + active.image}
    style={{ transform: `translate(${layer.x - 50}%, ${y - 50}%)` }}/>}
    {children(active)}</>;
}

export function GraphicOverlay({ layers, time, ratio, format, resolution, canvasWidth, seam, selected, move, select }: {
  layers: GraphicLayer[]; time: number; ratio: number; selected: string | null;
  format: string; resolution: number; canvasWidth: number; seam: number | null;
  move: (id: string, x: number, y: number) => void; select: (id: string) => void;
}) {
  const area = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const coordinates = (event: PointerEvent) => {
    const rect = area.current!.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / rect.width * 100, y: (event.clientY - rect.top) / rect.height * 100 };
  };
  const clamp = (value: number) => Math.round(Math.max(0, Math.min(100, value)) * 10) / 10;
  return <div className="graphic-overlay" ref={area}>
    {layers.filter(layer => !layer.hidden && layer.start <= time && (layer.end === null || time < layer.end) &&
      (layer.kind === 'image' ? layer.asset_id : layer.text.trim())).map(layer => {
      const y = layer.anchor === 'split' && seam !== null ? seam : layer.y;
      const item = (bitmap: { image: string; width?: number } | null) => <button type="button"
      className={`graphic-item ${layer.hook ? 'hook-item' : ''} ${bitmap?.width ? 'text-bitmap' : ''} ${selected === layer.id ? 'is-selected' : ''}`} aria-label={`Mover ${layer.name}`}
      style={{ left: `${layer.x}%`, top: `${y}%`, width: layer.kind === 'image' ? `${layer.size}%` : bitmap?.width ? `${bitmap.width / canvasWidth * 100}%` : undefined,
        color: layer.color, fontFamily: layer.font, fontSize: `${layer.size * Math.min(1, 1 / ratio) / (layer.hook ? 10.8 : 10)}cqw` }}
      onPointerDown={e => {
        e.preventDefault(); e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId);
        const point = coordinates(e);
        drag.current = { id: layer.id, dx: point.x - layer.x, dy: point.y - y };
        select(layer.id);
      }}
      onPointerMove={e => {
        if (drag.current?.id !== layer.id) return;
        const point = coordinates(e);
        move(layer.id, clamp(point.x - drag.current.dx), clamp(point.y - drag.current.dy));
      }}
      onLostPointerCapture={() => { drag.current = null; }}
      onKeyDown={e => {
        const vector: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
        const direction = vector[e.key];
        if (!direction) return;
        e.preventDefault();
        move(layer.id, clamp(layer.x + direction[0]), clamp(y + direction[1]));
      }}>
      {layer.kind === 'image' ? <img src={`/api/assets/${layer.asset_id}`} alt="" draggable={false}
        style={{ opacity: layer.opacity / 100, maxHeight: `${80 / ratio}cqw` }}/>
        : bitmap?.width ? <img className="text-raster" src={'data:image/png;base64,' + bitmap.image} alt="" draggable={false}/>
          : <span style={{ opacity: bitmap ? 0 : layer.opacity / 100 }}>{layer.text}</span>}
      </button>;
      return layer.kind === 'text' ? <TextRaster key={layer.id} layer={layer} format={format} resolution={resolution} y={y}>
        {item}
      </TextRaster> : <Fragment key={layer.id}>{item(null)}</Fragment>;
    })}
  </div>;
}
