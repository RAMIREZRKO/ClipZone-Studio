import { expect, test } from '@playwright/test';
import path from 'node:path';

test('muestra el disco, permite seleccionar una carpeta y cancelar la migración programada', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Almacenamiento', exact: true }).click();
  await expect(page.getByText('Espacio libre en la unidad')).toBeVisible();
  await expect(page.getByText('Máximo de 1 GB')).toBeVisible();
  const original = await (await page.request.get('/api/storage')).json();
  const directory = path.join(path.dirname(original.directory), 'nuevo almacenamiento');

  const change = page.getByRole('button', { name: 'Cambiar carpeta', exact: true });
  await change.click();
  const dialog = page.getByRole('dialog', { name: 'Cambiar carpeta de almacenamiento' });
  await dialog.getByRole('button', { name: 'Examinar unidades' }).click();
  const drive = path.parse(original.directory).root.replace(/[\\/]$/, '');
  await dialog.getByRole('button', { name: drive, exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Usar esta carpeta' })).toBeVisible();
  await dialog.getByLabel('Carpeta de destino').fill(directory);
  await dialog.getByRole('button', { name: 'Programar cambio' }).click();
  await expect(page.getByText(/Cambio programado a/)).toContainText(directory);
  await page.getByRole('button', { name: 'Cancelar cambio' }).click();
  await expect(page.getByText(/Cambio programado a/)).toHaveCount(0);
  expect((await (await page.request.get('/api/storage')).json()).directory).toBe(original.directory);
});
