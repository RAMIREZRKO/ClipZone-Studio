import { expect, test } from '@playwright/test';

test('Mi espacio local queda dentro de la ventana a distintas resoluciones y escalas', async ({ page }) => {
  const desktop = { width: 1920, height: 1080 };
  const layouts = [
    { ...desktop, label: '1920×1080 sin barras' },
    { width: 1920, height: 960, label: '1920×1080 con barras del navegador' },
    { width: 1366, height: 638, label: '1366×768 con barras del navegador' },
    { width: 390, height: 700, label: 'móvil compacto' },
    ...[1.25, 1.5, 1.75, 2, 2.5].map(zoom => ({
      width: Math.floor(desktop.width / zoom),
      height: Math.floor(960 / zoom),
      label: `${zoom * 100}% en un escritorio Full HD con barras`,
    })),
  ];
  await page.goto('/');
  const sidebar = page.locator('.sidebar');
  const profile = sidebar.getByText('Mi espacio local', { exact: true });
  const menu = sidebar.locator('.sidebar-scroll');
  for (const { width, height, label } of layouts) {
    await test.step(label, async () => {
      await page.setViewportSize({ width, height });
      await expect(profile).toBeInViewport({ ratio: 1 });
      const sidebarRect = (await sidebar.boundingBox())!;
      const profileRect = (await sidebar.locator('.profile').boundingBox())!;
      const menuRect = (await menu.boundingBox())!;
      expect(sidebarRect.height).toBeCloseTo(height, 0);
      expect(profileRect.y + profileRect.height).toBeLessThanOrEqual(height);
      expect(menuRect.y + menuRect.height).toBeLessThanOrEqual(profileRect.y);
      expect(await menu.evaluate(el => el.scrollWidth)).toBeLessThanOrEqual(await menu.evaluate(el => el.clientWidth));
    });
  }
});

test('el menú corto se desplaza con la rueda y el teclado con el perfil fijo', async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 480 });
  await page.goto('/');
  const sidebar = page.locator('.sidebar');
  const profile = sidebar.getByText('Mi espacio local', { exact: true });
  const menu = sidebar.locator('.sidebar-scroll');
  const help = sidebar.getByRole('button', { name: 'Guía de inicio' });
  await expect(help).not.toBeInViewport({ ratio: 1 });
  const firstProfile = await profile.boundingBox();
  const windowScroll = await page.evaluate(() => window.scrollY);
  await menu.hover();
  await page.mouse.wheel(0, 750);
  await expect(help).toBeInViewport({ ratio: 1 });
  expect(await menu.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  expect(await profile.boundingBox()).toEqual(firstProfile);
  await page.mouse.wheel(0, 750);
  expect(await page.evaluate(() => window.scrollY)).toBe(windowScroll);

  await sidebar.getByRole('button', { name: 'Gráficos y plantillas' }).focus();
  await page.keyboard.press('Tab');
  await expect(help).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog', { name: 'De tu vídeo a tu primer clip' })).toBeVisible();
});
