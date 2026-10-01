import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  reporter: 'list',
  outputDir: './test-results',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1100 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'bun run preview',
    url: 'http://127.0.0.1:4173/',
    env: { PORT: '4173' },
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
})
