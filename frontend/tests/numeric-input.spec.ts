import { expect, test, type Locator, type Page } from '@playwright/test';
import path from 'node:path';

async function erase(field: Locator) {
  await field.focus();
  await field.press('Control+a');
  await field.press('Backspace');
  await expect(field).toHaveValue('');
}

async function typeValue(field: Locator, text: string) {
  await erase(field);
  await field.pressSequentially(text);
  await expect(field).toHaveValue(text);
}

async function importDemo(page: Page) {
  await page.goto('/');
  await expect(page.getByText('Motor local listo')).toBeVisible();
  await page.getByLabel('Seleccionar vídeo', { exact: true }).setInputFiles(path.resolve('../demo/clipzone-demo.mp4'));
  await expect(page.locator('.video-frame video')).toBeVisible();
}

test('editor permite borrar, escribir, pegar y confirmar sin mover los límites durante la escritura', async ({ page, context }) => {
  await importDemo(page);
  await page.getByText('Ajuste de precisión', { exact: true }).click();
  const entry = page.getByLabel('Entrada en segundos');
  const handle = page.getByRole('slider', { name: 'Ajustar entrada' });
  await typeValue(entry, '4');
  await expect(handle).toHaveAttribute('aria-valuetext', '00:00:00.00');
  await entry.press('Enter');
  await expect(handle).toHaveAttribute('aria-valuetext', '00:00:04.00');

  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.evaluate(() => navigator.clipboard.writeText(' 2,75 '));
  await entry.press('Control+a');
  await entry.press('Control+v');
  await expect(entry).toHaveValue(' 2,75 ');
  await expect(handle).toHaveAttribute('aria-valuetext', '00:00:04.00');
  await entry.press('Tab');
  await expect(entry).toHaveValue('2.75');
  await expect(handle).toHaveAttribute('aria-valuetext', '00:00:02.75');

  await erase(entry);
  await entry.press('Tab');
  await expect(entry).toHaveValue('2.75');
  const margin = page.getByLabel('Margen superior');
  await typeValue(margin, '999');
  await margin.press('Enter');
  await expect(margin).toHaveValue('35');
  await typeValue(margin, '-4');
  await margin.press('Tab');
  await expect(margin).toHaveValue('0');
  await typeValue(margin, 'xyz');
  await margin.press('Enter');
  await expect(margin).toHaveValue('0');
  await expect(page.getByRole('slider', { name: 'Posición de reproducción' })).toHaveAttribute('aria-valuetext', '00:00:00.00');
});

test('subtítulos y ajustes de IA conservan el último valor y guardan la precisión admitida', async ({ page }) => {
  await importDemo(page);
  const panel = page.getByRole('region', { name: 'Subtítulos dinámicos' });
  await panel.getByRole('button', { name: 'Añadir segmento' }).click();
  await panel.getByLabel('Texto del segmento 1').fill('Prueba numérica');
  const start = panel.getByLabel('Inicio', { exact: true });
  await typeValue(start, '0,125');
  await start.press('Enter');
  await expect(start).toHaveValue('0.125');
  const end = panel.getByLabel('Final', { exact: true });
  const previousEnd = await end.inputValue();
  await erase(end);
  await end.press('Tab');
  await expect(end).toHaveValue(previousEnd);
  const saved = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/captions'));
  await panel.getByRole('button', { name: 'Guardar subtítulos' }).click();
  expect((await saved).postDataJSON().segments[0].start).toBe(0.125);
  await expect(panel.getByText('Cambios guardados.')).toBeVisible();
  await panel.getByText('Estilo y posición de subtítulos', { exact: true }).click();
  const outline = panel.getByLabel('Contorno', { exact: true });
  await typeValue(outline, '2,5');
  await outline.press('Tab');
  await expect(outline).toHaveValue('2.5');
  const proposals = page.getByLabel('Máximo de propuestas');
  await typeValue(proposals, '0');
  await proposals.press('Enter');
  await expect(proposals).toHaveValue('1');
  await typeValue(proposals, '14');
  await proposals.press('Escape');
  await expect(proposals).toHaveValue('1');
});

test('gráficos y plantillas aplican los números confirmados y conservan un final abierto', async ({ page }) => {
  await page.goto('/');
  const panel = page.getByRole('region', { name: 'Gráficos y plantillas' });
  await panel.getByRole('button', { name: 'Agregar texto' }).click();
  const opacity = panel.getByLabel('Opacidad del texto (%)');
  await typeValue(opacity, '45');
  await opacity.press('Tab');
  await panel.getByText('Tiempos avanzados', { exact: true }).click();
  const start = panel.getByLabel('Aparece (s)', { exact: true });
  await typeValue(start, '0,75');
  await start.press('Enter');
  const end = panel.getByLabel('Desaparece (s)', { exact: true });
  await expect(end).toHaveValue('');
  await end.pressSequentially('2.50');
  await end.press('Enter');
  await erase(end);
  await end.press('Tab');
  await expect(end).toHaveValue('2.5');
  await panel.getByRole('button', { name: 'Hasta el final del clip' }).click();
  await expect(end).toHaveValue('');
  await expect(start).toHaveValue('0.75');

  await panel.getByLabel('Nombre de plantilla').fill('Valores desde teclado');
  const saved = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/templates'));
  await panel.getByRole('button', { name: 'Guardar como plantilla' }).click();
  expect((await saved).postDataJSON().options.graphics[0]).toMatchObject({ opacity: 45, start: 0.75, end: null });
  await expect(panel.getByText('Plantilla guardada.')).toBeVisible();
  await typeValue(opacity, '10');
  await opacity.press('Enter');
  await panel.getByRole('button', { name: 'Aplicar plantilla' }).click();
  await expect(panel.getByLabel('Opacidad del texto (%)')).toHaveValue('45');
});
