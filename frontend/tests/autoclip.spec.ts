import { expect, test } from '@playwright/test';
import path from 'node:path';
import type { Video } from '../src/api';

test('AutoClipping configura Whisper, reproduce candidatos y registra decisiones', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  const uploaded = page.waitForResponse(response => response.url().endsWith('/api/videos') && response.request().method() === 'POST');
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  const video: Video = await (await uploaded).json();
  const storedTemplate = await page.request.post('/api/templates', { data: {
    name: 'AutoClipping · cámara', options: { fit: 'split', split_layout: { camera_share: 40, inverted: true } },
  } });
  expect(storedTemplate.ok()).toBe(true);
  const template = await storedTemplate.json();
  let options = { enabled: false, model: 'tiny', duration: 30, sensitivity: 'balanced',
    detection_mode: 'mixed', minimum_score: 58, before: 12, after: 8, per_hour: 6, interval: 40 };
  let received: Partial<typeof options> | undefined;
  const status = () => ({ options, stage: options.enabled ? 'listening' : 'disabled', message: null,
    detection_modes: ['gameplay', 'irl', 'mixed'],
    detected: 2, filtered: 0, skipped: 0, bytes: 1000, max_bytes: 512 * 1024 ** 2, vad: true, whisper: true,
    available_bytes: 512 * 1024 ** 2 - 1000,
    diagnostics: { audio_segments: 15, audio_failures: 0, transcriptions: 2, generated: 1, deferred: 1,
      last_score: 76, best_score: 76, last_error: null, omissions: { whisper_queue_timeout: 1 }, filters: { low_confidence: 1 } },
    models: ['tiny', 'base', 'small'].map(id => ({ id, installed: true })) });
  const fixture = { duration: video.duration, score: 76, created_at: video.created_at, platform: 'kick', channel: 'prueba',
    status: 'pending', reason: 'la voz coincide con el evento', excerpt: 'La frase que explica el resultado.',
    detection_mode: 'gameplay', detection_type: 'gameplay', metrics: { voice: 79, confidence: 84, intensity: 60 },
    thumbnail_url: video.thumbnail_url, preview_url: video.preview_url, video: null as Video | null };
  const candidates = [{ ...fixture, id: 'saved-fixture', title: 'Momento para conservar' },
    { ...fixture, id: 'dropped-fixture', title: 'Momento para descartar' }];
  const registered = await page.request.post('/api/live/streamers', { data: { url: 'https://kick.com/prueba' } });
  expect(registered.ok()).toBe(true);
  await page.route('**/api/live/auto/status?streamer=*', route => route.fulfill({ json: status() }));
  await page.route('**/api/live/auto/config?streamer=*', route => {
    received = route.request().postDataJSON();
    options = { ...options, ...received };
    return route.fulfill({ json: status() });
  });
  await page.route('**/api/live/auto/candidates', route => route.fulfill({ json: candidates }));
  await page.route('**/api/live/auto/candidates/*/*', route => {
    const parts = new URL(route.request().url()).pathname.split('/');
    const item = candidates.find(row => row.id === parts.at(-2))!;
    const kept = parts.at(-1) === 'keep';
    Object.assign(item, { status: kept ? 'kept' : 'discarded', video: kept ? video : null,
      thumbnail_url: null, preview_url: null });
    return route.fulfill({ json: item });
  });
  await page.getByRole('button', { name: 'ClipZone Live', exact: true }).click();
  const panel = page.getByRole('region', { name: 'AutoClipping IA · prueba' });
  const bound = page.waitForResponse(r => new URL(r.url()).pathname === '/api/live/streamers' && r.request().method() === 'POST');
  await panel.getByLabel('Plantilla para editar candidatos').selectOption(template.id);
  expect((await bound).ok()).toBe(true);
  await expect(panel.getByText('Modo automático desactivado')).toBeVisible();
  await expect(panel.getByText('Modelo para AutoClipping · Whisper Tiny')).toBeVisible();
  await panel.getByText('Diagnóstico del canal', { exact: true }).click();
  await expect(panel.getByText(/15 segmentos con audio/)).toBeVisible();
  await expect(panel.getByText('Espera agotada en la cola de Whisper · 1')).toBeVisible();
  await expect(panel.getByText('Confianza baja de Whisper · 1')).toBeVisible();
  const mode = panel.getByLabel('Modo de detección');
  await expect(mode).toHaveValue('mixed');
  await expect(mode.locator('option')).toHaveText(['Gameplay', 'IRL / Just Chatting', 'Mixto']);
  await mode.selectOption('irl');
  await panel.getByRole('button', { name: 'Guardar ajustes automáticos' }).click();
  await expect.poll(() => received?.detection_mode).toBe('irl');
  await mode.selectOption('gameplay');
  await panel.getByLabel('Duración automática').selectOption('60');
  await panel.getByLabel('Sensibilidad').selectOption('high');
  const after = panel.getByLabel('Segundos posteriores');
  await after.press('Control+a');
  await after.press('Backspace');
  await expect(after).toHaveValue('');
  await after.pressSequentially('10');
  await after.press('Enter');
  const score = panel.getByLabel('Puntuación mínima');
  await score.press('Control+a');
  await score.press('Backspace');
  await expect(score).toHaveValue('');
  await score.pressSequentially('65');
  await panel.getByRole('button', { name: 'Activar modo automático' }).click();
  await expect(panel.getByText('Analizando señales del audio')).toBeVisible();
  expect(received).toMatchObject({ enabled: true, model: 'tiny', duration: 60, sensitivity: 'high', detection_mode: 'gameplay', after: 10, minimum_score: 65 });
  const wanted = panel.getByRole('listitem').filter({ hasText: 'Momento para conservar' });
  await expect(wanted.getByText('76/100')).toBeVisible();
  await wanted.getByText('Señales de la puntuación', { exact: true }).click();
  await expect(wanted.getByText('Confianza de Whisper · 84%')).toBeVisible();
  await wanted.getByRole('button', { name: 'Reproducir' }).click();
  await expect(wanted.locator('video')).toBeVisible();
  await wanted.getByRole('button', { name: 'Conservar' }).click();
  await expect(wanted.getByText(/Conservado/)).toBeVisible();
  const other = panel.getByRole('listitem').filter({ hasText: 'Momento para descartar' });
  await other.getByRole('button', { name: 'Descartar' }).click();
  await expect(other.getByText(/Descartado/)).toBeVisible();
  await expect(other.getByRole('button', { name: 'Reproducir' })).toHaveCount(0);
  await panel.getByRole('button', { name: 'Desactivar modo automático' }).click();
  await expect(panel.getByText('Modo automático desactivado')).toBeVisible();
  await wanted.getByRole('button', { name: 'Editar' }).click();
  await expect(page.getByLabel('Nombre del clip')).toHaveValue(/clipzone-demo/);
  await expect(page.getByRole('button', { name: 'Streamer + Gameplay' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByLabel('Distribución vertical')).toHaveValue('40');
  await expect(page.getByRole('checkbox', { name: 'Invertir cámara y gameplay' })).toBeChecked();
});

test('AutoClipping guarda el umbral y desactiva un canal desconectado con el servidor anterior', async ({ page }) => {
  const registered = await page.request.post('/api/live/streamers', { data: { url: 'https://kick.com/retro' } });
  expect(registered.ok()).toBe(true);
  let options = { enabled: true, model: 'tiny', duration: 30, sensitivity: 'balanced',
    detection_mode: 'reaction', minimum_score: 65, before: 12, after: 8, per_hour: 6, interval: 40 };
  const status = () => ({ options, stage: options.enabled ? 'waiting' : 'disabled', message: null,
    detected: 0, filtered: 0, skipped: 0, bytes: 1000, max_bytes: 512 * 1024 ** 2,
    vad: false, whisper: false, models: [] });
  await page.route('**/api/live/auto/status?streamer=kick%3Aretro', route => route.fulfill({ json: status() }));
  await page.route('**/api/live/auto/config?streamer=kick%3Aretro', route => {
    const body = route.request().postDataJSON();
    expect(body.detection_mode).toBe('reaction');
    options = body;
    return route.fulfill({ json: status() });
  });
  await page.route('**/api/live/auto/candidates', route => route.fulfill({ status: 500, json: { detail: 'Historial temporalmente indisponible.' } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'ClipZone Live', exact: true }).click();
  await page.getByRole('article', { name: 'Kick · retro' }).getByRole('button', { name: 'AutoClipping y atajo' }).click();
  const panel = page.getByRole('region', { name: 'AutoClipping IA · retro' });
  await expect(panel.getByLabel('Modo de detección')).toHaveValue('irl');
  await expect(panel.getByText('Esperando captura directa')).toBeVisible();
  const score = panel.getByLabel('Puntuación mínima');
  await score.fill('78');
  await panel.getByRole('button', { name: 'Guardar ajustes automáticos' }).click();
  await expect.poll(() => options.minimum_score).toBe(78);
  await panel.getByRole('button', { name: 'Desactivar modo automático' }).click();
  await expect(panel.getByText('Modo automático desactivado')).toBeVisible();
  expect(options).toMatchObject({ enabled: false, detection_mode: 'reaction', minimum_score: 78 });
});

test('la cuota de candidatos persiste y se puede configurar sin una captura', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'ClipZone Live', exact: true }).click();
  const limit = page.getByLabel('Límite de almacenamiento de candidatos');
  await expect(limit.locator('option')).toHaveText(['1 GB', '5 GB', '10 GB', '20 GB']);
  await expect(limit).toHaveValue('5');
  await limit.selectOption('10');
  await expect(limit).toHaveValue('10');
  await page.reload();
  await page.getByRole('button', { name: 'ClipZone Live', exact: true }).click();
  await expect(limit).toHaveValue('10');
});
