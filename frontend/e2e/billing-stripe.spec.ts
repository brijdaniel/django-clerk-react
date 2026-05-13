/**
 * E2E tests for Stripe metered billing integration.
 *
 * Tests the full flow:
 *   1. Subscribe via Clerk PricingTable (enters Stripe test card)
 *   2. Verify org transitions to subscribed
 *   3. Verify Stripe customer is linked (billing_customer_id)
 *   4. Seed usage transactions
 *   5. Trigger invoice generation
 *   6. Verify invoice appears on billing page
 *   7. Cancel subscription
 *   8. Verify org reverts to prepaid
 *
 * Requirements:
 *   - CLERK_SECRET_KEY (Clerk auth)
 *   - STRIPE_SECRET_KEY (real Stripe test mode)
 *   - Backend running with TEST=1
 *   - Clerk Billing enabled with at least one paid plan
 */

import { test, expect } from '@playwright/test'
import fs from 'fs'
import {
  authenticatePage,
  getBillingSummary,
  seedUsage,
  generateInvoices,
  setOrgBalance,
  simulateSubscriptionActive,
  simulateSubscriptionCanceled,
  linkBillingCustomer,
} from './helpers'

// Read the org ID from global-setup state
function getOrgId(): string {
  const state = JSON.parse(fs.readFileSync('/tmp/e2e-state.json', 'utf-8'))
  return state.clerkOrgId
}

// Stripe test card details
const STRIPE_TEST_CARD = '4242424242424242'
const STRIPE_TEST_EXPIRY = '12/30'
const STRIPE_TEST_CVC = '123'

test.describe('Stripe Billing Integration', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ page }) => {
    await authenticatePage(page)
  })

  // Ensure the org is back in prepaid mode after all tests (so billing.spec.ts still works)
  test.afterAll(async ({ browser }) => {
    if (!process.env.CLERK_SECRET_KEY) return
    const orgId = getOrgId()
    await simulateSubscriptionCanceled(orgId).catch(() => {})
  })

  test('subscribe via PricingTable with Stripe test card', async ({ page }) => {
    test.setTimeout(60000) // Stripe checkout iframe is slow in CI
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 5000 })

    // Verify we start in prepaid mode
    await expect(page.getByText('Trial balance').first()).toBeVisible()

    // Open the Manage Plan dialog (button says "Subscribe" in prepaid mode)
    await page.getByRole('button', { name: /Subscribe/i }).first().click()
    await expect(page.getByText('Manage Plan').first()).toBeVisible({ timeout: 5000 })

    // Click Subscribe on the paid plan (inside the dialog's PricingTable)
    const subscribeButton = page.getByRole('button', { name: /Subscribe/i }).first()
    await expect(subscribeButton).toBeVisible({ timeout: 10000 })
    await subscribeButton.click()

    // Clerk opens checkout panel — wait for it to render
    await expect(page.getByText('Checkout').first()).toBeVisible({ timeout: 10000 })

    // Clerk's checkout fields are inside a shadow DOM — use "Pay with test card"
    // which auto-fills the card. If ZIP validation fails, fix it via shadow-piercing CSS.
    const testCardButton = page.getByRole('button', { name: 'Pay with test card' })
    const payButton = page.getByRole('button', { name: /Pay \$/ })
    await expect(testCardButton).toBeVisible({ timeout: 10000 })
    await testCardButton.click()

    // "Pay with test card" may auto-fill an invalid ZIP (e.g. 12345).
    // Use Playwright's shadow-piercing CSS selector to find and fix it.
    const zipInput = page.locator('input >> visible=true').filter({ hasText: '' }).locator('xpath=//input[contains(@autocomplete,"postal")]').first()
      .or(page.locator('css=input[autocomplete*="postal"]').first())
    if (await zipInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await zipInput.clear()
      await zipInput.fill('10001')
    }

    await expect(payButton).toBeEnabled({ timeout: 5000 })
    await payButton.click()

    // Wait for payment success confirmation and click Continue
    const continueButton = page.getByRole('button', { name: 'Continue' })
    await expect(continueButton).toBeVisible({ timeout: 20000 })
    await continueButton.click()

    // Simulate the subscription.active webhook — Clerk webhooks can't reach
    // the local Docker backend, so we post directly (same as global-setup.ts
    // does for user/org creation). TEST mode skips Svix signature verification.
    const orgId = getOrgId()
    await simulateSubscriptionActive(orgId)

    // Verify billing_mode transitioned to subscribed
    await expect(async () => {
      const summary = await getBillingSummary(page)
      expect(summary.billing_mode).toBe('subscribed')
    }).toPass({ timeout: 10000, intervals: [1000] })

    // Close dialog if still open
    await page.keyboard.press('Escape')

    // Verify the billing page now shows subscribed state
    await page.goto('/app/billing')
    await expect(
      page.getByText('Subscribed').first()
    ).toBeVisible({ timeout: 10000 })
  })

  test('billing_customer_id is linked after subscription', async ({ page }) => {
    const summary = await getBillingSummary(page)
    expect(summary.billing_mode).toBe('subscribed')

    // Link the Stripe customer — Stripe search API has eventual consistency,
    // so the initial lookup in the webhook handler may not have found it yet.
    // Poll until the link succeeds (Clerk creates the customer within seconds).
    await expect(async () => {
      const result = await linkBillingCustomer(page)
      expect(result.billing_customer_id).toBeTruthy()
    }).toPass({ timeout: 30000, intervals: [3000] })
  })

  test('seed usage and generate invoice', async ({ page }) => {
    // Seed usage transactions backdated to the previous month so that
    // generate_monthly_invoices (which invoices the *previous* month) picks them up.
    // Use 20 days back (not 35) — 35 can overshoot into 2 months ago when run early in the month.
    await seedUsage(page, { format: 'sms', amount: '2.50', description: 'E2E: 50 SMS messages', backdate_days: 20 })
    await seedUsage(page, { format: 'mms', amount: '1.00', description: 'E2E: 5 MMS messages', backdate_days: 20 })

    // Trigger invoice generation
    const result = await generateInvoices(page)
    expect(result.created).toBeGreaterThanOrEqual(1)
    expect(result.failed).toBe(0)
  })

  test('invoice appears in invoices modal', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    // Open the invoices modal
    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Invoice table should have at least one row with a status badge
    const tableRows = page.locator('table').last().locator('tbody tr')
    await expect(tableRows.first()).toBeVisible({ timeout: 5000 })
    await expect(
      tableRows.first().getByText(/open|paid/i).first()
    ).toBeVisible()

    // View link should point to Stripe
    const viewLink = tableRows.first().getByRole('link', { name: /View/i })
    await expect(viewLink).toBeVisible()
    const href = await viewLink.getAttribute('href')
    expect(href).toContain('stripe.com')
  })

  test('invoice details in billing summary API', async ({ page }) => {
    const summary = await getBillingSummary(page)
    expect(summary.latest_invoice).not.toBeNull()
    expect(summary.latest_invoice.status).toMatch(/open|paid/)
    expect(parseFloat(summary.latest_invoice.amount)).toBeGreaterThan(0)
    expect(summary.latest_invoice.invoice_url).toContain('stripe.com')
    expect(summary.latest_invoice.period_start).toBeTruthy()
    expect(summary.latest_invoice.period_end).toBeTruthy()
  })

  test('invoices modal shows Stripe invoice with correct data', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    // Open the invoices modal
    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Invoice table should have at least one row
    const tableRows = page.locator('table').last().locator('tbody tr')
    await expect(tableRows.first()).toBeVisible({ timeout: 5000 })

    // Row should contain a status badge (open or paid)
    await expect(
      tableRows.first().getByText(/open|paid/i).first()
    ).toBeVisible()

    // Row should contain a dollar amount > $0
    const amountCell = tableRows.first().locator('td').nth(3)
    const amountText = await amountCell.textContent()
    const amount = parseFloat(amountText!.replace('$', ''))
    expect(amount).toBeGreaterThan(0)

    // View link should point to Stripe
    const viewLink = tableRows.first().getByRole('link', { name: /View/i })
    await expect(viewLink).toBeVisible()
    const href = await viewLink.getAttribute('href')
    expect(href).toContain('stripe.com')
  })

  test('download Stripe invoice PDF via modal', async ({ page }) => {
    test.setTimeout(30000) // Stripe PDF fetch can be slow
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    // Open invoices modal
    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Wait for table to load
    const tableRows = page.locator('table').last().locator('tbody tr')
    await expect(tableRows.first()).toBeVisible({ timeout: 5000 })

    // Select the first invoice
    const firstRowCheckbox = tableRows.first().getByRole('checkbox')
    await firstRowCheckbox.click()

    // Click download — expect a real PDF from Stripe
    const downloadPromise = page.waitForEvent('download', { timeout: 20000 })
    await page.getByRole('button', { name: /Download selected/i }).click()
    const download = await downloadPromise

    // Verify it's a PDF file
    expect(download.suggestedFilename()).toMatch(/\.pdf$/)

    // Read the downloaded file and verify it's a real PDF
    const filePath = await download.path()
    expect(filePath).toBeTruthy()
    const buffer = fs.readFileSync(filePath!)
    expect(buffer.length).toBeGreaterThan(100)
    expect(buffer.subarray(0, 5).toString()).toBe('%PDF-')
  })

  test('cancel subscription via Cancel Plan button', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    // Click Manage Plan — opens Clerk's SubscriptionDetailsButton drawer
    await page.getByRole('button', { name: /Manage Plan/i }).click()

    // Clerk's drawer should appear with cancel/manage options
    // Click the cancel action inside the drawer
    const cancelAction = page.getByRole('button', { name: /cancel|unsubscribe/i }).last()
    await expect(cancelAction).toBeVisible({ timeout: 10000 })
    await cancelAction.click()

    // Confirm cancellation if prompted
    const confirmButton = page
      .getByRole('button', { name: /confirm|yes|cancel/i })
      .last()
    if (await confirmButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await confirmButton.click()
    }

    // Simulate the webhook (Clerk may not deliver to local Docker)
    const orgId = getOrgId()
    await simulateSubscriptionCanceled(orgId)

    // Verify billing_mode reverted to prepaid
    await expect(async () => {
      const summary = await getBillingSummary(page)
      expect(summary.billing_mode).toBe('prepaid')
    }).toPass({ timeout: 10000, intervals: [1000] })

    // Verify the billing page reflects the change
    await page.goto('/app/billing')
    await expect(
      page.getByText('Trial balance').first().or(page.getByText('Plan').first())
    ).toBeVisible({ timeout: 10000 })
  })
})
