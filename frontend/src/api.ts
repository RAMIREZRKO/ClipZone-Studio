export interface Video {
  id: string; name: string; duration: number; width: number; height: number; size: number;
  codec: string; has_audio: boolean; preview_status: 'ready' | 'processing' | 'failed';
  preview_url: string | null; thumbnail_url: string; created_at: string;
}
export interface ClipSettings {
  video_id: string; title: string; start: number; end: number; ratio: string; resolution: number;
  fit: 'contain' | 'cover'; platform: string; safe_top: number; safe_bottom: number; focus_x: number; focus_y: number;
}
export interface Job {
  id: string; kind: 'export' | 'preview'; video_id: string; title: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'; progress: number;
  error: string | null; settings: ClipSettings | null; preview_url: string | null; download_url: string | null;
  size: number | null; created_at: string;
}
export interface Health { status: string; dependencies: Record<string, boolean>; version: string; max_upload_bytes: number }

export async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${url}`, options);
  if (!response.ok) {
    let message = `Error ${response.status}. Vuelve a intentarlo.`;
    try {
      const data = await response.json();
      message = typeof data.detail === 'string' ? data.detail : data.detail?.map((d: {msg: string}) => d.msg).join(' · ') || message;
    } catch { /* Respuesta sin JSON. */ }
    throw new Error(message);
  }
  return response.json();
}

export function uploadVideo(file: File, progress: (value: number) => void): Promise<Video> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/videos');
    xhr.upload.onprogress = event => { if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100)); };
    xhr.onerror = () => reject(new Error('No se pudo conectar con el servidor local.'));
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo importar el archivo.'));
      } catch { reject(new Error('El servidor no devolvió una respuesta válida.')); }
    };
    const body = new FormData(); body.append('file', file); xhr.send(body);
  });
}

export const seconds = (value: number) => {
  const safe = Math.max(0, Number.isFinite(value) ? value : 0);
  const h = Math.floor(safe / 3600);
  return `${h ? `${h}:` : ''}${String(Math.floor(safe / 60) % 60).padStart(2, '0')}:${(safe % 60).toFixed(1).padStart(4, '0')}`;
};
export const sizeLabel = (value: number) => value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(1)} GB` : `${(value / 1024 ** 2).toFixed(1)} MB`;
