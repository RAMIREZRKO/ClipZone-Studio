import { test, expect } from '@playwright/test';
import path from 'node:path';

test('elimina los vídeos y los clips seleccionados solo después de confirmar', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  const file = page.getByLabel('Seleccionar vídeo', { exact: true });
  await file.setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  await expect(page.locator('.video-frame video')).toBeVisible();
  await page.getByLabel('Resolución', { exact: true }).selectOption('480');
  await page.getByText('Ajuste de precisión', { exact: true }).click();
  await page.getByLabel('Salida en segundos').fill('1');
  await page.getByLabel('Nombre del clip').fill('Clip de almacenamiento');
  await page.getByRole('button', { name: 'Exportar clip', exact: true }).click();
  const exported = page.locator('.export-card').filter({ hasText: 'Clip de almacenamiento' });
  await expect(exported.getByText('Listo para compartir')).toBeVisible();

  await page.getByRole('button', { name: 'Editor de clips', exact: true }).click();
  await file.setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  await expect(page.getByText(/Vídeo importado/)).toBeVisible();
  await page.getByRole('button', { name: /Mis vídeos/ }).click();
  const cards = page.locator('.library-grid .video-card');
  await expect.poll(() => cards.count()).toBeGreaterThanOrEqual(2);
  await page.getByRole('checkbox', { name: 'Seleccionar todos' }).check();
  await page.getByRole('button', { name: 'Eliminar selección' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('clips relacionados');
  await dialog.getByRole('button', { name: 'Cancelar', exact: true }).click();
  expect(await cards.count()).toBeGreaterThanOrEqual(2);
  await page.getByRole('button', { name: 'Eliminar selección' }).click();
  await dialog.getByRole('radio', { name: 'Borrar los archivos administrados' }).check();
  await dialog.getByRole('button', { name: 'Borrar archivos', exact: true }).click();
  await expect(cards).toHaveCount(0);

  await page.getByRole('button', { name: /Exportaciones/ }).click();
  await expect(exported.getByRole('link', { name: 'Descargar' })).toBeVisible();
  await exported.getByRole('button', { name: 'Eliminar', exact: true }).click();
  await dialog.getByRole('button', { name: 'Quitar del listado', exact: true }).click();
  await expect(exported).toHaveCount(0);
  await page.getByRole('button', { name: 'Almacenamiento' }).click();
  await expect(page.getByText('Total administrado')).toBeVisible();
  await page.getByRole('button', { name: 'Limpiar temporales' }).click();
  await dialog.getByRole('button', { name: 'Limpiar archivos', exact: true }).click();
  await expect(page.getByText(/Temporales retirados/)).toBeVisible();
});
