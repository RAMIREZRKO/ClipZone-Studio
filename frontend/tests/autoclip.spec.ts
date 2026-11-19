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
    minimum_score: 58, before: 12, after: 8, per_hour: 6, interval: 40 };
  let received: typeof options | undefined;
  const status = () => ({ options, stage: options.enabled ? 'listening' : 'disabled', message: null,
    detected: 2, filtered: 0, skipped: 0, bytes: 1000, max_bytes: 512 * 1024 ** 2, vad: true, whisper: true,
    models: ['tiny', 'base', 'small'].map(id => ({ id, installed: true })) });
  const fixture = { duration: video.duration, score: 76, created_at: video.created_at, platform: 'kick', channel: 'prueba',
    status: 'pending', reason: 'cambio brusco de intensidad y habla continua', excerpt: 'La frase que explica el resultado.',
    thumbnail_url: video.thumbnail_url, preview_url: video.preview_url, video: null as Video | null };
  const candidates = [{ ...fixture, id: 'saved-fixture', title: 'Momento para conservar' },
    { ...fixture, id: 'dropped-fixture', title: 'Momento para descartar' }];
  await page.route('**/api/live/auto/status', route => route.fulfill({ json: status() }));
  await page.route('**/api/live/auto/config', route => {
    received = route.request().postDataJSON();
    options = received!;
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
  const panel = page.getByRole('region', { name: 'AutoClipping IA' });
  await panel.getByLabel('Plantilla para editar candidatos').selectOption(template.id);
  await expect(panel.getByText('Modo automático desactivado')).toBeVisible();
  await panel.getByLabel('Modelo para AutoClipping').selectOption('base');
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
  expect(received).toMatchObject({ enabled: true, model: 'base', duration: 60, sensitivity: 'high', after: 10, minimum_score: 65 });
  const wanted = panel.getByRole('listitem').filter({ hasText: 'Momento para conservar' });
  await expect(wanted.getByText('76/100')).toBeVisible();
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
