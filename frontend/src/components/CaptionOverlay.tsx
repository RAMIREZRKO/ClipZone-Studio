import { useEffect, useMemo, useRef, useState } from 'react';
import { request, type CaptionSegment, type CaptionStyle, type SplitLayout } from '../api';

interface CaptionPage {
  start: number;
  end: number;
  frames: { start: number; end: number; image: number }[];
  images: string[];
}

const PRELOAD_SECONDS = 1.25;

export function CaptionOverlay({ segments, time, playing, style, language, ratio, resolution, safeTop, safeBottom, clipStart, clipEnd, splitLayout }: {
  segments: CaptionSegment[]; time: number; playing: boolean; style: CaptionStyle; language: string;
  ratio: string; resolution: number; safeTop: number; safeBottom: number; clipStart: number; clipEnd: number;
  splitLayout: SplitLayout | null;
}) {
  const config = useMemo(() => ({
    ratio, resolution, safe_top: safeTop, safe_bottom: safeBottom, start: clipStart, end: clipEnd, style, language,
    fit: splitLayout ? 'split' : 'contain', split_layout: splitLayout,
  }), [ratio, resolution, safeTop, safeBottom, clipStart, clipEnd, style, language, splitLayout]);
  const [layers, setLayers] = useState<{ config: typeof config; segment: CaptionSegment; page: CaptionPage }[]>([]);
  const [failure, setFailure] = useState<{ config: typeof config; segment: CaptionSegment; message: string } | null>(null);
  const requests = useRef(new Map<CaptionSegment, AbortController>());

  useEffect(() => {
    const pending = requests.current;
    return () => {
      for (const controller of pending.values()) controller.abort();
      pending.clear();
    };
  }, [config]);

  const at = time - clipStart;
  const getText = (segment: CaptionSegment) => (language === 'original' ? segment.text : segment.translations[language] ?? '').trim();
  const active = time >= clipStart && time < clipEnd ?
    segments.find(segment => segment.start <= time && time < segment.end && getText(segment)) : undefined;
  const findPage = (segment: CaptionSegment, position: number) =>
    layers.find(item => item.config === config && item.segment === segment &&
      item.page.start <= position && position < item.page.end)?.page;
  const page = active ? findPage(active, at) : undefined;
  const frame = page?.frames.find(item => item.start <= at && at < item.end);
  const image = page && frame ? page.images[frame.image] : undefined;

  useEffect(() => {
    function load(segment: CaptionSegment, position: number, preload = false) {
      const pending = requests.current;
      if (position < 0 || position >= clipEnd - clipStart || findPage(segment, position) || pending.has(segment) ||
          (failure?.config === config && failure.segment === segment)) return;
      for (const [previous, controller] of pending) {
        if (previous.id === segment.id) {
          controller.abort();
          pending.delete(previous);
        }
      }
      if (pending.size >= 2) {
        if (preload) return;
        const oldest = pending.entries().next().value;
        if (oldest) {
          oldest[1].abort();
          pending.delete(oldest[0]);
        }
      }
      const controller = new AbortController();
      pending.set(segment, controller);
      const timer = window.setTimeout(() => {
        request<CaptionPage>('/captions/layer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...config, segment, time: position }),
          signal: controller.signal,
        }).then(result => {
          if (pending.get(segment) === controller) pending.delete(segment);
          if (controller.signal.aborted) return;
          setLayers(previous => [{ config, segment, page: result }, ...previous].slice(0, 12));
        }).catch(cause => {
          if (pending.get(segment) === controller) pending.delete(segment);
          if (!controller.signal.aborted && !preload) setFailure({ config, segment, message: (cause as Error).message });
        });
      }, playing ? 0 : 80);
      controller.signal.addEventListener('abort', () => window.clearTimeout(timer), { once: true });
    }

    if (active && !page) {
      load(active, at);
      return;
    }
    if (!playing || time >= clipEnd) return;
    if (active && page && page.end - at <= PRELOAD_SECONDS && page.end < Math.min(active.end, clipEnd) - clipStart - .005) {
      load(active, page.end, true);
      return;
    }
    const next = segments.find(segment => segment.start > time && segment.start <= time + PRELOAD_SECONDS &&
      segment.start < clipEnd && segment.end > clipStart && getText(segment));
    if (next) {
      const start = Math.max(0, next.start - clipStart);
      load(next, Math.max(start, Math.ceil(start * 100) / 100), true);
    }
  }, [active, at, page, config, clipEnd, clipStart, failure, layers, playing, segments, time]);

  if (failure?.config === config && failure.segment === active && !image) {
    return <span className="live-caption-status" role="status">{failure.message}</span>;
  }
  if (!image || !active) return null;
  return <div className="live-caption">
    <img alt="" src={`data:image/png;base64,${image}`}/>
    <span className="sr-only">{getText(active)}</span>
  </div>;
}
