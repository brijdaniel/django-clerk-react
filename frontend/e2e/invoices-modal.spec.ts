/**
 * E2E tests for the Invoices Modal on the billing page.
 *
 * Flow:
 *   1. Simulate subscription active (puts org in subscribed mode)
 *   2. Seed backdated usage transactions (previous month)
 *   3. Trigger invoice generation via test endpoint
 *   4. Seed current-month usage (for preview)
 *   5. Open the invoices modal and verify data
 *   6. Test bulk download
 *   7. Clean up: revert to prepaid, restore balance
 *
 * Requirements:
 *   - CLERK_SECRET_KEY (Clerk auth)
 *   - Backend running with TEST=1
 *   - No STRIPE_SECRET_KEY needed (uses MockMeteredBillingProvider)
 */

import { test, expect } from '@playwright/test'
import fs from 'fs'
import {
  authenticatePage,
  apiRequest,
  getBillingSummary,
  seedUsage,
  setOrgBalance,
  simulateSubscriptionActive,
  simulateSubscriptionCanceled,
} from './helpers'

function getOrgId(): string {
  const state = JSON.parse(fs.readFileSync('/tmp/e2e-state.json', 'utf-8'))
  return state.clerkOrgId
}

test.describe('Invoices Modal', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async ({ browser }) => {
    if (!process.env.CLERK_SECRET_KEY) return
    const page = await browser.newPage()
    await authenticatePage(page)

    const orgId = getOrgId()

    // Reset to prepaid first (in case a previous run left org as subscribed),
    // then activate — ensures the webhook handler runs the full setup path
    // including linking billing_customer_id.
    await simulateSubscriptionCanceled(orgId).catch(() => {})
    await simulateSubscriptionActive(orgId)

    // Wait for billing_mode to transition
    await expect(async () => {
      const summary = await getBillingSummary(page)
      expect(summary.billing_mode).toBe('subscribed')
    }).toPass({ timeout: 10000, intervals: [1000] })

    // Create an invoice record directly (bypasses Stripe provider which would
    // reject a mock customer ID when STRIPE_SECRET_KEY is set in Docker).
    // May fail if an invoice already exists for this period (e.g. from billing-stripe tests) — that's fine.
    const now = new Date()
    const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1)
    const firstOfPrevMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1)
    await apiRequest(page, 'POST', '/api/billing/test-create-invoice/', {
      amount: '3.50',
      period_start: firstOfPrevMonth.toISOString(),
      period_end: firstOfMonth.toISOString(),
    }).catch(() => {})

    // Verify at least one invoice exists (created now or by billing-stripe tests)
    const summary = await getBillingSummary(page)
    expect(summary.latest_invoice).not.toBeNull()

    // Seed current-month usage (for the preview section)
    await seedUsage(page, { usage_type: 'api_call', amount: '0.50', description: 'E2E: 10 api calls this month' })

    await page.close()
  })

  test.afterAll(async ({ browser }) => {
    if (!process.env.CLERK_SECRET_KEY) return
    const page = await browser.newPage()
    await authenticatePage(page)
    const orgId = getOrgId()
    await simulateSubscriptionCanceled(orgId).catch(() => {})
    await setOrgBalance(page, 100).catch(() => {})
    await page.close()
  })

  test.beforeEach(async ({ page }) => {
    await authenticatePage(page)
  })

  test('Invoices button opens modal', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    // Click the "Invoices" button
    const allInvoicesBtn = page.getByRole('button', { name: /Invoices/i })
    await expect(allInvoicesBtn).toBeVisible({ timeout: 5000 })
    await allInvoicesBtn.click()

    // Modal should open with "Invoices" title
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })
  })

  test('invoice history shows generated invoice', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Wait for "Invoice history" heading to appear
    await expect(page.getByText('Invoice history')).toBeVisible()

    // Should have at least one invoice row in the table
    const tableRows = page.locator('table').last().locator('tbody tr')
    await expect(tableRows.first()).toBeVisible({ timeout: 5000 })

    // Row should contain a status badge (open from MockMeteredBillingProvider)
    await expect(
      page.getByText(/open|paid|draft/i).first()
    ).toBeVisible()

    // Row should contain a dollar amount
    await expect(
      page.locator('table').last().locator('tbody tr').first().locator('td').nth(3)
    ).toContainText('$')
  })

  test('current month preview shows usage estimate', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Preview section should be visible (org is subscribed)
    await expect(page.getByText('Current month estimate')).toBeVisible({ timeout: 5000 })

    // Should show the line item badge from the current-month seeded usage
    await expect(page.getByText('API_CALL').first()).toBeVisible()

    // Should show a total
    await expect(page.getByText(/Total: \$/)).toBeVisible()
  })

  test('select all checkbox selects all invoices', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Wait for table to load
    const tableRows = page.locator('table').last().locator('tbody tr')
    await expect(tableRows.first()).toBeVisible({ timeout: 5000 })

    // Click the select-all checkbox (first checkbox in the table header)
    const selectAllCheckbox = page.locator('table').last().locator('thead').getByRole('checkbox')
    await selectAllCheckbox.click()

    // Download button should show a count > 0
    await expect(
      page.getByRole('button', { name: /Download selected \([1-9]/i })
    ).toBeVisible()
  })

  test('download selected sends download request', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Wait for table to load
    const tableRows = page.locator('table').last().locator('tbody tr')
    await expect(tableRows.first()).toBeVisible({ timeout: 5000 })

    // Click the first row's checkbox to select one invoice
    const firstRowCheckbox = tableRows.first().getByRole('checkbox')
    await firstRowCheckbox.click()

    // Intercept the download API request to verify it's called correctly
    const responsePromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/billing/invoice-download/'),
      { timeout: 15000 },
    )
    await page.getByRole('button', { name: /Download selected/i }).click()
    const response = await responsePromise

    // The request was made — verify it's a POST with invoice_ids
    expect(response.request().method()).toBe('POST')
    const requestBody = response.request().postDataJSON()
    expect(requestBody.invoice_ids).toBeDefined()
    expect(requestBody.invoice_ids.length).toBeGreaterThan(0)

    // Response is either a PDF (200) or a failure (404) depending on
    // whether the billing provider can fetch the mock invoice's PDF.
    // Either way, the button click triggered the correct API call.
    expect([200, 404]).toContain(response.status())
  })

  test('View link exists for invoice', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Wait for table rows
    const tableRows = page.locator('table').last().locator('tbody tr')
    await expect(tableRows.first()).toBeVisible({ timeout: 5000 })

    // View link should exist with an href
    const viewLink = page.getByRole('link', { name: /View/i }).first()
    await expect(viewLink).toBeVisible()
    const href = await viewLink.getAttribute('href')
    expect(href).toBeTruthy()
  })

  test('Close button closes modal', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Click Close
    await page.getByRole('button', { name: /Close/i }).click()

    // Modal should disappear
    await expect(page.getByRole('heading', { name: 'Invoices' })).not.toBeVisible({ timeout: 3000 })
  })

  test('Download selected button is disabled with no selection', async ({ page }) => {
    await page.goto('/app/billing')
    await expect(page.getByText('Billing').first()).toBeVisible({ timeout: 10000 })

    await page.getByRole('button', { name: /Invoices/i }).click()
    await expect(page.getByRole('heading', { name: 'Invoices' })).toBeVisible({ timeout: 5000 })

    // Download button should show count 0 and be disabled
    const downloadBtn = page.getByRole('button', { name: /Download selected \(0\)/i })
    await expect(downloadBtn).toBeVisible()
    await expect(downloadBtn).toBeDisabled()
  })
})
