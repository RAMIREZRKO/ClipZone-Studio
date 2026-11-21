import type { GraphicLayer, GraphicTextStyle } from '../api';

export const textFonts = ['Montserrat', 'Poppins', 'Anton', 'Arial', 'Roboto', 'Impact'];
export const legacyFonts = ['Segoe UI', 'Verdana', 'Tahoma'];

export const defaultTextStyle: GraphicTextStyle = {
  bold: true, italic: false, underline: false, align: 'center',
  background_color: '#000000', background_transparent: true, background_opacity: 100, padding: 12, radius: 10,
  outline_color: '#000000', outline_width: 2,
  shadow_color: '#000000', shadow_opacity: 0, shadow_blur: 4, shadow_x: 2, shadow_y: 3,
};

type Look = Pick<GraphicLayer, 'font' | 'size' | 'color' | 'opacity'> & { text_style: GraphicTextStyle };
const look = (font: string, size: number, color: string, style: Partial<GraphicTextStyle> = {}): Look => ({
  font, size, color, opacity: 100, text_style: { ...defaultTextStyle, ...style },
});

export const textPresets = [
  { id: 'white-box', label: 'Texto negro con fondo blanco',
    look: look('Montserrat', 52, '#000000', { background_transparent: false, background_color: '#ffffff', outline_width: 0 }) },
  { id: 'black-box', label: 'Texto blanco con fondo negro',
    look: look('Roboto', 52, '#ffffff', { background_transparent: false, outline_width: 0 }) },
  { id: 'white-outline', label: 'Texto blanco con contorno negro',
    look: look('Arial', 52, '#ffffff', { outline_width: 4 }) },
  { id: 'yellow-outline', label: 'Texto amarillo con contorno negro',
    look: look('Impact', 60, '#ffe34f', { outline_width: 5 }) },
  { id: 'promo', label: 'Texto promocional',
    look: look('Poppins', 46, '#d6ffa5', { background_transparent: false, background_color: '#152414',
      background_opacity: 92, padding: 16, radius: 20, outline_width: 0 }) },
  { id: 'tiktok', label: 'Texto gancho para TikTok',
    look: look('Anton', 66, '#fff36a', { outline_width: 5, shadow_opacity: 75 }) },
];

export function automaticName(text: string) {
  return Array.from(text.trim().replace(/\s+/g, ' ')).slice(0, 80).join('') || 'Texto sin contenido';
}

export function layerLook(layer: GraphicLayer): Look {
  const { font, size, color, opacity, text_style } = layer;
  return { font, size, color, opacity, text_style: text_style ?? {
    ...defaultTextStyle,
    outline_width: layer.hook ? Math.round(size * .068) : 3,
    shadow_opacity: layer.hook ? 0 : 45,
    shadow_blur: 0, shadow_x: 1, shadow_y: 1,
  } };
}
