import { test, expect } from '@playwright/test'
import { authenticatePage } from './helpers'

test.beforeEach(async ({ page }) => {
  await authenticatePage(page)
})

test.describe('Buy Credits', () => {
  test.describe.configure({ mode: 'serial' })

  test('Buy Credits button is visible on billing page for prepaid org', async ({ page }) => {
    await page.goto('/app/billing', { waitUntil: 'networkidle' })
    // Skip if org is subscribed (Buy Credits only shows for prepaid)
    const isSubscribed = await page.getByText('Subscribed').first().isVisible().catch(() => false)
    if (isSubscribed) {
      test.skip()
      return
    }
    await expect(page.getByRole('button', { name: 'Buy Credits' })).toBeVisible({ timeout: 10000 })
  })

  test('Buy Credits dialog opens with presets and custom input', async ({ page }) => {
    await page.goto('/app/billing', { waitUntil: 'networkidle' })
    const isSubscribed = await page.getByText('Subscribed').first().isVisible().catch(() => false)
    if (isSubscribed) {
      test.skip()
      return
    }

    await page.getByRole('button', { name: 'Buy Credits' }).click()

    // Dialog is open with preset amounts
    await expect(page.getByText('$10')).toBeVisible()
    await expect(page.getByText('$100')).toBeVisible()
    await expect(page.getByText('$1,000')).toBeVisible()

    // Custom amount input is present
    await expect(page.getByPlaceholder('5 – 10,000')).toBeVisible()

    // Purchase button starts disabled
    const purchaseBtn = page.getByRole('button', { name: /Purchase/i }).last()
    await expect(purchaseBtn).toBeDisabled()
  })

  test('selecting a preset enables the Purchase button', async ({ page }) => {
    await page.goto('/app/billing', { waitUntil: 'networkidle' })
    const isSubscribed = await page.getByText('Subscribed').first().isVisible().catch(() => false)
    if (isSubscribed) {
      test.skip()
      return
    }

    await page.getByRole('button', { name: 'Buy Credits' }).click()
    await page.getByText('$50').click()

    const purchaseBtn = page.getByRole('button', { name: /Purchase \$50/i })
    await expect(purchaseBtn).toBeEnabled()
  })

  test('custom amount enables the Purchase button', async ({ page }) => {
    await page.goto('/app/billing', { waitUntil: 'networkidle' })
    const isSubscribed = await page.getByText('Subscribed').first().isVisible().catch(() => false)
    if (isSubscribed) {
      test.skip()
      return
    }

    await page.getByRole('button', { name: 'Buy Credits' }).click()
    await page.getByPlaceholder('5 – 10,000').fill('75')

    const purchaseBtn = page.getByRole('button', { name: /Purchase \$75/i })
    await expect(purchaseBtn).toBeEnabled()
  })

  test('purchase success banner shows on return from Stripe', async ({ page }) => {
    await page.goto('/app/billing?purchase=success')
    await expect(page.getByText(/Credit purchase successful/i)).toBeVisible({ timeout: 10000 })
  })
})
