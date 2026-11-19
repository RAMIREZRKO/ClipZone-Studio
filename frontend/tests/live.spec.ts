import { expect, test } from '@playwright/test';
import path from 'node:path';
import type { Video } from '../src/api';

const connected = {
  connected: true, buffer_active: true, buffer_seconds: 90, ready: true, busy: false, port: '4455',
  error: null, replay_dir: 'C:\\Clips\\Repeticiones OBS', replay_free_bytes: 2 * 1024 ** 3, library_free_bytes: 4 * 1024 ** 3,
};

test('ClipZone Live guarda por botón y atajo y abre el flujo de edición', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  const uploaded = page.waitForResponse(response => response.url().endsWith('/api/videos') && response.request().method() === 'POST');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  const video: Video = await (await uploaded).json();
  const posted: number[] = [];
  const history: { id: string; name: string; requested_seconds: number; duration: number; size: number; captured_at: string; video: Video }[] = [];
  let releaseFirst: () => void = () => {};
  const allowFirst = new Promise<void>(resolve => { releaseFirst = resolve; });
  await page.route('**/api/live/status', route => route.fulfill({ json: connected }));
  await page.route('**/api/live/captures', async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: history });
      return;
    }
    const duration = route.request().postDataJSON().seconds;
    posted.push(duration);
    if (posted.length === 1) await allowFirst;
    const capture = { id: `capture-${posted.length}`, name: `Repetición ${duration}.mp4`, requested_seconds: duration,
      duration: video.duration, size: video.size, captured_at: video.created_at, video };
    history.unshift(capture);
    await route.fulfill({ status: 201, json: capture });
  });

  const nav = page.getByRole('button', { name: 'ClipZone Live', exact: true });
  await nav.click();
  await page.getByRole('button', { name: 'OBS Studio', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'ClipZone Live', exact: true })).toBeVisible();
  await expect(page.getByText('OBS conectado', { exact: true })).toBeVisible();
  await expect(page.getByText('4.0 GB', { exact: true })).toBeVisible();
  await expect(page.getByText('Todavía no hay fragmentos guardados.')).toBeVisible();
  await page.getByRole('button', { name: '30 s', exact: true }).click();
  await page.getByRole('button', { name: 'Guardar fragmento' }).click();
  await expect(page.getByRole('button', { name: 'Guardando e importando…' })).toBeDisabled();
  await page.keyboard.press('Control+Alt+g');
  releaseFirst();
  await expect(page.getByRole('heading', { name: 'Repetición 30.mp4' })).toBeVisible();
  expect(posted).toEqual([30]);
  await page.getByRole('button', { name: '90 s', exact: true }).click();
  await page.keyboard.press('Control+Alt+g');
  const card = page.getByRole('listitem').filter({ has: page.getByRole('heading', { name: 'Repetición 90.mp4' }) });
  await expect(card).toBeVisible();
  expect(posted).toEqual([30, 90]);

  await page.reload();
  await nav.click();
  await expect(card).toBeVisible();
  await expect(page.getByRole('button', { name: '90 s', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await card.getByRole('button', { name: 'Analizar con Whisper' }).click();
  const analysis = page.getByRole('region', { name: 'Momentos con IA' });
  await expect(analysis).toBeInViewport();
  await expect(page.getByLabel('Nombre del clip')).toHaveValue(/clipzone-demo/);

  await nav.click();
  await card.getByRole('button', { name: 'Subtítulos', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Subtítulos dinámicos' })).toBeInViewport();

  await nav.click();
  await card.getByRole('button', { name: 'Ir a exportar' }).click();
  const exportButton = page.getByRole('button', { name: 'Exportar clip', exact: true });
  await expect(exportButton).toBeFocused();
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await exportButton.click();
  await expect(page.getByText('Listo para compartir').first()).toBeVisible({ timeout: 30_000 });
});

test('ClipZone Live indica desconexión y errores y conserva el ancho en móvil', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let status = { ...connected, connected: false, ready: false, buffer_active: false, error: 'No se pudo conectar con OBS en el puerto local 4455.' };
  let captureAttempts = 0;
  await page.route('**/api/live/status', route => route.fulfill({ json: status }));
  await page.route('**/api/live/captures', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [] });
    captureAttempts++;
    return route.fulfill({ status: 507, json: { detail: 'Falta espacio para importar la repetición.' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'ClipZone Live', exact: true }).click();
  await page.getByRole('button', { name: 'OBS Studio', exact: true }).click();
  await expect(page.getByText('OBS sin conexión', { exact: true })).toBeVisible();
  const save = page.getByRole('button', { name: 'Guardar fragmento' });
  await expect(save).toBeDisabled();
  await page.keyboard.press('Control+Alt+g');
  expect(captureAttempts).toBe(0);
  await page.getByText('Configurar OBS Studio', { exact: true }).click();
  await expect(page.getByText(connected.replay_dir, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  status = { ...connected, error: '' };
  await page.getByRole('button', { name: 'Comprobar conexión con OBS' }).click();
  await expect(save).toBeEnabled();
  await save.click();
  await expect(page.getByRole('alert').filter({ hasText: 'Falta espacio para importar la repetición.' })).toBeVisible();
  expect(captureAttempts).toBe(1);
});

test('captura directa consulta calidades, conserva el estado del servidor y guarda al detener', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  const uploaded = page.waitForResponse(response => response.url().endsWith('/api/videos') && response.request().method() === 'POST');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  const video: Video = await (await uploaded).json();
  const url = 'https://kick.com/canal_de_prueba';
  let state = { installed: true, state: 'idle', url: null as string | null, quality: null as string | null, platform: null as string | null,
    elapsed: 0, buffer_seconds: 0, bytes: 0, max_bytes: 512 * 1024 ** 2, free_bytes: 4 * 1024 ** 3,
    saving: false, retries: 0, max_retries: 3, message: null };
  let posted: number | undefined;
  let inHistory = false;
  const saved = { id: video.id, name: 'Kick · canal_de_prueba.mp4', method: 'direct', platform: 'kick', quality: '720p60',
    duration: video.duration, size: video.size, requested_seconds: 120, captured_at: video.created_at, video };
  await page.route('**/api/live/captures', route => route.fulfill({ json: inHistory ? [saved] : [] }));
  await page.route('**/api/live/direct/status', route => route.fulfill({ json: state }));
  await page.route('**/api/live/direct/probe', route => {
    expect(route.request().postDataJSON()).toEqual({ url });
    return route.fulfill({ json: { url, platform: 'kick', live: true, qualities: ['1080p60', '720p60', '360p'] } });
  });
  await page.route('**/api/live/direct/start', route => {
    expect(route.request().postDataJSON()).toEqual({ url, quality: '720p60' });
    state = { ...state, state: 'capturing', url, quality: '720p60', platform: 'kick', elapsed: 68, buffer_seconds: 60, bytes: 32 * 1024 ** 2 };
    return route.fulfill({ status: 202, json: state });
  });
  await page.route('**/api/live/direct/stop', route => {
    state = { ...state, state: 'stopped' };
    return route.fulfill({ json: state });
  });
  await page.route('**/api/live/direct/captures', route => {
    posted = route.request().postDataJSON().seconds;
    inHistory = true;
    return route.fulfill({ status: 201, json: saved });
  });
  const nav = page.getByRole('button', { name: 'ClipZone Live', exact: true });
  await nav.click();
  await expect(page.getByRole('button', { name: 'Captura directa' })).toHaveAttribute('aria-pressed', 'true');
  const input = page.getByLabel('URL del directo autorizado');
  await input.fill(url);
  await page.getByRole('button', { name: 'Comprobar directo' }).click();
  await expect(page.getByText('Kick · Canal en directo')).toBeVisible();
  await page.getByLabel('Calidad del directo').selectOption('720p60');
  await page.getByRole('button', { name: 'Iniciar captura' }).click();
  await expect(page.getByText('Capturando en segundo plano')).toBeVisible();
  await expect(input).toBeDisabled();
  await expect(page.getByText('32.0 MB / 512.0 MB')).toBeVisible();
  await page.reload();
  await nav.click();
  await expect(input).toHaveValue(url);
  await expect(page.getByLabel('Calidad del directo')).toHaveValue('720p60');
  await page.getByRole('button', { name: 'Detener captura' }).click();
  await expect(page.getByText('Captura detenida', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '300 s', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '120 s', exact: true }).click();
  await page.getByRole('button', { name: 'Guardar fragmento' }).click();
  expect(posted).toBe(120);
  await expect(page.getByRole('heading', { name: saved.name })).toBeVisible();
  await page.getByRole('button', { name: 'Subtítulos', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Subtítulos dinámicos' })).toBeInViewport();
});

test('captura directa informa canal desconectado y falta de dependencia', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let installed = true;
  await page.route('**/api/live/direct/status', route => route.fulfill({ json: {
    installed, state: 'idle', elapsed: 0, buffer_seconds: 0, bytes: 0, max_bytes: 512 * 1024 ** 2, free_bytes: 1024 ** 3,
  } }));
  await page.route('**/api/live/captures', route => route.fulfill({ json: [] }));
  const url = 'https://www.twitch.tv/canal_de_prueba';
  await page.route('**/api/live/direct/probe', route => route.fulfill({ json: { url, platform: 'twitch', live: false, qualities: [] } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'ClipZone Live', exact: true }).click();
  await page.getByLabel('URL del directo autorizado').fill(url);
  await page.getByRole('button', { name: 'Comprobar directo' }).click();
  await expect(page.getByText('Twitch · El canal no está en directo')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Iniciar captura' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Guardar fragmento' })).toBeDisabled();
  installed = false;
  await expect(page.getByText(/Instala Streamlink para habilitar/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
