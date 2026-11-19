import { expect, test, type Locator, type Page } from '@playwright/test';
import path from 'node:path';

async function openTimeline(page: Page) {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  const video = page.locator('.video-frame video');
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThan(0);
  const cursor = page.getByRole('slider', { name: 'Posición de reproducción' });
  const start = page.getByRole('slider', { name: 'Ajustar entrada' });
  const end = page.getByRole('slider', { name: 'Ajustar salida' });
  const track = page.locator('.timeline-track');
  await track.scrollIntoViewIfNeeded();
  const duration = Number(await cursor.getAttribute('aria-valuemax'));
  return { video, cursor, start, end, track, duration };
}

async function dragBy(page: Page, handle: Locator, pixels: number) {
  const box = (await handle.boundingBox())!;
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + pixels, y, { steps: 8 });
  await page.mouse.up();
}

test('el cursor y los tiradores se arrastran de forma independiente', async ({ page }) => {
  const { video, cursor, start, end, track, duration } = await openTimeline(page);
  const geometry = await track.evaluate(element => ({
    x: element.getBoundingClientRect().left + element.clientLeft,
    y: element.getBoundingClientRect().top + 12,
    width: element.clientWidth,
  }));
  const pixelsPerSecond = geometry.width / duration;
  await dragBy(page, start, pixelsPerSecond);
  expect(Number(await start.getAttribute('aria-valuenow'))).toBeCloseTo(1, 1);
  await expect(cursor).toHaveAttribute('aria-valuetext', '00:00:00.00');
  await expect(end).toHaveAttribute('aria-valuenow', String(duration));
  await dragBy(page, end, (3 - duration) * pixelsPerSecond);
  expect(Number(await end.getAttribute('aria-valuenow'))).toBeCloseTo(3, 1);
  await expect(cursor).toHaveAttribute('aria-valuetext', '00:00:00.00');
  const inputTime = (await start.getAttribute('aria-valuenow'))!;
  const outputTime = (await end.getAttribute('aria-valuenow'))!;
  await dragBy(page, cursor, 2 * pixelsPerSecond);
  expect(Number(await cursor.getAttribute('aria-valuenow'))).toBeCloseTo(2, 1);
  await page.mouse.click(geometry.x + 4 * pixelsPerSecond, geometry.y);
  expect(Number(await cursor.getAttribute('aria-valuenow'))).toBeCloseTo(4, 1);
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeCloseTo(4, 1);
  await expect(start).toHaveAttribute('aria-valuenow', inputTime);
  await expect(end).toHaveAttribute('aria-valuenow', outputTime);
});

test('marcar límites usa centésimas y conserva el zoom hasta 32×', async ({ page }) => {
  const { video, cursor, start, end, track, duration } = await openTimeline(page);
  const markIn = page.getByRole('button', { name: 'Marcar entrada aquí' });
  const markOut = page.getByRole('button', { name: 'Marcar salida aquí' });
  await expect(markOut).toBeDisabled();
  await cursor.press('Shift+ArrowRight');
  await cursor.press('ArrowRight');
  await expect(cursor).toHaveAttribute('aria-valuetext', '00:00:01.01');
  await markIn.click();
  await expect(start).toHaveAttribute('aria-valuetext', '00:00:01.01');
  await expect(end).toHaveAttribute('aria-valuenow', String(duration));

  await cursor.press('Shift+ArrowRight');
  await cursor.press('ArrowRight');
  await markOut.click();
  await expect(end).toHaveAttribute('aria-valuetext', '00:00:02.02');
  await expect(start).toHaveAttribute('aria-valuetext', '00:00:01.01');
  await expect(cursor).toHaveAttribute('aria-valuetext', '00:00:02.02');
  await expect(markIn).toBeDisabled();

  const zoomIn = page.getByRole('button', { name: 'Acercar línea de tiempo' });
  for (let level = 0; level < 5; level++) await zoomIn.click();
  await expect(page.getByLabel('Zoom de línea de tiempo')).toHaveText('32×');
  await expect(zoomIn).toBeDisabled();
  await cursor.press('ArrowRight');
  await expect(cursor).toHaveAttribute('aria-valuetext', '00:00:02.03');
  const visibleTimeline = page.locator('.timeline-viewport');
  await expect.poll(() => visibleTimeline.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
  const pixelsPerSecond = await track.evaluate(element => element.clientWidth) / duration;
  await dragBy(page, cursor, 0.1 * pixelsPerSecond);
  await expect(cursor).toHaveAttribute('aria-valuetext', '00:00:02.13');
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeCloseTo(2.13, 2);
  await expect(start).toHaveAttribute('aria-valuetext', '00:00:01.01');
  await expect(end).toHaveAttribute('aria-valuetext', '00:00:02.02');
});
