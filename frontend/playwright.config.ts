import { defineConfig } from '@playwright/test';
import path from 'node:path';

const port = 8013;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  outputDir: '../test-results/browser',
  use: {
    baseURL,
    browserName: 'chromium',
    ...(process.env.CLIPZONE_BROWSER_CHANNEL ? { channel: process.env.CLIPZONE_BROWSER_CHANNEL } : {}),
    viewport: { width: 1440, height: 1100 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `"../.venv/Scripts/python.exe" -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port ${port}`,
    url: `${baseURL}/api/health`,
    reuseExistingServer: false,
    env: { CLIPZONE_DATA_DIR: path.resolve('../test-results/e2e-data', Date.now().toString()), PYTHONUTF8: '1' },
    timeout: 20_000,
  },
});
