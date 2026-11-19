import { test, expect, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

async function scanCaption(page: Page, src: string) {
  return page.evaluate(async src => {
    const image = new Image();
    image.src = src;
    await image.decode();
    const { naturalWidth: width, naturalHeight: height } = image;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d')!;
    context.drawImage(image, 0, 0);
    const { data } = context.getImageData(0, 0, width, height);
    const bounds = () => ({ left: width, top: height, right: -1, bottom: -1, count: 0 });
    const result = { fill: bounds(), outline: bounds(), shadow: bounds(), active: bounds() };
    for (let i = 0; i < data.length; i += 4) {
      const [r, g, b, a] = [data[i], data[i + 1], data[i + 2], data[i + 3]];
      if (a < 175) continue;
      let mask: ReturnType<typeof bounds>;
      if (r - g > 80 && b - g > 60) mask = result.fill;
      else if (g - r > 75 && g - b > 70) mask = result.outline;
      else if (r > 215 && g > 190 && b < 162) mask = result.active;
      else if (Math.max(r, g, b) < 104) mask = result.shadow;
      else continue;
      const x = i / 4 % width;
      const y = Math.floor(i / 4 / width);
      mask.left = Math.min(mask.left, x);
      mask.top = Math.min(mask.top, y);
      mask.right = Math.max(mask.right, x);
      mask.bottom = Math.max(mask.bottom, y);
      mask.count++;
    }
    return { ...result, width, height };
  }, src);
}

test('edita, divide, combina y guarda subtítulos con vista en directo', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await expect(page.getByLabel('Idioma del audio', { exact: true })).toHaveValue('auto');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  await expect(page.locator('.video-frame video')).toBeVisible();
  await page.getByRole('button', { name: 'Subtítulos dinámicos', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Subtítulos dinámicos' });
  await panel.getByRole('button', { name: 'Añadir segmento' }).click();
  await panel.getByLabel('Texto del segmento 1').fill('Hola mundo');
  await panel.getByRole('button', { name: 'Dividir', exact: true }).click();
  await expect(panel.getByLabel('Texto del segmento 2')).toHaveValue('mundo');
  await panel.getByRole('button', { name: 'Combinar con siguiente', exact: true }).first().click();
  await panel.getByLabel('Buscar texto', { exact: true }).fill('mundo');
  await panel.getByLabel('Reemplazar por', { exact: true }).fill('Bogotá');
  await panel.getByRole('button', { name: 'Reemplazar todo' }).click();
  await panel.getByRole('checkbox', { name: 'Activar subtítulos' }).check();
  await expect(page.locator('.live-caption')).toHaveText('Hola Bogotá');
  await panel.getByRole('button', { name: 'Guardar subtítulos' }).click();
  await expect(panel.getByText('Cambios guardados.')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: /Mis vídeos/ }).click();
  await page.locator('.video-card-open').first().click();
  await expect(panel.getByLabel('Texto del segmento 1')).toHaveValue('Hola Bogotá');
});

test('resalta una palabra y ofrece SRT y VTT en una exportación real', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  await expect(page.locator('.video-frame video')).toBeVisible();
  const panel = page.getByRole('region', { name: 'Subtítulos dinámicos' });
  await panel.getByRole('button', { name: 'Añadir segmento' }).click();
  await panel.getByLabel('Texto del segmento 1').fill('Hola Bogotá');
  await panel.getByRole('checkbox', { name: 'Activar subtítulos' }).check();
  await panel.getByRole('checkbox', { name: 'Archivos SRT y VTT' }).check();
  await panel.getByText('Estilo y posición de subtítulos', { exact: true }).click();
  await panel.getByLabel('Estilo', { exact: true }).selectOption('karaoke');
  const captionImage = page.locator('.live-caption img');
  const highlighted = async () => (await scanCaption(page, (await captionImage.getAttribute('src'))!)).active;
  await expect.poll(async () => (await highlighted()).count).toBeGreaterThan(10);
  const firstWord = await highlighted();
  const cursor = page.getByRole('slider', { name: 'Posición de reproducción' });
  await cursor.press('Shift+ArrowRight');
  await expect.poll(async () => (await highlighted()).left).toBeGreaterThan(firstWord.right);
  await panel.getByRole('button', { name: 'Guardar subtítulos' }).click();
  await expect(panel.getByText('Cambios guardados.')).toBeVisible();
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await page.getByText('Ajuste de precisión', { exact: true }).click();
  await page.getByLabel('Entrada en segundos').fill('0.2');
  await page.getByLabel('Salida en segundos').fill('1.8');
  await page.getByLabel('Nombre del clip', { exact: true }).fill('Prueba subtítulos');
  await page.getByRole('button', { name: 'Vista exacta', exact: true }).click();
  await expect.poll(() => page.locator('.video-frame video').evaluate((video: HTMLVideoElement) => video.videoHeight)).toBe(854);
  const previous = await page.locator('.video-frame video').getAttribute('src');
  await panel.getByLabel('Posición vertical (%)').fill('45');
  await expect(page.locator('.video-frame video')).toHaveCount(0);
  await panel.getByLabel('Texto del segmento 1').fill('Hola Bogotá editado');
  await expect(page.getByText('Guarda los subtítulos para actualizar Vista exacta.')).toBeVisible();
  await panel.getByLabel('Texto del segmento 1').fill('Hola Bogotá');
  await panel.getByRole('button', { name: 'Guardar subtítulos' }).click();
  await expect(panel.getByText('Cambios guardados.')).toBeVisible();
  await page.getByRole('button', { name: 'Generar vista exacta', exact: true }).click();
  await expect(page.locator('.video-frame video')).toHaveAttribute('src', /\/api\/jobs\//);
  await expect(page.locator('.video-frame video')).not.toHaveAttribute('src', previous!);
  await page.getByRole('button', { name: 'Exportar clip', exact: true }).click();
  const clip = page.locator('.export-card').filter({ hasText: 'Prueba subtítulos' });
  await expect(clip.getByText('Listo para compartir')).toBeVisible();
  const href = await clip.getByRole('link', { name: 'SRT', exact: true }).getAttribute('href');
  expect(await (await page.request.get(href!)).text()).toContain('Hola Bogotá');
  await expect(clip.getByRole('link', { name: 'VTT', exact: true })).toBeVisible();
});

test('importa y corrige una traducción sin cambiar el texto ni el intervalo original', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  const panel = page.getByRole('region', { name: 'Subtítulos dinámicos' });
  await panel.getByRole('button', { name: 'Añadir segmento' }).click();
  await panel.getByLabel('Texto del segmento 1').fill('¡Hola, Bogotá!');
  await panel.getByRole('checkbox', { name: 'Activar subtítulos' }).check();
  await panel.getByRole('button', { name: 'Guardar subtítulos' }).click();
  await expect(panel.getByText('Cambios guardados.')).toBeVisible();
  await panel.getByLabel('Idioma de los subtítulos').selectOption('en');
  await panel.getByLabel('Importar traducción SRT/VTT').setInputFiles({
    name: 'captions.srt', mimeType: 'application/x-subrip',
    buffer: Buffer.from('1\n00:00:23,000 --> 00:00:24,000\nHello Bogotá!\n', 'utf8'),
  });
  await expect(panel.getByLabel('Traducción del segmento 1')).toHaveValue('Hello Bogotá!');
  await expect(panel.getByLabel('Texto del segmento 1')).toHaveValue('¡Hola, Bogotá!');
  await expect(panel.getByLabel('Inicio', { exact: true })).toHaveValue('0');
  await expect(panel.getByLabel('Final', { exact: true })).toHaveValue('1.5');
  await panel.getByLabel('Traducción del segmento 1').fill('Welcome to Bogotá!');
  await expect(page.locator('.live-caption')).toHaveText('Welcome to Bogotá!');
  await panel.getByRole('button', { name: 'Guardar subtítulos' }).click();
  await expect(panel.getByText('Cambios guardados.')).toBeVisible();
  await panel.getByLabel('Idioma de los subtítulos').selectOption('original');
  await expect(page.locator('.live-caption')).toHaveText('¡Hola, Bogotá!');
});

const formats = [
  { ratio: '9:16', width: 480, height: 854, align: 'left' },
  { ratio: '1:1', width: 480, height: 480, align: 'center' },
  { ratio: '4:5', width: 480, height: 600, align: 'right' },
  { ratio: '16:9', width: 854, height: 480, align: 'center' },
];

function neutralVideo() {
  const bundled = path.resolve('../tools/ffmpeg/bin/ffmpeg.exe');
  const ffmpeg = process.env.CLIPZONE_FFMPEG || (existsSync(bundled) ? bundled : 'ffmpeg');
  return execFileSync(ffmpeg, ['-v', 'error', '-f', 'lavfi', '-i', 'color=0x999999:s=640x360:r=24:d=1',
    '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-movflags', 'empty_moov+frag_keyframe', '-f', 'mp4', 'pipe:1']);
}

for (const format of formats) {
  test(`correspondencia visual de subtítulos en ${format.ratio} y los tres encuadres`, async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Motor local listo')).toBeVisible();
    await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles({
      name: 'Lienzo neutro.mp4', mimeType: 'video/mp4', buffer: neutralVideo(),
    });
    const canvas = page.locator('.video-frame');
    const video = canvas.locator('video');
    await expect(video).toBeVisible();
    await page.getByRole('button', { name: format.ratio, exact: true }).click();
    await page.getByLabel('Resolución', { exact: true }).selectOption('480');
    await page.getByLabel('Margen superior').fill('8');
    await page.getByLabel('Margen inferior').fill('12');
    await page.getByRole('switch', { name: 'Guías de zona segura' }).click();
    const panel = page.getByRole('region', { name: 'Subtítulos dinámicos' });
    await panel.getByRole('button', { name: 'Añadir segmento' }).click();
    await panel.getByLabel('Texto del segmento 1').fill('Línea Uno Línea Dos');
    await panel.getByRole('button', { name: 'Guardar subtítulos' }).click();
    await expect(panel.getByText('Cambios guardados.')).toBeVisible();
    await panel.getByText('Estilo y posición de subtítulos', { exact: true }).click();
    await panel.getByLabel('Alineación').selectOption(format.align);
    await panel.getByLabel('Tamaño a 1080 px').fill('84');
    await panel.getByLabel('Posición vertical (%)').fill('100');
    await panel.getByLabel('Palabras por línea').fill('2');
    await panel.getByLabel('Contorno', { exact: true }).fill('8');
    await panel.getByLabel('Sombra', { exact: true }).fill('8');
    await panel.getByLabel('Color del texto').fill('#f020e0');
    await panel.getByLabel('Color del contorno').fill('#12cc35');
    await panel.getByRole('checkbox', { name: 'Activar subtítulos' }).check();

    const capture = async () => scanCaption(page, 'data:image/png;base64,' + (await canvas.screenshot()).toString('base64'));
    for (const fit of ['Ajustar completo', 'Llenar y recortar', 'Fondo difuminado']) {
      await test.step(fit, async () => {
        await page.getByRole('button', { name: 'Encuadre en directo' }).click();
        await page.getByRole('button', { name: fit, exact: true }).click();
        await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2);
        await canvas.locator('.live-caption img').evaluate((element: HTMLImageElement) => element.decode());
        const live = await capture();
        await page.getByRole('button', { name: 'Vista exacta', exact: true }).click();
        await expect.poll(() => video.evaluate((element: HTMLVideoElement) =>
          [element.videoWidth, element.videoHeight, element.readyState >= 2])).toEqual([format.width, format.height, true]);
        const exact = await capture();
        expect([live.width, live.height]).toEqual([exact.width, exact.height]);
        for (const mask of fit === 'Llenar y recortar' ? ['fill', 'outline', 'shadow'] as const : ['fill', 'outline'] as const) {
          expect(live[mask].count, `píxeles visibles de ${mask}`).toBeGreaterThan(12);
          expect(exact[mask].count / live[mask].count, `tamaño de ${mask}`).toBeGreaterThan(.55);
          expect(exact[mask].count / live[mask].count, `tamaño de ${mask}`).toBeLessThan(1.55);
          for (const edge of ['left', 'top', 'right', 'bottom'] as const) {
            expect(Math.abs(exact[mask][edge] - live[mask][edge]), `${mask} ${edge}`).toBeLessThanOrEqual(3);
          }
        }
        expect(live.outline.top / live.height).toBeGreaterThan(.08);
        expect(live.outline.bottom / live.height).toBeLessThan(.88);
        if (format.ratio === '9:16' && fit !== 'Llenar y recortar') {
          const videoContentBottom = (1 + format.width / format.height / (16 / 9)) / 2;
          expect(live.outline.top / live.height).toBeGreaterThan(videoContentBottom);
          expect(exact.outline.top / exact.height).toBeGreaterThan(videoContentBottom);
        }
      });
    }
  });
}
