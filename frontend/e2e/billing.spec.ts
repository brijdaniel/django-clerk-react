import { test, expect } from '@playwright/test'
import {
  authenticatePage,
  seedUsage,
  setOrgBalance,
} from './helpers'

// Per-spec token so fixtures can't collide with other specs and retries stay
// idempotent (stable string, NOT Date.now()).
const TOKEN = 'BILL'

test.beforeAll(async ({ browser }) => {
  if (!process.env.CLERK_SECRET_KEY) return
  const page = await browser.newPage()
  await authenticatePage(page)

  // Set known balance
  await setOrgBalance(page, 50)

  // Seed a usage transaction so transaction history has at least one row
  await seedUsage(page, {
    usage_type: 'widget',
    amount: '0.10',
    description: `${TOKEN} billing test usage`,
  })

  await page.close()
})

test.afterAll(async ({ browser }) => {
  if (!process.env.CLERK_SECRET_KEY) return
  const page = await browser.newPage()
  await authenticatePage(page)
  await setOrgBalance(page, 100).catch(() => {})
  await page.close()
})

test.beforeEach(async ({ page }) => {
  await authenticatePage(page)
})

test.describe('Billing Page', () => {
  test.describe.configure({ mode: 'serial' })

  test('displays billing heading and mode badge', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })
    // Mode badge is either Prepaid or Subscribed depending on Clerk subscription state
    await expect(
      page.getByText(/Prepaid|Subscribed/).first()
    ).toBeVisible()
  })

  test('shows balance or plan label', async ({ page }) => {
    await page.goto('/app/billing')
    // Shows "Prepaid balance" for prepaid orgs or "Plan" for subscribed orgs
    await expect(
      page.getByText('Prepaid balance').first().or(page.getByText('Plan').first())
    ).toBeVisible({ timeout: 10000 })
  })

  test('shows monthly spend section', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText(/Monthly spend/).first()).toBeVisible({ timeout: 10000 })
  })

  test('displays transaction history', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Transaction history').first()).toBeVisible({ timeout: 10000 })
    // At least one transaction row should exist from the usage seeded in beforeAll
    await expect(page.locator('table').last().locator('tbody tr').first()).toBeVisible()
  })

  test('shows exhausted balance warning when balance is zero (prepaid only)', async ({ page }) => {
    // This warning only shows for prepaid orgs — skip if Clerk has an active subscription.
    // Wait for networkidle so Clerk subscription data has time to load before checking.
    await page.goto('/app/billing', { waitUntil: 'networkidle' })
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })
    // Give Clerk subscription hook time to resolve — check for either Prepaid balance or Subscribed badge
    await expect(
      page.getByText('Prepaid balance').or(page.getByText('Subscribed')).first()
    ).toBeVisible({ timeout: 10000 })
    const isSubscribed = await page.getByText('Subscribed').first().isVisible().catch(() => false)
    if (isSubscribed) {
      // Subscribed orgs don't show balance warnings
      return
    }
    try {
      await setOrgBalance(page, 0)
      // Set up response listener before reload so we don't miss the API response
      const billingResponse = page.waitForResponse(
        resp => resp.url().includes('/api/billing/summary') && resp.status() === 200
      )
      await page.reload({ waitUntil: 'networkidle' })
      await billingResponse
      await expect(page.getByText(/Balance exhausted/).first()).toBeVisible({ timeout: 15000 })
    } finally {
      await setOrgBalance(page, 100).catch(() => {})
    }
  })
})
