import { test, expect } from '@playwright/test';
import path from 'node:path';

test('encuadre difuminado, vista original y render exacto con línea de tiempo ampliada', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  for (const width of [1280, 1366, 1920, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    expect(await page.locator('.settings-body').evaluate(e => e.scrollWidth <= e.clientWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 1366, height: 900 });
  const contrast = await page.locator('.field-heading > label').first().evaluate(label => {
    const luminance = (color: string) => {
      const values = (color.match(/\d+/g) ?? []).slice(0, 3).map(Number).map(component => {
        const c = component / 255;
        return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4;
      });
      return .2126 * values[0] + .7152 * values[1] + .0722 * values[2];
    };
    const foreground = luminance(getComputedStyle(label).color);
    const background = luminance(getComputedStyle(label.closest('.panel')!).backgroundColor);
    return (foreground + .05) / (background + .05);
  });
  expect(contrast).toBeGreaterThanOrEqual(4.5);
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  await expect(page.locator('.video-frame video')).toBeVisible();
  await page.getByText('Ajuste de precisión', { exact: true }).click();
  await page.getByLabel('Entrada en segundos').fill('1');
  await page.getByLabel('Salida en segundos').fill('3');
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await page.getByRole('button', { name: 'Fondo difuminado', exact: true }).click();
  await expect(page.locator('.blur-backdrop')).toBeVisible();
  await page.getByLabel('Intensidad del desenfoque').fill('75');
  await page.getByRole('button', { name: 'Acercar línea de tiempo' }).click();
  await expect(page.getByLabel('Zoom de línea de tiempo')).toHaveText('2×');
  await page.getByRole('slider', { name: 'Ajustar entrada', exact: true }).press('ArrowRight');
  await expect(page.getByLabel('Entrada en segundos')).toHaveValue('1.01');
  await page.getByRole('button', { name: 'Original', exact: true }).click();
  await expect(page.locator('.blur-backdrop')).toHaveCount(0);
  const original = (await page.locator('.video-frame').boundingBox())!;
  expect(original.width / original.height).toBeCloseTo(16 / 9, 1);
  await page.getByRole('button', { name: 'Vista exacta', exact: true }).click();
  await expect.poll(() => page.locator('.video-frame video').evaluate((v: HTMLVideoElement) => v.videoHeight)).toBe(854);
  const exact = (await page.locator('.video-frame').boundingBox())!;
  expect(exact.width / exact.height).toBeCloseTo(9 / 16, 1);
  await page.screenshot({ path: '../test-results/screenshots/editor-1366.png', fullPage: true });
  await page.getByRole('slider', { name: 'Posición de reproducción' }).press('Home');
  await expect(page.getByRole('button', { name: 'Encuadre en directo' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('slider', { name: 'Posición de reproducción' })).toHaveAttribute('aria-valuetext', '00:00:00.00');
  await expect(page.getByLabel('Entrada en segundos')).toHaveValue('1.01');
  await expect(page.getByLabel('Salida en segundos')).toHaveValue('3');
});
