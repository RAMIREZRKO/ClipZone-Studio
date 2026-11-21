import { useEffect, useState, type ReactNode } from 'react';
import { HardDrive, LoaderCircle, Trash2 } from 'lucide-react';
import { request, type DiskSpace } from '../api';
import { Modal } from './Modal';

interface LocationStatus {
  location_configurable: boolean; pending_directory: string | null;
  migration_error: string | null; migration_warning: string | null; verified_files: number | null;
}

export interface StorageStats extends DiskSpace, LocationStatus {
  directory: string; draft_bytes: number; draft_limit_bytes: number;
  video_count: number; export_count: number; video_bytes: number; export_bytes: number;
  transcript_bytes: number; temporary_bytes: number; database_bytes: number; model_bytes: number; total_bytes: number; graphics_bytes?: number;
}

interface FolderListing { path: string | null; parent: string | null; folders: string[] }

export function diskGB(value: number) {
  return new Intl.NumberFormat('es', { maximumFractionDigits: 2 }).format(value / 1e9) + ' GB';
}

export function DiskWarning({ space }: { space: DiskSpace }) {
  const { free_bytes, warning_bytes, capture_stop_bytes } = space;
  if (free_bytes === null || free_bytes > warning_bytes) return null;
  return <p className="manage-warning" role="status">
    Quedan {diskGB(free_bytes)} libres en la unidad de ClipZone. {free_bytes <= capture_stop_bytes
      ? 'Las capturas se detienen y quedan bloqueadas hasta recuperar espacio.'
      : 'Las capturas se detendrán si el espacio baja a 5 GB.'}
  </p>;
}

export function bytes(value: number) {
  if (!value) return '0 B';
  const unit = Math.min(4, Math.floor(Math.log(value) / Math.log(1024)));
  return `${new Intl.NumberFormat('es', { maximumFractionDigits: 1 }).format(value / 1024 ** unit)} ${['B', 'KB', 'MB', 'GB', 'TB'][unit]}`;
}

export interface RemovalTarget { id: string; name: string; related?: number }
interface RemovalResult { id: string; status: 'removed' | 'missing' | 'blocked'; message?: string; warning?: string | null }

export function RemoveDialog({ kind, targets, close, onRemoved }: {
  kind: 'videos' | 'exports'; targets: RemovalTarget[]; close: () => void;
  onRemoved: (ids: string[], warnings: string[]) => void;
}) {
  const [physical, setPhysical] = useState(false);
  const [running, setRunning] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [pending, setPending] = useState(targets);
  const related = pending.reduce((count, item) => count + (item.related ?? 0), 0);
  async function remove() {
    setRunning(true);
    setProblems([]);
    const removed: string[] = [];
    const warnings: string[] = [];
    const blocked = new Set<string>();
    const errors: string[] = [];
    let offset = 0;
    try {
      for (; offset < pending.length; offset += 100) {
        const batch = pending.slice(offset, offset + 100);
        const { results } = await request<{ results: RemovalResult[] }>(`/${kind}/remove`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: batch.map(item => item.id), remove_files: physical }),
        });
        for (const item of results) {
          if (item.status === 'blocked') {
            blocked.add(item.id);
            errors.push(`${batch.find(t => t.id === item.id)?.name || 'Elemento'}: ${item.message}`);
          } else {
            removed.push(item.id);
            if (item.warning) warnings.push(item.warning);
          }
        }
      }
    } catch (error) {
      errors.push((error as Error).message);
      for (const item of pending.slice(offset)) blocked.add(item.id);
    } finally {
      setRunning(false);
      onRemoved(removed, warnings);
      if (!blocked.size) close();
      else {
        setProblems(errors);
        setPending(pending.filter(item => blocked.has(item.id)));
      }
    }
  }
  return <Modal title={kind === 'videos' ? 'Quitar vídeos de la biblioteca' : 'Quitar exportaciones'} onClose={() => { if (!running) close(); }}>
    <div className="manage-dialog">
      <p>{pending.length === 1 ? pending[0].name : `${pending.length} elementos seleccionados`}</p>
      <fieldset disabled={running}>
        <legend>Elige qué hacer con los archivos</legend>
        <label><input type="radio" name="remove-mode" checked={!physical} onChange={() => setPhysical(false)}/> Conservar los archivos en el disco</label>
        <label><input type="radio" name="remove-mode" checked={physical} onChange={() => setPhysical(true)}/> Borrar los archivos administrados</label>
      </fieldset>
      {kind === 'videos' && <p>Se quitarán también los análisis del vídeo. Los archivos originales de fuera de ClipZone se conservan.</p>}
      {related > 0 && <p className="manage-warning" role="status">Se conservarán {related} clips relacionados en Exportaciones.</p>}
      {problems.length > 0 && <ul className="manage-warning" role="alert">{problems.map(problem => <li key={problem}>{problem}</li>)}</ul>}
      <div className="manage-actions">
        <button type="button" className="secondary" disabled={running} onClick={close}>Cancelar</button>
        <button type="button" className="danger-button" disabled={running} onClick={() => void remove()}>
          {running && <LoaderCircle className="spin" size={16}/>} {physical ? 'Borrar archivos' : 'Quitar del listado'}
        </button>
      </div>
    </div>
  </Modal>;
}

export function SelectionBar({ count, all, onAll, onRemove }: {
  count: number; all: boolean; onAll: () => void; onRemove: () => void;
}) {
  return <div className="selection-bar">
    <label><input type="checkbox" checked={all} onChange={onAll}/> Seleccionar todos</label>
    <span>{count} seleccionados</span>
    <button className="secondary danger-link" disabled={!count} onClick={onRemove}><Trash2 size={16}/> Eliminar selección</button>
  </div>;
}

export function RemoveButton({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return <button className="secondary danger-link" disabled={disabled} onClick={onClick}><Trash2 size={15}/>{children}</button>;
}

export function StoragePanel({ onCleaned, space }: { onCleaned: () => void; space?: DiskSpace }) {
  const [data, setData] = useState<StorageStats | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [selecting, setSelecting] = useState(false);
  const [target, setTarget] = useState('');
  const [folders, setFolders] = useState<FolderListing | null>(null);
  const [folderError, setFolderError] = useState('');
  async function refresh() {
    try { setData(await request<StorageStats>('/storage')); setError(''); }
    catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { void refresh(); }, []);

  async function browse(directory?: string) {
    setFolderError('');
    try {
      const query = directory ? '?directory=' + encodeURIComponent(directory) : '';
      setFolders(await request<FolderListing>('/storage/folders' + query));
    } catch (cause) { setFolderError((cause as Error).message); }
  }

  async function changeDirectory(directory: string | null) {
    setBusy(true);
    setFolderError('');
    setError('');
    try {
      const result = await request<LocationStatus>('/storage/location', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ directory }),
      });
      setData(previous => previous ? { ...previous, ...result } : previous);
      setSelecting(false);
    } catch (cause) {
      if (directory === null) setError((cause as Error).message);
      else setFolderError((cause as Error).message);
    } finally { setBusy(false); }
  }
  async function cleanup() {
    setBusy(true);
    try {
      const result = await request<{ removed: number; errors: string[]; storage: StorageStats }>('/storage/cleanup', { method: 'POST' });
      setData(result.storage);
      setMessage(`Temporales retirados: ${result.removed}.`);
      setError([...new Set(result.errors)].join(' '));
      onCleaned();
      setConfirm(false);
    } catch (e) { setError((e as Error).message); setConfirm(false); }
    finally { setBusy(false); }
  }
  return <section className="panel storage-panel">
    <div className="panel-heading"><div><HardDrive size={19}/><h2>Almacenamiento local</h2></div><button className="secondary" onClick={() => void refresh()}>Actualizar</button></div>
    {data && <div className="storage-location">
      <div><strong>Carpeta de almacenamiento</strong><p>{data.directory}</p></div>
      <button className="secondary" disabled={!data.location_configurable || busy} onClick={() => {
        setTarget(data.pending_directory ?? data.directory);
        setFolderError('');
        setFolders(null);
        setSelecting(true);
      }}>Cambiar carpeta</button>
      {data.pending_directory && <div className="storage-location-note">
        <p role="status">Cambio programado a <strong>{data.pending_directory}</strong>. Cierra la terminal del servidor con Ctrl+C y vuelve a abrir ClipZone. La comprobación de los archivos puede tardar varios minutos.</p>
        <button className="secondary" disabled={busy} onClick={() => void changeDirectory(null)}>Cancelar cambio</button>
      </div>}
      {data.migration_error && <p className="manage-warning storage-location-note" role="alert">{data.migration_error}</p>}
      {data.migration_warning && <p className="manage-warning storage-location-note" role="alert">{data.migration_warning}</p>}
      {!data.pending_directory && data.verified_files !== null && <p className="storage-location-note" role="status">Biblioteca migrada. {data.verified_files} archivos verificados con SHA-256 y copia de SQLite comprobada.</p>}
      {!data.location_configurable && <p className="storage-location-note">Ubicación definida por CLIPZONE_DATA_DIR.</p>}
    </div>}
    {data && <div className="storage-location disk-space"><DiskWarning space={space ?? data}/></div>}
    {data && <dl className="storage-metrics">
      <div><dt>Espacio libre en la unidad</dt><dd>{(space ?? data).free_bytes === null ? 'Sin datos' : diskGB((space ?? data).free_bytes!)}</dd>
        <small>{(space ?? data).disk_bytes === null ? '' : 'Capacidad de ' + diskGB((space ?? data).disk_bytes!)}</small></div>
      <div><dt>Caché de vistas exactas</dt><dd>{diskGB(data.draft_bytes)}</dd><small>Máximo de {diskGB(data.draft_limit_bytes)}</small></div>
      <div><dt>Vídeos importados</dt><dd>{data.video_count}</dd><small>{bytes(data.video_bytes)} en vídeos, proxies y miniaturas</small></div>
      <div><dt>Clips exportados</dt><dd>{data.export_count}</dd><small>{bytes(data.export_bytes)} en archivos MP4</small></div>
      <div><dt>Transcripciones</dt><dd>{bytes(data.transcript_bytes)}</dd><small>Dentro de SQLite</small></div>
      <div><dt>Archivos temporales</dt><dd>{bytes(data.temporary_bytes)}</dd></div>
      <div><dt>Base de datos</dt><dd>{bytes(data.database_bytes)}</dd></div>
      <div><dt>Modelos de Whisper</dt><dd>{bytes(data.model_bytes)}</dd></div>
      <div><dt>Gráficos PNG</dt><dd>{bytes(data.graphics_bytes ?? 0)}</dd></div>
      <div><dt>Total administrado</dt><dd>{bytes(data.total_bytes)}</dd><small>Incluye copias conservadas en disco</small></div>
    </dl>}
    <div className="storage-footer">
      {message && <p role="status">{message}</p>}
      {error && <p className="manage-warning" role="alert">{error}</p>}
      <RemoveButton onClick={() => setConfirm(true)}>Limpiar temporales</RemoveButton>
    </div>
    {selecting && <Modal title="Cambiar carpeta de almacenamiento" onClose={() => { if (!busy) setSelecting(false); }}>
      <form className="manage-dialog storage-picker" onSubmit={event => { event.preventDefault(); void changeDirectory(target.trim()); }}>
        <p>Elige una carpeta vacía o escribe la ruta de una carpeta nueva. Al reiniciar, ClipZone comprobará la copia antes de retirar los archivos antiguos.</p>
        <label>Carpeta de destino<input value={target} onChange={event => setTarget(event.target.value)} required maxLength={2048}/></label>
        <button type="button" className="secondary" onClick={() => void browse()}>Examinar unidades</button>
        {folders && <div className="storage-folders">
          {folders.path && <p>{folders.path}</p>}
          {folders.path && <button type="button" className="secondary" onClick={() => void browse(folders.parent ?? undefined)}>Subir</button>}
          {folders.path && <button type="button" className="secondary" onClick={() => setTarget(folders.path!)}>Usar esta carpeta</button>}
          {folders.folders.map(folder => <button type="button" className="text-button" key={folder} onClick={() => void browse(folder)}>
            {folder.split(/[\\/]/).filter(Boolean).at(-1) ?? folder}
          </button>)}
        </div>}
        {folderError && <p className="manage-warning" role="alert">{folderError}</p>}
        <div className="manage-actions">
          <button type="button" className="secondary" disabled={busy} onClick={() => setSelecting(false)}>Cancelar</button>
          <button className="primary" disabled={busy || !target.trim() || target === data?.directory}>Programar cambio</button>
        </div>
      </form>
    </Modal>}
    {confirm && <Modal title="Limpiar archivos temporales" onClose={() => { if (!busy) setConfirm(false); }}>
      <div className="manage-dialog"><p>Se borrarán las vistas exactas guardadas y archivos de trabajos que ya terminaron. Las transcripciones y los procesos activos se conservan.</p>
        <div className="manage-actions"><button className="secondary" disabled={busy} onClick={() => setConfirm(false)}>Cancelar</button>
          <button className="danger-button" disabled={busy} onClick={() => void cleanup()}>{busy && <LoaderCircle className="spin" size={16}/>} Limpiar archivos</button></div>
      </div>
    </Modal>}
  </section>;
}
