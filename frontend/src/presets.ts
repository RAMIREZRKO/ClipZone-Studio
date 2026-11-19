// Valores iniciales editables; no representan reglas obligatorias de las plataformas.
export const ratios = ['9:16', '1:1', '4:5', '16:9'];
export const presets: Record<string, { label: string; ratio: string; top: number; bottom: number; duration: number; symbol: string }> = {
  tiktok: { label: 'TikTok', ratio: '9:16', top: 10, bottom: 22, duration: 30, symbol: '♪' },
  reels: { label: 'Reels', ratio: '9:16', top: 12, bottom: 22, duration: 30, symbol: '◎' },
  shorts: { label: 'Shorts', ratio: '9:16', top: 10, bottom: 20, duration: 60, symbol: '▶' },
  facebook: { label: 'Facebook Reels', ratio: '9:16', top: 12, bottom: 22, duration: 30, symbol: 'f' },
  custom: { label: 'Libre', ratio: '16:9', top: 8, bottom: 10, duration: 60, symbol: '↗' },
};
export const statusLabel = { queued: 'En cola', running: 'Exportando', completed: 'Listo para compartir', failed: 'Error al procesar', cancelled: 'Cancelado' };
