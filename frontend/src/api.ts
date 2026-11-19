export interface Video {
  id: string; name: string; duration: number; width: number; height: number; size: number;
  codec: string; has_audio: boolean; preview_status: 'ready' | 'processing' | 'failed';
  preview_url: string | null; thumbnail_url: string; created_at: string;
}
export interface ClipSettings {
  video_id: string; title: string; start: number; end: number; ratio: string; resolution: number;
  fit: 'contain' | 'cover' | 'blur'; platform: string; safe_top: number; safe_bottom: number; focus_x: number; focus_y: number;
  blur_strength?: number;
  captions?: CaptionOptions | null;
  graphics?: GraphicLayer[];
  score?: number; analysis_id?: string; moment_id?: string;
}
export interface Job {
  id: string; kind: 'export' | 'preview' | 'draft'; video_id: string; title: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'; progress: number;
  error: string | null; settings: ClipSettings | null; preview_url: string | null; download_url: string | null;
  size: number | null; created_at: string;
  subtitles?: { srt: string; vtt: string };
}
export interface Health { status: string; dependencies: Record<string, boolean>; version: string; max_upload_bytes: number }

export interface AIModel {
  id: string; label: string; size_mb: number; installed: boolean;
  integrity?: 'verified' | 'invalid' | 'unreadable' | 'missing';
}
export interface ModelDownload { status: 'downloading' | 'cancelling' | 'completed' | 'failed' | 'cancelled'; received: number; total: number | null; error: string | null; error_code?: string | null }
export interface AICapabilities {
  dependencies: Record<string, boolean>; models: AIModel[]; ready: boolean; install_command: string;
  device: 'cpu'; downloads: Record<string, ModelDownload>;
}
export interface AnalysisOptions { model: string; language: string; min_duration: number; max_duration: number; max_clips: number; reuse_transcript: boolean; cpu_threads?: number }
export interface Analysis {
  id: string; video_id: string; status: Job['status']; progress: number; stage: string; error: string | null;
  options: AnalysisOptions; created_at: string; reused_transcript: boolean;
  elapsed_seconds?: number;
}
export interface Moment {
  id: string; start: number; end: number; score: number; title: string; text: string; reason: string;
  metrics: { speech: number; hook: number; closure: number; energy: number };
}
export interface AnalysisResult {
  transcript: { text: string; language: string; words: { text: string; start: number; end: number }[] };
  moments: Moment[]; scoring_version: string;
}
export interface CaptionWord { text: string; start: number; end: number }
export interface CaptionSegment extends CaptionWord {
  id: string; words: CaptionWord[]; translations: Record<string, string>;
}
export interface CaptionTrack {
  id: string; revision: string | null; audio_language: string | null; analysis_id: string | null; segments: CaptionSegment[];
}
export interface CaptionStyle {
  preset: 'classic' | 'hormozi' | 'karaoke' | 'minimal';
  font: string; size: number; color: string; active_color: string; outline: number; outline_color: string; shadow: number;
  background: string; background_opacity: number; align: 'left' | 'center' | 'right'; position: number; words_per_line: number;
}
export interface CaptionOptions { enabled: boolean; sidecars: boolean; revision: string | null; language: string; style: CaptionStyle }
export interface GraphicLayer {
  id: string; kind: 'image' | 'text'; name: string; asset_id: string | null; text: string; font: string; color: string;
  x: number; y: number; size: number; opacity: number; start: number; end: number | null;
}
export type RenderOptions = Pick<ClipSettings, 'ratio' | 'resolution' | 'fit' | 'platform' | 'safe_top' | 'safe_bottom' | 'focus_x' | 'focus_y' | 'blur_strength' | 'captions' | 'graphics'>;
export interface CampaignTemplate { id: string; name: string; example: boolean; options: RenderOptions }

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
  const tenths = Math.round(safe * 10);
  const h = Math.floor(tenths / 36000);
  return `${h ? `${h}:` : ''}${String(Math.floor(tenths / 600) % 60).padStart(2, '0')}:${((tenths % 600) / 10).toFixed(1).padStart(4, '0')}`;
};
export const sizeLabel = (value: number) => value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(1)} GB` : `${(value / 1024 ** 2).toFixed(1)} MB`;
