import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test('conserva el volumen y el silencio en las tres vistas y tras recargar, con audio intacto en el MP4', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  const volume = page.getByRole('slider', { name: 'Volumen del reproductor' });
  await expect(volume).toHaveValue('100');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  const video = page.locator('.video-frame video');
  await expect(video).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(volume).toBeVisible();
  expect(await page.locator('.transport').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1100 });

  const audio = () => video.evaluate((element: HTMLVideoElement) => ({ volume: element.volume, muted: element.muted }));
  const mute = page.getByRole('button', { name: 'Silenciar', exact: true });
  const restore = page.getByRole('button', { name: 'Activar sonido', exact: true });
  const original = page.getByRole('button', { name: 'Original', exact: true });
  const live = page.getByRole('button', { name: 'Encuadre en directo', exact: true });
  const exact = page.getByRole('button', { name: 'Vista exacta', exact: true });
  await volume.fill('37');
  await expect(volume).toHaveAttribute('aria-valuetext', '37%');
  await expect.poll(audio).toEqual({ volume: .37, muted: false });
  await original.click();
  await expect.poll(audio).toEqual({ volume: .37, muted: false });
  await mute.click();
  await live.click();
  await expect(volume).toHaveValue('0');
  await expect.poll(audio).toEqual({ volume: 0, muted: true });
  await restore.click();
  await expect(volume).toHaveValue('37');

  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await page.getByText('Ajuste de precisión', { exact: true }).click();
  const end = page.getByLabel('Salida en segundos');
  await end.fill('2');
  await end.press('Enter');
  const title = 'Prueba de audio del reproductor';
  await page.getByLabel('Nombre del clip').fill(title);
  await exact.click();
  await expect(video).toHaveAttribute('src', /\/api\/jobs\//);
  const draft = (await video.getAttribute('src'))!;
  await expect.poll(audio).toEqual({ volume: .37, muted: false });
  await volume.press('Home');
  await expect(volume).toHaveValue('0');
  await expect.poll(audio).toEqual({ volume: 0, muted: true });
  await restore.click();
  await expect.poll(audio).toEqual({ volume: .37, muted: false });
  await mute.click();
  await original.click();
  await exact.click();
  await expect(video).toHaveAttribute('src', draft);
  await expect.poll(audio).toEqual({ volume: 0, muted: true });

  await page.getByRole('button', { name: 'Exportar clip', exact: true }).click();
  const card = page.locator('.export-card').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  await expect(card.getByText('Listo para compartir')).toBeVisible({ timeout: 30_000 });
  const download = await card.getByRole('link', { name: 'Descargar', exact: true }).getAttribute('href');
  const draftBytes = await (await page.request.get(draft)).body();
  const exportBytes = await (await page.request.get(download!)).body();
  expect(exportBytes.equals(draftBytes)).toBe(true);
  const bundled = path.resolve('../tools/ffmpeg/bin/ffmpeg.exe');
  const ffmpeg = process.env.CLIPZONE_FFMPEG || (existsSync(bundled) ? bundled : 'ffmpeg');
  const pcm = execFileSync(ffmpeg, ['-v', 'error', '-i', 'pipe:0', '-map', '0:a:0', '-t', '0.5',
    '-c:a', 'pcm_s16le', '-f', 's16le', 'pipe:1'], { input: exportBytes, timeout: 15_000 });
  expect(pcm.some(byte => byte !== 0)).toBe(true);

  await page.reload();
  await expect(volume).toHaveValue('0');
  await page.getByRole('button', { name: /Mis vídeos/ }).click();
  await page.locator('.video-card-open').first().click();
  await expect.poll(audio).toEqual({ volume: 0, muted: true });
  await restore.click();
  await expect(volume).toHaveValue('37');
  await page.reload();
  await expect(volume).toHaveValue('37');
});

