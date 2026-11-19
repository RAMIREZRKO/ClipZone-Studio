export const MIN_CLIP_SECONDS = 0.1;

export function roundTimelineTime(value: number) {
  return Math.round(value * 100) / 100;
}

export function latestClipStart(end: number) {
  return Math.max(0, Math.floor((end - MIN_CLIP_SECONDS) * 100 + 1e-9) / 100);
}

export function earliestClipEnd(start: number, duration: number) {
  return Math.min(duration, Math.ceil((start + MIN_CLIP_SECONDS) * 100 - 1e-9) / 100);
}

export function formatTimecode(seconds: number, showHundredths = false) {
  const total = Math.max(0, Math.round(seconds * 100));
  const hours = Math.floor(total / 360_000);
  const minutes = Math.floor(total / 6_000) % 60;
  const wholeSeconds = Math.floor(total / 100) % 60;
  const pad = (value: number) => String(value).padStart(2, '0');
  const time = [hours, minutes, wholeSeconds].map(pad).join(':');
  return showHundredths ? `${time}.${pad(total % 100)}` : time;
}
