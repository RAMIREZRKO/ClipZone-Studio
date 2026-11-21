import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Locator } from '@playwright/test';
import type { Job } from '../src/api';

async function colors(surface: Locator) {
  return surface.evaluate(element => {
    const canvas = element instanceof HTMLCanvasElement ? element : document.createElement('canvas');
    if (element instanceof HTMLVideoElement) {
      if (element.readyState < 2) return [];
      canvas.width = element.videoWidth;
      canvas.height = element.videoHeight;
      canvas.getContext('2d')!.drawImage(element, 0, 0);
    }
    const ctx = canvas.getContext('2d')!;
    return [.15, .60, .68, .86].map(fraction => {
      const [r, g, b] = ctx.getImageData(Math.floor(canvas.width / 2), Math.floor(canvas.height * fraction), 1, 1).data;
      return g > 180 && r < 75 && b < 75 ? 'camera' : b > 180 && r < 75 && g < 75 ? 'gameplay' : 'other';
    });
  });
}

async function captionCenter(surface: Locator) {
  return surface.evaluate(element => {
    const video = element instanceof HTMLVideoElement;
    const source = element as HTMLVideoElement | HTMLImageElement;
    const width = video ? (source as HTMLVideoElement).videoWidth : (source as HTMLImageElement).naturalWidth;
    const height = video ? (source as HTMLVideoElement).videoHeight : (source as HTMLImageElement).naturalHeight;
    if (!width || (video && (source as HTMLVideoElement).readyState < 2)) return null;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d')!;
    ctx.drawImage(source, 0, 0);
    const { data } = ctx.getImageData(0, 0, width, height);
    let minX = width, minY = height, maxX = 0, maxY = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] < 180 || data[i + 1] > 90 || data[i + 2] < 180 || data[i + 3] < 150) continue;
      const x = i / 4 % width;
      const y = Math.floor(i / 4 / width);
      minX = Math.min(minX, x); minY = Math.min(minY, y);
      maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
    }
    return minX < width ? [(minX + maxX) / (2 * width), (minY + maxY) / (2 * height)] : null;
  });
}

test('ajusta las regiones con el ratón, invierte el reparto y recupera el encuadre de la plantilla', async ({ page }, info) => {
  const source = info.outputPath('gameplay con cámara.mp4');
  mkdirSync(path.dirname(source), { recursive: true });
  const bundled = path.resolve('../tools/ffmpeg/bin/ffmpeg.exe');
  const ffmpeg = process.env.CLIPZONE_FFMPEG || (existsSync(bundled) ? bundled : 'ffmpeg');
  const picture = 'color=blue:size=640x360:rate=24,drawbox=64:36:128:144:color=red:t=fill,' +
    "drawbox=128:36:64:144:color=lime:t=fill,drawbox=320:0:320:360:color=white:t=fill:enable='gte(t,0.65)'";
  execFileSync(ffmpeg, ['-v', 'error', '-y', '-f', 'lavfi', '-i',
    picture,
    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '2',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', source], { timeout: 15_000 });
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(source);
  const video = page.locator('.video-frame video');
  await expect(video).toBeVisible();
  const button = (name: string) => page.getByRole('button', { name, exact: true });
  const commit = async (name: string, value: string) => {
    const field = page.getByRole('spinbutton', { name, exact: true });
    await field.fill(value);
    await field.press('Enter');
  };
  await button('Streamer + Gameplay').click();
  await button('Editar regiones en Original').click();
  const camera = page.locator('.split-source-rect[data-region=camera]');
  await expect(camera).toBeVisible();
  const handle = (await camera.locator('.split-handle.se').boundingBox())!;
  const before = (await camera.boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2 + 28, handle.y + handle.height / 2 + 12, { steps: 5 });
  await page.mouse.up();
  expect((await camera.boundingBox())!.width).toBeGreaterThan(before.width + 20);
  const moveBox = (await camera.boundingBox())!;
  await page.mouse.move(moveBox.x + moveBox.width / 2, moveBox.y + moveBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(moveBox.x + moveBox.width / 2 + 20, moveBox.y + moveBox.height / 2 + 10, { steps: 5 });
  await page.mouse.up();
  expect((await camera.boundingBox())!.x).toBeGreaterThan(moveBox.x + 15);

  await page.getByText('Coordenadas del recorte', { exact: true }).click();
  await commit('X (%)', '10'); await commit('Y (%)', '10');
  await commit('Ancho (%)', '20'); await commit('Alto (%)', '40');
  await commit('Zoom (%)', '200'); await commit('Centro horizontal del recorte', '100');
  await button('Gameplay').click();
  await expect(page.getByRole('spinbutton', { name: 'Zoom (%)' })).toHaveValue('100');
  await commit('Ancho (%)', '50'); await commit('X (%)', '50');
  await page.getByLabel('Distribución vertical').selectOption('custom');
  await commit('Altura de cámara (%)', '33.5');
  await page.getByRole('checkbox', { name: 'Invertir cámara y gameplay' }).check();
  await button('Encuadre en directo').click();
  const expected = ['gameplay', 'gameplay', 'camera', 'camera'];
  const composition = page.locator('.split-canvas');
  await expect.poll(() => colors(composition)).toEqual(expected);

  await page.getByLabel('Nombre de plantilla').fill('Streamer de prueba');
  await button('Guardar como plantilla').click();
  await expect(page.getByText('Plantilla guardada.')).toBeVisible();
  await page.getByLabel('Distribución vertical').selectOption('50');
  await expect.poll(() => colors(composition)).toEqual(['gameplay', 'camera', 'camera', 'camera']);
  await button('Aplicar plantilla').click();
  await expect(page.getByRole('spinbutton', { name: 'Altura de cámara (%)' })).toHaveValue('33.5');
  await expect.poll(() => colors(composition)).toEqual(expected);

  await video.evaluate((element: HTMLVideoElement) => element.play());
  await expect.poll(() => colors(composition)).toEqual(['other', 'other', 'camera', 'camera']);
  await video.evaluate((element: HTMLVideoElement) => { element.pause(); element.currentTime = 0; });
  await expect.poll(() => colors(composition)).toEqual(expected);

  const subtitles = page.getByRole('region', { name: 'Subtítulos dinámicos' });
  await subtitles.getByRole('button', { name: 'Añadir segmento' }).click();
  await subtitles.getByLabel('Texto del segmento 1').fill('Cámara');
  await subtitles.getByRole('checkbox', { name: 'Activar subtítulos' }).check();
  await subtitles.getByText('Estilo y posición de subtítulos', { exact: true }).click();
  await subtitles.getByLabel('Ubicación de subtítulos').selectOption('split');
  await commit('Posición horizontal (%)', '72');
  await subtitles.getByLabel('Color del texto', { exact: true }).fill('#ff00ff');
  await subtitles.getByRole('button', { name: 'Guardar subtítulos' }).click();
  await expect(subtitles.getByText('Cambios guardados.')).toBeVisible();
  const liveCaption = page.locator('.live-caption img');
  await expect(liveCaption).toBeVisible();
  await expect.poll(() => captionCenter(liveCaption)).not.toBeNull();
  const [x, y] = (await captionCenter(liveCaption))!;
  expect(x).toBeCloseTo(.72, 2);
  expect(y).toBeCloseTo(.665, 2);

  await button('Vista exacta').click();
  await expect(video).toHaveAttribute('src', /\/api\/jobs\//, { timeout: 40_000 });
  await expect.poll(() => colors(video)).toEqual(expected);
  expect(await video.evaluate((element: HTMLVideoElement) => [element.videoWidth, element.videoHeight])).toEqual([1080, 1920]);
  await expect.poll(() => captionCenter(video)).not.toBeNull();
  const [exactX, exactY] = (await captionCenter(video))!;
  expect(exactX).toBeCloseTo(x, 2);
  expect(exactY).toBeCloseTo(y, 2);
});

async function cameraMarker(surface: Locator) {
  return surface.evaluate(element => {
    const canvas = element instanceof HTMLCanvasElement ? element : document.createElement('canvas');
    if (element instanceof HTMLVideoElement) {
      if (element.readyState < 2) return null;
      canvas.width = element.videoWidth;
      canvas.height = element.videoHeight;
      canvas.getContext('2d')!.drawImage(element, 0, 0);
    }
    const { width, height } = canvas;
    const { data } = canvas.getContext('2d')!.getImageData(0, 0, width, height);
    let left = width, right = 0, top = height, bottom = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (Math.min(data[i], data[i + 1], data[i + 2]) < 190) continue;
      const x = i / 4 % width;
      const y = Math.floor(i / (4 * width));
      left = Math.min(left, x); right = Math.max(right, x);
      top = Math.min(top, y); bottom = Math.max(bottom, y);
    }
    if (left > right) return null;
    let seam = 0;
    for (let y = 0; y < height; y++) {
      const i = (y * width + Math.floor(width / 2)) * 4;
      if (data[i + 2] > 180 && data[i] < 75) { seam = y; break; }
    }
    return {
      x: (left + right + 1) * 240 / width, y: (top + bottom + 1) * 427 / height,
      width: (right - left + 1) * 480 / width, height: (bottom - top + 1) * 854 / height,
      seam: seam * 854 / height,
    };
  });
}

test('Llenar recalcula el recorte sin deformarlo en directo, en Vista exacta y al exportar', async ({ page, request }, info) => {
  test.setTimeout(120_000);
  const source = info.outputPath('cámara con referencia cuadrada.mp4');
  mkdirSync(path.dirname(source), { recursive: true });
  const bundled = path.resolve('../tools/ffmpeg/bin/ffmpeg.exe');
  const ffmpeg = process.env.CLIPZONE_FFMPEG || (existsSync(bundled) ? bundled : 'ffmpeg');
  const picture = 'color=blue:size=640x360:rate=24,drawbox=64:36:240:144:color=red:t=fill,' +
    'drawbox=174:98:20:20:color=white:t=fill';
  execFileSync(ffmpeg, ['-v', 'error', '-y', '-f', 'lavfi', '-i', picture, '-t', '0.6',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', source], { timeout: 15_000 });

  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(source);
  const button = (name: string) => page.getByRole('button', { name, exact: true });
  const field = (name: string) => page.getByRole('spinbutton', { name, exact: true });
  const commit = async (name: string, value: number) => {
    await field(name).fill(String(value));
    await field(name).press('Enter');
  };
  const video = page.locator('.video-frame video');
  const live = page.locator('.split-canvas');
  await expect(video).toBeVisible();
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await button('Streamer + Gameplay').click();
  await page.getByText('Coordenadas del recorte', { exact: true }).click();
  await commit('X (%)', 10); await commit('Y (%)', 10);
  await commit('Ancho (%)', 37.5); await commit('Alto (%)', 40);
  await button('Gameplay').click();
  await commit('Ancho (%)', 50); await commit('X (%)', 50);
  await button('Cámara').click();

  const shares = [20, 25, 30, 40, 50, 10, 33.5, 90, 20];
  for (let i = 0; i < shares.length; i++) {
    const share = shares[i];
    await test.step(`Cámara al ${share}% (paso ${i + 1})`, async () => {
      const custom = share === 10 || share === 33.5 || share === 90;
      await page.getByLabel('Distribución vertical').selectOption(custom ? 'custom' : String(share));
      if (custom) await commit('Altura de cámara (%)', share);
      const zoom = share === 33.5 ? 150 : 100;
      const panX = share === 50 ? 75 : 0;
      const panY = i === 0 ? -75 : i === shares.length - 1 ? 75 : 0;
      await commit('Zoom (%)', zoom);
      await commit('Centro horizontal del recorte', panX);
      await commit('Centro vertical del recorte', panY);

      const seam = 2 * Math.round(854 * share / 200);
      const scale = Math.max(480 / 240, seam / 144) * zoom / 100;
      const expected = {
        x: 240 - (240 * scale - 480) * panX / 200,
        y: seam / 2 - (144 * scale - seam) * panY / 200,
        width: 20 * scale, height: 20 * scale, seam,
      };
      const checkMarker = async (surface: Locator) => {
        await expect.poll(async () => {
          const marker = await cameraMarker(surface);
          return marker ? Math.max(...(Object.keys(expected) as (keyof typeof expected)[])
            .map(key => Math.abs(marker[key] - expected[key]))) : Infinity;
        }).toBeLessThan(8);
      };
      await button('Encuadre en directo').click();
      await checkMarker(live);
      await button('Vista exacta').click();
      await expect(video).toHaveAttribute('src', /\/api\/jobs\//);
      await checkMarker(video);
      const exact = await request.get((await video.getAttribute('src'))!);
      expect(exact.ok()).toBe(true);

      const queued = page.waitForResponse(response => response.url().endsWith('/api/clips') && response.request().method() === 'POST');
      await button('Exportar clip').click();
      const response = await queued;
      expect(response.status()).toBe(202);
      const { id, settings } = await response.json() as Job;
      expect(settings?.split_layout).toMatchObject({ camera_share: share, camera: {
        rect: { x: .1, y: .1, width: .375, height: .4 }, zoom, pan_x: panX, pan_y: panY,
      } });
      await expect.poll(async () => (await (await request.get(`/api/jobs/${id}`)).json()).status).toBe('completed');
      const exported = await request.get(`/api/jobs/${id}/download`);
      expect(exported.ok()).toBe(true);
      expect((await exported.body()).equals(await exact.body())).toBe(true);
      await button('Editor de clips').click();
    });
  }
});

async function sampledColors(surface: Locator, points: [number, number][]) {
  return surface.evaluate((element, samples) => {
    const canvas = element instanceof HTMLCanvasElement ? element : document.createElement('canvas');
    if (element instanceof HTMLVideoElement) {
      if (element.readyState < 2) return [];
      canvas.width = element.videoWidth;
      canvas.height = element.videoHeight;
      canvas.getContext('2d')!.drawImage(element, 0, 0);
    }
    const ctx = canvas.getContext('2d')!;
    return samples.map(([x, y]) => {
      const [r, g, b] = ctx.getImageData(Math.floor(x * canvas.width / 480), Math.floor(y * canvas.height / 854), 1, 1).data;
      if (b > 180 && r < 65 && g < 65) return 'blue';
      if (g > 180 && r < 65 && b < 65) return 'green';
      if (Math.min(r, g, b) > 210) return 'white';
      if (Math.max(r, g, b) < 40) return 'black';
      return 'other';
    });
  }, points);
}

test('el texto gancho en la unión coincide en directo, en Vista exacta y en el MP4', async ({ page, request }, info) => {
  const source = info.outputPath('fondo del texto gancho.mp4');
  mkdirSync(path.dirname(source), { recursive: true });
  const bundled = path.resolve('../tools/ffmpeg/bin/ffmpeg.exe');
  const ffmpeg = process.env.CLIPZONE_FFMPEG || (existsSync(bundled) ? bundled : 'ffmpeg');
  const picture = 'color=blue:size=640x360:rate=24,drawbox=0:0:240:115:color=green:t=fill';
  execFileSync(ffmpeg, ['-v', 'error', '-y', '-f', 'lavfi', '-i', picture, '-t', '0.8',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', source], { timeout: 15_000 });
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(source);
  const button = (name: string) => page.getByRole('button', { name, exact: true });
  const video = page.locator('.video-frame video');
  await expect(video).toBeVisible();
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await button('Streamer + Gameplay').click();
  await page.getByLabel('Distribución vertical').selectOption('50');
  const panel = page.getByRole('region', { name: 'Gráficos y plantillas' });
  await panel.getByRole('button', { name: 'Crear texto gancho' }).click();
  await expect(panel.getByLabel('Tamaño a 1080p (px)')).toHaveValue('44');
  await expect(panel.getByLabel('Color del texto')).toHaveValue('#ffffff');
  await expect(panel.getByLabel('Posición del gancho')).toHaveValue('split');
  await panel.getByLabel('Texto gancho', { exact: true }).fill('Ahora empieza el clip');
  await panel.getByLabel('Color del texto').fill('#ff00ff');
  await panel.getByLabel('Nombre del estilo').fill('Gancho de prueba');
  await button('Guardar estilo de gancho').click();
  await expect(panel.getByText('Estilo de gancho guardado.')).toBeVisible();
  await panel.getByLabel('Fuente', { exact: true }).selectOption('Poppins');
  const style = await request.get('/api/templates');
  const saved = (await style.json()).find((template: { kind?: string }) => template.kind === 'hook');
  await panel.getByLabel('Aplicar estilo de gancho').selectOption(saved.id);
  await expect(panel.getByLabel('Fuente', { exact: true })).toHaveValue('Arial');
  await expect(page.getByLabel('Distribución vertical')).toHaveValue('50');
  const art = page.locator('.text-raster');
  await expect.poll(() => captionCenter(art)).not.toBeNull();
  const [artX, artY] = (await captionCenter(art))!;
  const frame = (await page.locator('.video-frame').boundingBox())!;
  const box = (await art.boundingBox())!;
  const x = (box.x + artX * box.width - frame.x) / frame.width;
  const y = (box.y + artY * box.height - frame.y) / frame.height;
  expect(x).toBeCloseTo(.5, 2);
  expect(y).toBeCloseTo(.5, 2);
  await button('Vista exacta').click();
  await expect(video).toHaveAttribute('src', /\/api\/jobs\//);
  await expect.poll(() => captionCenter(video)).not.toBeNull();
  const [exactX, exactY] = (await captionCenter(video))!;
  expect(exactX).toBeCloseTo(x, 2);
  expect(exactY).toBeCloseTo(y, 2);
  const exact = await request.get((await video.getAttribute('src'))!);
  const submitted = page.waitForResponse(r => r.url().endsWith('/api/clips') && r.request().method() === 'POST');
  await button('Exportar clip').click();
  const { id } = await (await submitted).json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${id}`)).json()).status).toBe('completed');
  const exported = await request.get(`/api/jobs/${id}/download`);
  expect((await exported.body()).equals(await exact.body())).toBe(true);
});

test('excluye la cámara de inmediato, limita el desplazamiento y conserva las regiones', async ({ page, request }, info) => {
  const source = info.outputPath('gameplay con cámara incrustada.mp4');
  mkdirSync(path.dirname(source), { recursive: true });
  const bundled = path.resolve('../tools/ffmpeg/bin/ffmpeg.exe');
  const ffmpeg = process.env.CLIPZONE_FFMPEG || (existsSync(bundled) ? bundled : 'ffmpeg');
  const stripes = [64, 80, 96, 112, 128].map(x => `drawbox=${x}:40:8:80:color=black:t=fill`).join(',');
  const picture = `color=blue:size=640x360:rate=24,drawbox=64:40:80:80:color=white:t=fill,${stripes},` +
    'drawbox=196:166:20:20:color=lime:t=fill,drawbox=12:166:20:20:color=lime:t=fill';
  execFileSync(ffmpeg, ['-v', 'error', '-y', '-f', 'lavfi', '-i', picture, '-t', '0.8',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', source], { timeout: 15_000 });

  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(source);
  const button = (name: string) => page.getByRole('button', { name, exact: true });
  const field = (name: string) => page.getByRole('spinbutton', { name, exact: true });
  const commit = async (name: string, value: string) => {
    await field(name).fill(value);
    await field(name).press('Enter');
  };
  const live = page.locator('.split-canvas');
  const video = page.locator('.video-frame video');
  await expect(video).toBeVisible();
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await button('Streamer + Gameplay').click();
  await expect(page.locator('.split-controls select')).toHaveCount(1);
  await page.getByText('Coordenadas del recorte', { exact: true }).click();
  await commit('X (%)', '10'); await commit('Y (%)', '11.11');
  await commit('Ancho (%)', '12.5'); await commit('Alto (%)', '22.22');
  await button('Gameplay').click();
  await commit('Zoom (%)', '125');
  await commit('Centro horizontal del recorte', '-42');
  await commit('Centro vertical del recorte', '25');

  await button('Cámara').click();
  const cameraX = field('X (%)');
  const cameraPoint: [number, number][] = [[28, 107]];
  await expect.poll(() => sampledColors(live, cameraPoint)).toEqual(['black']);
  await cameraX.fill('11,25');
  await expect(cameraX).toBeFocused();
  await expect.poll(() => sampledColors(live, cameraPoint)).toEqual(['white']);
  await cameraX.fill('-');
  await expect.poll(() => sampledColors(live, cameraPoint)).toEqual(['black']);
  await cameraX.fill('11,25');
  await cameraX.press('Escape');
  await expect(cameraX).toHaveValue('10');
  await expect.poll(() => sampledColors(live, cameraPoint)).toEqual(['black']);

  await cameraX.fill('11,25');
  await expect.poll(() => sampledColors(live, cameraPoint)).toEqual(['white']);
  const preview = page.waitForRequest(r => r.url().endsWith('/api/clips/preview') && r.method() === 'POST');
  await button('Vista exacta').click();
  expect((await preview).postDataJSON().split_layout.camera.rect.x).toBe(.1125);
  await expect(video).toHaveAttribute('src', /\/api\/jobs\//);
  await expect.poll(() => sampledColors(video, cameraPoint)).toEqual(['white']);
  await button('Encuadre en directo').click();
  await expect.poll(() => sampledColors(live, cameraPoint)).toEqual(['white']);
  await commit('X (%)', '10');
  await button('Gameplay').click();

  const croppedPoints: [number, number][] = [[8, 289], [23, 289], [138, 503]];
  await expect.poll(() => sampledColors(live, croppedPoints)).toEqual(['blue', 'blue', 'green']);
  await commit('Centro horizontal del recorte', '-100');
  await expect.poll(() => sampledColors(live, croppedPoints)).toEqual(['blue', 'blue', 'green']);

  await page.getByLabel('Nombre de plantilla').fill('Cámara fuera del gameplay');
  await button('Guardar como plantilla').click();
  await expect(page.getByText('Plantilla guardada.')).toBeVisible();
  await page.getByLabel('Distribución vertical').selectOption('50');
  await button('Restablecer encuadre').click();
  await expect(page.getByLabel('Distribución vertical')).toHaveValue('25');
  await expect(field('Zoom (%)')).toHaveValue('100');
  await expect(field('Centro horizontal del recorte')).toHaveValue('0');
  await button('Cámara').click();
  await expect(cameraX).toHaveValue('10');
  await button('Gameplay').click();
  await commit('Ancho (%)', '12.5'); await commit('Alto (%)', '22.22');
  await commit('X (%)', '10'); await commit('Y (%)', '11.11');
  await expect(page.getByText('La región de gameplay queda dentro de la cámara.', { exact: false })).toBeVisible();
  await expect(button('Vista exacta')).toBeDisabled();
  await expect(button('Exportar clip')).toBeDisabled();

  await button('Aplicar plantilla').click();
  await expect(field('Zoom (%)')).toHaveValue('125');
  await expect(field('Centro horizontal del recorte')).toHaveValue('-100');
  await expect(field('Centro vertical del recorte')).toHaveValue('25');
  await expect.poll(() => sampledColors(live, croppedPoints)).toEqual(['blue', 'blue', 'green']);
  await button('Vista exacta').click();
  await expect(video).toHaveAttribute('src', /\/api\/jobs\//);
  await expect.poll(() => sampledColors(video, croppedPoints)).toEqual(['blue', 'blue', 'green']);
  const exact = await request.get((await video.getAttribute('src'))!);
  expect(exact.ok()).toBe(true);
  const queued = page.waitForResponse(response => response.url().endsWith('/api/clips') && response.request().method() === 'POST');
  await button('Exportar clip').click();
  const response = await queued;
  expect(response.status()).toBe(202);
  const { id } = await response.json() as Job;
  await expect.poll(async () => (await (await request.get(`/api/jobs/${id}`)).json()).status).toBe('completed');
  const exported = await request.get(`/api/jobs/${id}/download`);
  expect(exported.ok()).toBe(true);
  expect((await exported.body()).equals(await exact.body())).toBe(true);
});
