import { test } from '@playwright/test'
import fs from 'fs'
import { authenticatePage } from './helpers'

/**
 * Runs once before all chromium tests (via project dependency).
 * Authenticates using setupClerkTestingToken (Playwright test fixtures),
 * activates the org (so JWTs include org claims), then saves the browser
 * storage state so every subsequent test context starts pre-authenticated.
 */
test('save auth state', async ({ page }) => {
  test.setTimeout(120_000) // 2-minute budget for cold Vite start + Clerk FAPI init
  if (!process.env.CLERK_SECRET_KEY) return

  const { clerkUserId, clerkOrgId } = JSON.parse(
    fs.readFileSync('/tmp/e2e-state.json', 'utf8')
  )
  await authenticatePage(page, clerkUserId)

  // Activate the org so JWTs include org claims for API calls
  if (clerkOrgId) {
    await page.evaluate(async (orgId: string) => {
      await (window as any).Clerk.setActive({ organization: orgId })
    }, clerkOrgId)
    await page.waitForFunction(
      (orgId: string) => (window as any).Clerk?.organization?.id === orgId,
      clerkOrgId,
      { timeout: 10000 },
    )
  }

  await page.context().storageState({ path: '/tmp/e2e-auth-state.json' })
})
