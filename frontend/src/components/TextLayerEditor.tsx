import { useRef, useState } from 'react';
import { Smile } from 'lucide-react';
import type { CampaignTemplate, GraphicLayer, GraphicTextStyle } from '../api';
import { NumericInput } from './NumericInput';
import { automaticName, layerLook, legacyFonts, textFonts, textPresets } from './textStyles';
import { EmojiPicker } from './EmojiPicker';

type Patch = (patch: Partial<GraphicLayer>) => void;
const hundredths = (seconds: number) => Math.floor(seconds * 100 + 1e-7);

function TextDuration({ layer, duration, change }: { layer: GraphicLayer; duration: number; change: Patch }) {
  const max = Math.max(1, hundredths(duration));
  const first = Math.min(max, hundredths(layer.start));
  const last = Math.min(max, Math.max(first, layer.end === null ? max : hundredths(layer.end)));
  const full = layer.start === 0 && layer.end === null;
  const format = (value: number) => (value / 100).toFixed(2) + ' s';

  function setStart(next: number) {
    change({ start: Math.min(Math.max(0, last - 1), Math.max(0, next)) / 100 });
  }
  function setEnd(next: number) {
    change({ ...(first >= max ? { start: (max - 1) / 100 } : {}),
      end: Math.min(max, Math.max(first + 1, next)) / 100 });
  }
  return <fieldset className="text-editor-section">
    <legend>Duración</legend>
    <label><input type="checkbox" checked={full} onChange={event => change(event.target.checked ?
      { start: 0, end: null } : { end: max / 100 })}/> Mostrar durante todo el clip</label>
    <div className="text-time-readout"><output>{format(first)}</output><output>{format(last)}</output></div>
    <div className="text-time-slider">
      <div className="text-time-track"><span style={{ left: first / max * 100 + '%', right: (1 - last / max) * 100 + '%' }}/></div>
      <input type="range" min={0} max={max} value={first} aria-label="Inicio del texto" aria-valuetext={format(first)}
        onChange={event => setStart(Number(event.target.value))}/>
      <input type="range" min={0} max={max} value={last} aria-label="Fin del texto" aria-valuetext={format(last)}
        onChange={event => setEnd(Number(event.target.value))}/>
    </div>
    {first === max && <p className="field-note">El inicio está fuera del clip. Mueve el control para ajustar el intervalo.</p>}
    <details className="text-editor-advanced">
      <summary>Tiempos avanzados</summary>
      <div className="phase-toolbar">
        <label>Aparece (s)<NumericInput min={0} max={Math.max(0, last - 1) / 100} precision={2}
          value={first / 100} onCommit={value => setStart(hundredths(value))}/></label>
        <label>Desaparece (s)<NumericInput min={Math.min(max, first + 1) / 100} max={max / 100} precision={2}
          value={layer.end === null ? null : last / 100} placeholder="Final" onCommit={value => setEnd(hundredths(value))}/></label>
        {layer.end !== null && <button type="button" className="secondary" onClick={() => change({ end: null })}>Hasta el final del clip</button>}
      </div>
    </details>
  </fieldset>;
}

export function TextLayerEditor({ layer, duration, split, styles, busy, change, position, saveStyle }: {
  layer: GraphicLayer; duration: number; split: boolean; styles: CampaignTemplate[]; busy: boolean;
  change: Patch; position: () => void; saveStyle: (name: string) => Promise<boolean>;
}) {
  const [styleName, setStyleName] = useState('');
  const [draftName, setDraftName] = useState<string | null>(null);
  const [showEmojis, setShowEmojis] = useState(false);
  const [emojiError, setEmojiError] = useState('');
  const field = useRef<HTMLTextAreaElement>(null);
  const emojiButton = useRef<HTMLButtonElement>(null);
  const look = layerLook(layer);
  const style = look.text_style;
  const editStyle = (next: Partial<GraphicTextStyle>) => change({ text_style: { ...style, ...next } });
  const editLook = (next: Partial<typeof look>) => change({ ...look, ...next });
  const flags = [['bold', 'Negrita'], ['italic', 'Cursiva'], ['underline', 'Subrayado']] as const;
  const contentLabel = layer.hook ? 'Texto gancho' : 'Texto promocional';
  const presetLabel = layer.hook ? 'Aplicar estilo de gancho' : 'Aplicar estilo de texto';
  function editText(text: string) {
    setEmojiError('');
    change({ text, ...(layer.text_style ? {} : { text_style: style }), ...(layer.auto_name ? { name: automaticName(text) } : {}) });
  }
  function insertEmoji(emoji: string) {
    const input = field.current;
    if (!input) return;
    const { selectionStart, selectionEnd } = input;
    const text = layer.text.slice(0, selectionStart) + emoji + layer.text.slice(selectionEnd);
    if (text.length > input.maxLength) {
      setEmojiError('Selecciona parte del texto o libera espacio para añadir el emoji.');
      return;
    }
    editText(text);
    setShowEmojis(false);
    requestAnimationFrame(() => {
      input.focus();
      input.setSelectionRange(selectionStart + emoji.length, selectionStart + emoji.length);
    });
  }

  return <div className="text-editor">
    <fieldset className="text-editor-section">
      <legend>Contenido</legend>
      <label>{contentLabel}
        <textarea ref={field} aria-label={contentLabel} value={layer.text} maxLength={180}
          onChange={event => editText(event.target.value)}/>
      </label>
      <button type="button" className="secondary emoji-toggle" ref={emojiButton} aria-expanded={showEmojis}
        onClick={() => { setEmojiError(''); setShowEmojis(value => !value); }}><Smile size={17}/> Insertar emoji</button>
      {showEmojis && <EmojiPicker insert={insertEmoji} close={() => {
        setShowEmojis(false); setEmojiError(''); emojiButton.current?.focus();
      }}/>}
      {emojiError && <p role="status" className="field-note">{emojiError}</p>}
      <details className="text-editor-advanced">
        <summary>Opciones avanzadas de la capa</summary>
        <div className="phase-toolbar">
          <label>Nombre de capa<input value={draftName ?? layer.name} maxLength={80}
            onChange={event => setDraftName(event.target.value)}
            onBlur={() => {
              if (draftName !== null) change({ name: draftName.trim() || automaticName(layer.text), auto_name: false });
              setDraftName(null);
            }}
            onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); event.currentTarget.blur(); } }}/></label>
          <label><input type="checkbox" checked={!!layer.auto_name} onChange={event => change({
            auto_name: event.target.checked, ...(event.target.checked ? { name: automaticName(layer.text) } : {}),
          })}/> Generar el nombre desde el texto</label>
        </div>
      </details>
    </fieldset>

    <fieldset className="text-editor-section">
      <legend>Estilo</legend>
      <div className="phase-toolbar">
        <label>{presetLabel}<select aria-label={presetLabel} value="" onChange={event => {
          const preset = textPresets.find(item => item.id === event.target.value);
          const saved = styles.find(item => item.id === event.target.value)?.options.graphics?.[0];
          if (preset) change(preset.look);
          if (saved) change(layerLook(saved));
        }}>
          <option value="">Elige un estilo</option>
          <optgroup label="Predefinidos">{textPresets.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</optgroup>
          {styles.length > 0 && <optgroup label="Guardados">{styles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup>}
        </select></label>
        <label>Nombre del estilo<input maxLength={80} value={styleName} onChange={event => setStyleName(event.target.value)}/></label>
        <button type="button" className="secondary" disabled={busy || !styleName.trim()} onClick={() => {
          void saveStyle(styleName.trim()).then(saved => { if (saved) setStyleName(''); });
        }}>{layer.hook ? 'Guardar estilo de gancho' : 'Guardar estilo de texto'}</button>
      </div>
      <div className="phase-toolbar">
        <label>Fuente<select aria-label="Fuente" value={layer.font} onChange={event => editLook({ font: event.target.value })}>
          {textFonts.map(font => <option key={font}>{font}</option>)}
          {legacyFonts.includes(layer.font) && <option>{layer.font}</option>}
        </select></label>
        <label>Tamaño a 1080p (px)<NumericInput min={5} max={220} value={layer.size} onCommit={size => editLook({ size })}/></label>
        <label>Alineación<select aria-label="Alineación" value={style.align} onChange={event => editStyle({ align: event.target.value as GraphicTextStyle['align'] })}>
          <option value="left">Izquierda</option><option value="center">Centrada</option><option value="right">Derecha</option>
        </select></label>
        <div className="text-style-flags" role="group" aria-label="Formato de texto">{flags.map(([key, label]) =>
          <button type="button" className="secondary" key={key} aria-pressed={style[key]}
            onClick={() => editStyle({ [key]: !style[key] })}>{label}</button>)}</div>
      </div>
      <div className="phase-toolbar">
        <label>Color del texto<input type="color" value={layer.color} onChange={event => editLook({ color: event.target.value })}/></label>
        <label>Opacidad del texto (%)<NumericInput min={0} max={100} value={layer.opacity}
          onCommit={opacity => editLook({ opacity })}/></label>
        <label><input type="checkbox" checked={style.background_transparent}
          onChange={event => editStyle({ background_transparent: event.target.checked })}/> Fondo transparente</label>
        <label>Color de fondo<input type="color" value={style.background_color} onChange={event => editStyle({ background_color: event.target.value })}/></label>
        <label>Opacidad del fondo (%)<NumericInput min={0} max={100} value={style.background_opacity}
          onCommit={background_opacity => editStyle({ background_opacity })}/></label>
        <label>Redondeo (px)<NumericInput min={0} max={100} value={style.radius} onCommit={radius => editStyle({ radius })}/></label>
        <label>Espaciado interno (px)<NumericInput min={0} max={100} value={style.padding} onCommit={padding => editStyle({ padding })}/></label>
      </div>
      <details className="text-editor-advanced">
        <summary>Contorno y sombra</summary>
        <div className="phase-toolbar">
          <label>Color del contorno<input type="color" value={style.outline_color} onChange={event => editStyle({ outline_color: event.target.value })}/></label>
          <label>Grosor del contorno (px)<NumericInput min={0} max={24} value={style.outline_width}
            onCommit={outline_width => editStyle({ outline_width })}/></label>
          <label>Color de sombra<input type="color" value={style.shadow_color} onChange={event => editStyle({ shadow_color: event.target.value })}/></label>
          {([
            ['shadow_opacity', 'Opacidad de sombra (%)', 0, 100], ['shadow_blur', 'Desenfoque de sombra (px)', 0, 30],
            ['shadow_x', 'Sombra horizontal (px)', -40, 40], ['shadow_y', 'Sombra vertical (px)', -40, 40],
          ] as const).map(([key, label, min, max]) => <label key={key}>{label}
            <NumericInput min={min} max={max} value={style[key]} onCommit={value => editStyle({ [key]: value })}/>
          </label>)}
        </div>
      </details>
    </fieldset>

    <fieldset className="text-editor-section">
      <legend>Posición</legend>
      <div className="phase-toolbar">
        {layer.hook && split && <label>Posición del gancho<select value={layer.anchor ?? 'free'}
          onChange={event => change({ anchor: event.target.value as GraphicLayer['anchor'] })}>
          <option value="split">Unión de cámara y gameplay</option><option value="free">Libre</option>
        </select></label>}
        <label>Horizontal (%)<NumericInput min={0} max={100} precision={1} value={layer.x} onCommit={x => change({ x })}/></label>
        <label>Vertical (%)<NumericInput min={0} max={100} precision={1} value={layer.y} onCommit={y => change({ y, anchor: 'free' })}/></label>
        <button type="button" className="secondary" disabled={layer.hidden} onClick={position}>Posicionar en el vídeo</button>
      </div>
    </fieldset>
    <TextDuration layer={layer} duration={duration} change={change}/>
  </div>;
}
