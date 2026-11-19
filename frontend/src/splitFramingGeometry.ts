import type { SourceGeometry, SourceRect, SplitLayout, SplitRegion } from './api';

export const emptyGameplay = 'La región de gameplay queda dentro de la cámara. Amplíala o muévela en Original.';
const epsilon = 1e-7;
const right = (rect: SourceRect) => rect.x + rect.width;
const bottom = (rect: SourceRect) => rect.y + rect.height;
const area = (rect: SourceRect) => rect.width * rect.height;

function overlap(a: SourceRect, b: SourceRect) {
  const width = Math.max(0, Math.min(right(a), right(b)) - Math.max(a.x, b.x));
  const height = Math.max(0, Math.min(bottom(a), bottom(b)) - Math.max(a.y, b.y));
  return width * height;
}

function inwardAxis(start: number, end: number, length: number, aligned: boolean): [number, number] {
  for (const step of aligned ? [2, 1] : [1]) {
    const left = Math.max(0, step * Math.ceil((start - epsilon) / step));
    const right = Math.min(length, step * Math.floor((end + epsilon) / step));
    if (right > left) return [left, right - left];
  }
  return [Math.min(length - 1, Math.floor((start + end) / 2)), 1];
}

function pixelBounds(rect: SourceRect, source: SourceGeometry, outward = false): SourceRect {
  const x = rect.x * source.width, endX = right(rect) * source.width;
  const y = rect.y * source.height, endY = bottom(rect) * source.height;
  if (outward) {
    const left = 2 * Math.floor((x + epsilon) / 2);
    const top = 2 * Math.floor((y + epsilon) / 2);
    return { x: left, y: top, width: Math.min(source.width, 2 * Math.ceil((endX - epsilon) / 2)) - left,
      height: Math.min(source.height, 2 * Math.ceil((endY - epsilon) / 2)) - top };
  }
  const [left, width] = inwardAxis(x, endX, source.width, true);
  const [top, height] = inwardAxis(y, endY, source.height, true);
  return { x: left, y: top, width, height };
}

const cropLength = (value: number, limit: number) => Math.min(limit, Math.max(2, 2 * Math.floor((value + epsilon) / 2)));
const alignedOffset = (value: number, limit: number) => Math.max(0, Math.min(limit, 2 * Math.round(value / 2)));

function preferredCrop(region: SplitRegion, bounds: SourceRect, aspect: number): SourceRect {
  const zoom = 100 / region.zoom;
  const width = cropLength(Math.min(bounds.width, bounds.height * aspect) * zoom, bounds.width);
  const height = cropLength(Math.min(bounds.height, bounds.width / aspect) * zoom, bounds.height);
  const x = bounds.x + alignedOffset((bounds.width - width) * (region.pan_x + 100) / 200, bounds.width - width);
  const y = bounds.y + alignedOffset((bounds.height - height) * (region.pan_y + 100) / 200, bounds.height - height);
  return { x, y, width, height };
}

function excludeCamera(desired: SourceRect, bounds: SourceRect, camera: SourceRect): SourceRect | undefined {
  if (!overlap(desired, camera)) return desired;
  const strips = [
    { ...bounds, width: camera.x - bounds.x },
    { ...bounds, x: right(camera), width: right(bounds) - right(camera) },
    { ...bounds, height: camera.y - bounds.y },
    { ...bounds, y: bottom(camera), height: bottom(bounds) - bottom(camera) },
  ];
  let best: { crop: SourceRect; size: number; retained: number; distance: number } | undefined;
  for (const strip of strips) {
    if (Math.min(strip.width, strip.height) < 1) continue;
    const scale = Math.min(1, strip.width / desired.width, strip.height / desired.height);
    const width = cropLength(desired.width * scale, Math.min(strip.width, desired.width));
    const height = cropLength(desired.height * scale, Math.min(strip.height, desired.height));
    const centerX = desired.x + (desired.width - width) / 2;
    const centerY = desired.y + (desired.height - height) / 2;
    const x = strip.x + alignedOffset(centerX - strip.x, strip.width - width);
    const y = strip.y + alignedOffset(centerY - strip.y, strip.height - height);
    const crop = { x, y, width, height };
    const dx = 2 * (x - centerX), dy = 2 * (y - centerY);
    const size = area(crop), retained = overlap(crop, desired), distance = dx * dx + dy * dy;
    if (!best || size > best.size || (size === best.size &&
      (retained > best.retained || (retained === best.retained && distance < best.distance)))) {
      best = { crop, size, retained, distance };
    }
  }
  return best?.crop;
}

export interface PanelGeometry {
  crop: SourceRect;
  width: number;
  height: number;
  scaledWidth: number;
  scaledHeight: number;
}

function panelGeometry(crop: SourceRect, width: number, height: number, pixelAspect: number): PanelGeometry {
  const aspect = crop.width * pixelAspect / crop.height;
  return { crop, width, height, scaledWidth: Math.max(width, 2 * Math.ceil((height * aspect - epsilon) / 2)),
    scaledHeight: Math.max(height, 2 * Math.ceil((width / aspect - epsilon) / 2)) };
}

// Match split_geometry in the renderer. All crop coordinates are in the oriented original's native pixels.
export function splitGeometry(layout: SplitLayout, width: number, height: number, source: SourceGeometry) {
  const cameraHeight = 2 * Math.round(height * layout.camera_share / 200);
  const gameplayHeight = height - cameraHeight;
  const pixelAspect = source.display_width / source.width;
  const camera = preferredCrop(layout.camera, pixelBounds(layout.camera.rect, source), width / cameraHeight / pixelAspect);
  const gameplayBounds = pixelBounds(layout.gameplay.rect, source);
  const desired = preferredCrop(layout.gameplay, gameplayBounds, width / gameplayHeight / pixelAspect);
  const gameplay = excludeCamera(desired, gameplayBounds, pixelBounds(layout.camera.rect, source, true));
  return gameplay ? {
    camera: panelGeometry(camera, width, cameraHeight, pixelAspect),
    gameplay: panelGeometry(gameplay, width, gameplayHeight, pixelAspect),
  } : null;
}

export type SplitGeometry = NonNullable<ReturnType<typeof splitGeometry>>;

export function decodedCrop(crop: SourceRect, source: SourceGeometry, video: HTMLVideoElement): SourceRect {
  const sx = video.videoWidth / source.width;
  const sy = video.videoHeight / source.height;
  const [x, width] = inwardAxis(crop.x * sx, right(crop) * sx, video.videoWidth, false);
  const [y, height] = inwardAxis(crop.y * sy, bottom(crop) * sy, video.videoHeight, false);
  return { x, y, width, height };
}
