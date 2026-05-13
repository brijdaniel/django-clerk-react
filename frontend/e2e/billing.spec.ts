import { test, expect } from '@playwright/test'
import {
  authenticatePage,
  ensureContact, deleteContact,
  deleteSchedule,
  apiRequest,
  setOrgBalance,
} from './helpers'

let contact: { id: number }
const scheduleIds: number[] = []

test.beforeAll(async ({ browser }) => {
  if (!process.env.CLERK_SECRET_KEY) return
  const page = await browser.newPage()
  await authenticatePage(page)

  // Set known balance
  await setOrgBalance(page, 50)

  // Create a contact and send an SMS to generate a transaction
  contact = await ensureContact(page, { first_name: 'Billing', last_name: 'Test', phone: '0416111111' })
  const res = await apiRequest(page, 'POST', '/api/sms/send/', {
    message: 'Billing test message',
    recipients: [{ phone: '0416111111', contact_id: contact.id }],
  })
  if (res?.schedule_id) scheduleIds.push(res.schedule_id)

  await page.close()
})

test.afterAll(async ({ browser }) => {
  if (!process.env.CLERK_SECRET_KEY) return
  const page = await browser.newPage()
  await authenticatePage(page)
  await Promise.all([
    setOrgBalance(page, 100).catch(() => {}),
    ...scheduleIds.map(id => deleteSchedule(page, id).catch(() => {})),
    deleteContact(page, contact.id).catch(() => {}),
  ])
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
    // At least one transaction row should exist from the SMS sent in beforeAll
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
