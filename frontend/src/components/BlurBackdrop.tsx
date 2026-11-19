import { useEffect, useRef, type RefObject } from 'react';

export function BlurBackdrop({ player, source, aspect, strength }: {
  player: RefObject<HTMLVideoElement | null>;
  source: string;
  aspect: number;
  strength: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const video = player.current;
    const target = canvas.current;
    const context = target?.getContext('2d');
    if (!video || !target || !context) return;
    target.width = Math.round(320 * Math.min(1, aspect));
    target.height = Math.round(target.width / aspect);

    function draw() {
      if (!video || !target || !context || video.readyState < 2 || !video.videoWidth) return;
      const scale = Math.max(target.width / video.videoWidth, target.height / video.videoHeight);
      const width = video.videoWidth * scale;
      const height = video.videoHeight * scale;
      context.filter = `blur(${strength / 100 * Math.min(target.width, target.height) * .055}px)`;
      context.drawImage(video, (target.width - width) / 2, (target.height - height) / 2, width, height);
    }

    let callback = 0;
    function frame() {
      draw();
      callback = video!.requestVideoFrameCallback(frame);
    }
    draw();
    callback = video.requestVideoFrameCallback(frame);
    video.addEventListener('seeked', draw);
    video.addEventListener('loadeddata', draw);
    return () => {
      video.cancelVideoFrameCallback(callback);
      video.removeEventListener('seeked', draw);
      video.removeEventListener('loadeddata', draw);
    };
  }, [player, source, aspect, strength]);

  return <canvas ref={canvas} className="blur-backdrop" aria-hidden="true"/>;
}
