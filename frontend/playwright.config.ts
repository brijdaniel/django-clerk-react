import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL || 'http://localhost:5173'
const isRemote = baseURL !== 'http://localhost:5173'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: 'html',
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // storageState is set only on the chromium project (auth.setup.ts must run first)
  },
  projects: [
    {
      name: 'setup',
      testMatch: '**/auth.setup.ts',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: { args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'] },
      },
    },
    {
      name: 'chromium',
      dependencies: ['setup'],
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
          args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
        },
        ...(process.env.CLERK_SECRET_KEY ? { storageState: '/tmp/e2e-auth-state.json' } : {}),
      },
    },
  ],
  // Only start a local dev server when running against localhost.
  // When E2E_BASE_URL points to a deployed environment, skip the local server.
  ...(!isRemote && {
    webServer: {
      command: 'npm run dev -- --host 0.0.0.0',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 30000,
    },
  }),
})
