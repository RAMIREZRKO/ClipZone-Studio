import { expect, test, type Locator } from '@playwright/test';
import path from 'node:path';

test('edita y arrastra texto, cambia el intervalo y reutiliza el estilo antes de exportar', async ({ page, request }) => {
  const rasterRequests: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/graphics/')) rasterRequests.push(request.url());
  });
  await page.goto('/');
  const source = process.env.CLIPZONE_TEXT_TEST_VIDEO || path.resolve('../demo/clipzone-demo.mp4');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(source);
  const video = page.locator('.video-frame video');
  await expect(video).toBeVisible();
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await page.getByText('Ajuste de precisión', { exact: true }).click();
  const clipEnd = page.getByLabel('Salida en segundos');
  await clipEnd.fill('3');
  await clipEnd.press('Enter');
  const panel = page.getByRole('region', { name: 'Gráficos y plantillas' });
  const button = (name: string) => panel.getByRole('button', { name, exact: true });
  const editor = panel.locator('.graphic-row').first();
  const commit = async (scope: Locator, label: string, value: string) => {
    const input = scope.getByLabel(label, { exact: true });
    await input.fill(value);
    await input.press('Enter');
  };
  await button('Agregar texto').click();
  await editor.getByLabel('Texto promocional', { exact: true }).fill('Colores de edición\nClipZone');
  await expect(editor.locator(':scope > summary')).toHaveText('Colores de edición ClipZone');
  await editor.getByLabel('Aplicar estilo de texto').selectOption('white-box');
  await expect(editor.getByLabel('Color del texto')).toHaveValue('#000000');
  await expect(editor.getByLabel('Color de fondo')).toHaveValue('#ffffff');
  await editor.getByLabel('Fuente', { exact: true }).selectOption('Montserrat');
  await editor.getByLabel('Alineación', { exact: true }).selectOption('right');
  await editor.getByLabel('Color de fondo').fill('#ecff9c');
  await editor.getByRole('button', { name: 'Cursiva', exact: true }).click();
  await editor.getByRole('button', { name: 'Subrayado', exact: true }).click();
  await commit(editor, 'Opacidad del texto (%)', '72');
  await commit(editor, 'Opacidad del fondo (%)', '85');
  await commit(editor, 'Redondeo (px)', '28');
  await editor.getByText('Contorno y sombra', { exact: true }).click();
  await commit(editor, 'Grosor del contorno (px)', '4');
  await commit(editor, 'Opacidad de sombra (%)', '55');
  await editor.getByText('Opciones avanzadas de la capa', { exact: true }).click();
  await editor.getByLabel('Nombre de capa').fill('Texto principal');
  await editor.getByLabel('Nombre de capa').press('Enter');
  const graphic = page.getByRole('button', { name: 'Mover Texto principal', exact: true });
  await expect(graphic.locator('.text-raster')).toBeVisible();
  await graphic.scrollIntoViewIfNeeded();
  const bounds = (await graphic.boundingBox())!;
  const frame = (await page.locator('.video-frame').boundingBox())!;
  expect(bounds.width).toBeLessThan(frame.width * .8);
  const requestsBeforeDrag = rasterRequests.length;
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 20, bounds.y + bounds.height / 2 + 18, { steps: 6 });
  await page.mouse.up();
  expect(Number(await editor.getByLabel('Horizontal (%)').inputValue())).toBeGreaterThan(50);
  expect(rasterRequests).toHaveLength(requestsBeforeDrag);

  const timing = editor.getByRole('group', { name: 'Duración', exact: true });
  const from = timing.getByRole('slider', { name: 'Inicio del texto', exact: true });
  const to = timing.getByRole('slider', { name: 'Fin del texto', exact: true });
  const rail = timing.locator('.text-time-slider');
  await rail.scrollIntoViewIfNeeded();
  const track = (await rail.boundingBox())!;
  const y = track.y + track.height / 2;
  await page.mouse.move(track.x + 9, y);
  await page.mouse.down();
  await page.mouse.move(track.x + track.width * .2, y, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => Number(await from.inputValue())).toBeGreaterThan(25);
  await page.mouse.move(track.x + track.width - 9, y);
  await page.mouse.down();
  await page.mouse.move(track.x + track.width * .66, y, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => Number(await to.inputValue())).toBeLessThan(240);
  await expect(graphic).toHaveCount(0);
  await timing.getByLabel('Mostrar durante todo el clip').check();
  await expect(from).toHaveValue('0');
  await expect(to).toHaveValue('300');
  await expect(graphic.locator('img')).toBeVisible();
  await clipEnd.fill('2');
  await clipEnd.press('Enter');
  await expect(to).toHaveValue('200');

  await editor.getByLabel('Nombre del estilo').fill('Claro con relieve');
  await editor.getByRole('button', { name: 'Guardar estilo de texto', exact: true }).click();
  await expect(panel.getByText('Estilo de texto guardado.')).toBeVisible();
  await editor.getByRole('button', { name: 'Duplicar capa', exact: true }).click();
  const copy = panel.locator('.graphic-row').filter({ has: page.locator('summary').filter({ hasText: /^Texto principal · copia/ }) });
  await copy.getByRole('button', { name: 'Ocultar capa', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Mover Texto principal · copia', exact: true })).toHaveCount(0);
  await expect(copy.getByRole('button', { name: 'Mostrar capa', exact: true })).toBeVisible();
  await copy.getByRole('button', { name: 'Eliminar capa', exact: true }).click();
  const readyForHook = await request.get('/api/templates');
  const style = (await readyForHook.json()).find((item: { name: string }) => item.name === 'Claro con relieve');
  await button('Crear texto gancho').click();
  const hook = panel.locator('.graphic-row').last();
  await hook.getByLabel('Aplicar estilo de gancho').selectOption('tiktok');
  await expect(hook.getByLabel('Fuente', { exact: true })).toHaveValue('Anton');
  await hook.getByLabel('Aplicar estilo de gancho').selectOption(style.id);
  await expect(hook.getByLabel('Fuente', { exact: true })).toHaveValue('Montserrat');
  await expect(hook.getByLabel('Opacidad del fondo (%)')).toHaveValue('85');
  await hook.getByRole('button', { name: 'Ocultar capa', exact: true }).click();

  expect(rasterRequests.some(url => url.endsWith('/graphics/text'))).toBe(true);
  expect(rasterRequests.some(url => url.endsWith('/graphics/hook'))).toBe(false);
  await page.getByRole('button', { name: 'Vista exacta', exact: true }).click();
  await expect(video).toHaveAttribute('src', /\/api\/jobs\//);
  const exact = await request.get((await video.getAttribute('src'))!);
  const response = page.waitForResponse(response => response.url().endsWith('/api/clips') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Exportar clip', exact: true }).click();
  const job = await (await response).json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe('completed');
  const exported = await request.get(`/api/jobs/${job.id}/download`);
  expect((await exported.body()).equals(await exact.body())).toBe(true);
});

test('inserta emojis a color en el cursor, pega secuencias y exporta ambas capas', async ({ page, context, request }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/');
  const source = process.env.CLIPZONE_TEXT_TEST_VIDEO || path.resolve('../demo/clipzone-demo.mp4');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(source);
  const video = page.locator('.video-frame video');
  await expect(video).toBeVisible();
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await page.getByText('Ajuste de precisión', { exact: true }).click();
  await page.getByLabel('Salida en segundos').fill('2');
  await page.getByLabel('Salida en segundos').press('Enter');
  const panel = page.getByRole('region', { name: 'Gráficos y plantillas' });
  await panel.getByRole('button', { name: 'Agregar texto', exact: true }).click();
  const normal = panel.locator('.graphic-row').first();
  const text = normal.getByLabel('Texto promocional', { exact: true });
  await text.fill('Hola mundo');
  await text.press('Home');
  for (let i = 0; i < 5; i++) await text.press('ArrowRight');
  await normal.getByRole('button', { name: 'Insertar emoji' }).click();
  await normal.getByLabel('Buscar emoji').fill('llama');
  const fire = normal.getByRole('button', { name: 'Fuego', exact: true });
  await expect.poll(() => fire.locator('img').evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await fire.click();
  await expect(text).toHaveValue('Hola 🔥mundo');
  await expect(text).toBeFocused();
  await page.keyboard.type(' ');
  await expect(text).toHaveValue('Hola 🔥 mundo');
  await page.evaluate(() => navigator.clipboard.writeText(' 🧑🏽‍💻 1️⃣'));
  await text.press('End');
  await text.press('Control+v');
  await expect(text).toHaveValue('Hola 🔥 mundo 🧑🏽‍💻 1️⃣');

  await panel.getByRole('button', { name: 'Crear texto gancho' }).click();
  const hook = panel.locator('.graphic-row').last();
  const hookText = hook.getByLabel('Texto gancho', { exact: true });
  await hookText.fill('Equipo ');
  await hookText.press('End');
  await hook.getByRole('button', { name: 'Insertar emoji' }).click();
  await hook.getByRole('button', { name: 'Banderas' }).click();
  await hook.getByRole('button', { name: 'Colombia', exact: true }).click();
  await expect(hookText).toHaveValue('Equipo 🇨🇴');
  await expect(page.locator('.graphic-overlay img.text-raster')).toHaveCount(2);
  await page.getByRole('button', { name: 'Vista exacta', exact: true }).click();
  await expect(video).toHaveAttribute('src', /\/api\/jobs\//);
  const exact = await request.get((await video.getAttribute('src'))!);
  const posted = page.waitForResponse(response => response.url().endsWith('/api/clips') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Exportar clip', exact: true }).click();
  const job = await (await posted).json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe('completed');
  const exported = await request.get(`/api/jobs/${job.id}/download`);
  expect((await exported.body()).equals(await exact.body())).toBe(true);
});

test('el selector carga los 64 SVG locales y busca por nombre, acento o emoji', async ({ page }, testInfo) => {
  const failedImages: string[] = [];
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (route.request().resourceType() === 'image' && url.origin !== new URL(page.url()).origin) {
      failedImages.push(url.href);
      return route.abort();
    }
    if (url.pathname.startsWith('/api/graphics/emojis/')) return route.abort();
    return route.continue();
  });
  await page.goto('/');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  await page.getByRole('button', { name: 'Agregar texto', exact: true }).click();
  await page.getByRole('button', { name: 'Insertar emoji', exact: true }).click();
  const picker = page.getByRole('group', { name: 'Selector de emojis' });
  const icons = picker.locator('.emoji-grid img');
  const expected = [
    ['Caras', 9], ['Gestos', 9], ['Gaming y vídeo', 9], ['Símbolos', 12],
    ['Objetos', 9], ['Animales y naturaleza', 8], ['Banderas', 8],
  ] as const;
  for (const [category, count] of expected) {
    await picker.getByRole('button', { name: category, exact: true }).click();
    await expect(icons).toHaveCount(count);
    await expect.poll(() => icons.evaluateAll(elements => elements.every(node => {
      const image = node as HTMLImageElement;
      return image.complete && image.naturalWidth > 0 && new URL(image.src).origin === location.origin &&
        new URL(image.src).pathname.startsWith('/twemoji/17.0.3/') && image.src.endsWith('.svg');
    }))).toBe(true);
    if (category === 'Símbolos' || category === 'Banderas') {
      await picker.screenshot({ path: testInfo.outputPath(category === 'Símbolos' ? 'simbolos.png' : 'banderas.png') });
    }
  }
  const search = picker.getByRole('searchbox', { name: 'Buscar emoji' });
  await search.fill('microfono');
  await expect(picker.getByRole('button', { name: 'Micrófono' })).toBeVisible();
  await expect(icons).toHaveCount(1);
  await expect.poll(() => icons.first().evaluate(node => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await picker.screenshot({ path: testInfo.outputPath('busqueda.png') });
  await search.fill('🇨🇴');
  await expect(picker.getByRole('button', { name: 'Colombia' })).toBeVisible();
  await search.fill('zz-sin-coincidencia');
  await expect(picker.getByText('Sin resultados')).toBeVisible();
  expect(failedImages).toEqual([]);
});

test('el selector muestra e inserta Unicode cuando falla un SVG', async ({ page }, testInfo) => {
  await page.route('**/twemoji/17.0.3/1f525.svg', route => route.abort());
  await page.goto('/');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  await page.getByRole('button', { name: 'Agregar texto', exact: true }).click();
  await page.getByRole('button', { name: 'Insertar emoji', exact: true }).click();
  const picker = page.getByRole('group', { name: 'Selector de emojis' });
  await picker.getByRole('searchbox', { name: 'Buscar emoji' }).fill('fuego');
  const fire = picker.getByRole('button', { name: 'Fuego', exact: true });
  await expect(fire.locator('.emoji-unicode')).toHaveText('🔥');
  await expect(fire.locator('img')).toHaveCount(0);
  await picker.screenshot({ path: testInfo.outputPath('unicode.png') });
  await fire.click();
  await expect(page.getByLabel('Texto promocional')).toHaveValue(/🔥/);
});
