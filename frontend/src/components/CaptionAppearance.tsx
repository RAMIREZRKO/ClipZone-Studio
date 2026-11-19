import type { CaptionStyle } from '../api';

const classic: CaptionStyle = {
  preset: 'classic', font: 'Arial', size: 52, color: '#ffffff', active_color: '#b1f65a', outline: 3,
  outline_color: '#000000', shadow: 1, background: '#000000', background_opacity: 0,
  align: 'center', position: 90, words_per_line: 5,
};

export const captionPresets: Record<CaptionStyle['preset'], CaptionStyle> = {
  classic,
  hormozi: { ...classic, preset: 'hormozi', size: 78, outline: 5, shadow: 3, words_per_line: 3 },
  karaoke: { ...classic, preset: 'karaoke', size: 58, active_color: '#ffe86b' },
  minimal: { ...classic, preset: 'minimal', font: 'Segoe UI', size: 43, outline: 0, shadow: 0, background_opacity: 64 },
};
const names = { classic: 'Clásico', hormozi: 'Hormozi', karaoke: 'Karaoke', minimal: 'Minimalista' };

export function CaptionAppearance({ style, onChange }: { style: CaptionStyle; onChange: (style: CaptionStyle) => void }) {
  const set = <Key extends keyof CaptionStyle>(key: Key, value: CaptionStyle[Key]) => onChange({ ...style, [key]: value });
  return <details className="caption-appearance">
    <summary>Estilo y posición de subtítulos</summary>
    <div className="phase-toolbar">
      <label>Estilo<select aria-label="Estilo" value={style.preset} onChange={e => onChange({ ...captionPresets[e.target.value as CaptionStyle['preset']] })}>
        {Object.entries(names).map(([key, name]) => <option value={key} key={key}>{name}</option>)}
      </select></label>
      <label>Fuente<select value={style.font} onChange={e => set('font', e.target.value)}>
        {['Arial', 'Segoe UI', 'Verdana', 'Tahoma', 'Impact'].map(font => <option key={font}>{font}</option>)}
      </select></label>
      <label>Alineación<select value={style.align} onChange={e => set('align', e.target.value as CaptionStyle['align'])}>
        <option value="left">Izquierda</option><option value="center">Centro</option><option value="right">Derecha</option>
      </select></label>
      {([
        ['size', 'Tamaño a 1080 px', 24, 104], ['outline', 'Contorno', 0, 10], ['shadow', 'Sombra', 0, 10],
        ['background_opacity', 'Opacidad del fondo (%)', 0, 100], ['position', 'Posición vertical (%)', 0, 100],
        ['words_per_line', 'Palabras por línea', 1, 12],
      ] as const).map(([key, label, min, max]) => <label key={key}>{label}
        <input type="number" min={min} max={max} value={style[key]} onChange={e => set(key, Math.max(min, Math.min(max, +e.target.value)))}/>
      </label>)}
      {([
        ['color', 'Color del texto'], ['active_color', 'Color de palabra activa'], ['outline_color', 'Color del contorno'],
        ['background', 'Color del fondo'],
      ] as const).map(([key, label]) => <label key={key}>{label}<input type="color" value={style[key]} onChange={e => set(key, e.target.value)}/></label>)}
    </div>
  </details>;
}

