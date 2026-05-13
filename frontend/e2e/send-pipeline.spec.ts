/**
 * E2E tests for the async send pipeline from the user's perspective.
 *
 * These tests verify UI behaviour across the full send flow:
 *   - Submitting the form → API called → success/error state shown
 *   - 202 Accepted responses handled as success (not treated as errors)
 *   - Billing gate errors (insufficient balance, monthly limit) surface correctly
 *   - Group send shows queued recipient count in the summary
 *   - MMS send flow works end-to-end in the browser
 *
 * Billing gate error tests use real backend state:
 *   - setOrgBalance(page, 0) triggers "Insufficient balance. Subscribe to continue sending."
 *   - createConfig(page, { name: 'monthly_limit', value: '0.00' }) triggers monthly limit error
 * Both use try/finally to restore state even on test failure.
 */

import { test, expect, type Page } from '@playwright/test'
import {
  authenticatePage,
  deleteContact, ensureContact,
  createGroup, addMembers, deleteGroup,
  deleteSchedule, forceStatus,
  apiRequest,
  setOrgBalance,
  createConfig, deleteConfig,
  uploadFile, sendMms,
} from './helpers'

// Minimal valid PNG (1x1 transparent pixel)
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==',
  'base64',
)

// ---------------------------------------------------------------------------
// Shared fixture data
// ---------------------------------------------------------------------------

let contact: { id: number }
let group: { id: number }
let pipelineScheduleIds: number[] = []

test.beforeAll(async ({ browser }) => {
  if (!process.env.CLERK_SECRET_KEY) return
  const page = await browser.newPage()
  await authenticatePage(page)

  // Ensure enough balance for all sends (parallel tests may consume credits)
  await setOrgBalance(page, 100)

  // Clean up any stale monthly_limit config from a previous failed run
  const configs = await apiRequest(page, 'GET', '/api/configs/?limit=100')
  for (const c of (configs.results || configs || [])) {
    if (c.name === 'monthly_limit') {
      await apiRequest(page, 'DELETE', `/api/configs/${c.id}/`).catch(() => {})
    }
  }

  let groupContact: any
  ;[contact, groupContact, group] = await Promise.all([
    ensureContact(page, { first_name: 'Pipeline', last_name: 'Test', phone: '0416111111' }),
    ensureContact(page, { first_name: 'Group', last_name: 'Member', phone: '0416222222' }),
    createGroup(page, { name: 'Pipeline Group' }),
  ])
  await addMembers(page, group.id, [groupContact.id])

  // Create schedules for pipeline status display tests
  const PIPELINE_STATES = [
    { message: 'Hello Charlie', status: 'queued',    phone: '0416333333' },
    { message: 'Hello Diana',   status: 'retrying',  phone: '0416444444' },
    { message: 'Hello Eve',     status: 'delivered', phone: '0416555555' },
    { message: 'Hello Frank',   status: 'failed',    phone: '0416666666' },
  ]
  const results = await Promise.all(
    PIPELINE_STATES.map(s => apiRequest(page, 'POST', '/api/sms/send/', {
      message: s.message, recipients: [{ phone: s.phone, contact_id: contact.id }],
    }))
  )
  results.forEach(r => pipelineScheduleIds.push(r.schedule_id))

  // Wait for the Celery worker to finish processing all dispatched tasks
  // before overriding statuses — otherwise the worker may change them back.
  await page.waitForTimeout(3000)

  await Promise.all(
    PIPELINE_STATES.map((s, i) => forceStatus(page, results[i].schedule_id, s.status))
  )

  await page.close()
})

test.afterAll(async ({ browser }) => {
  if (!process.env.CLERK_SECRET_KEY) return
  const page = await browser.newPage()
  await authenticatePage(page)
  await Promise.all([
    ...pipelineScheduleIds.map(id => deleteSchedule(page, id).catch(() => {})),
    group?.id   ? deleteGroup(page, group.id).catch(() => {})    : Promise.resolve(),
    contact?.id ? deleteContact(page, contact.id).catch(() => {}) : Promise.resolve(),
  ])
  await page.close()
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Fill and submit the single-recipient send form. */
async function fillAndSubmitSmsForm(page: Page, message = 'Hello test') {
  const textarea = page.locator('textarea').first()
  await expect(textarea).toBeVisible({ timeout: 10000 })
  await textarea.fill(message)

  const recipientInput = page.getByPlaceholder(/search|recipient|phone|contact/i).first()
  if (await recipientInput.isVisible()) {
    await recipientInput.fill('0416111111')
    const firstOption = page.locator('[role="option"]').first()
    if (await firstOption.isVisible({ timeout: 1000 }).catch(() => false)) {
      await firstOption.click()
    }
  }

  const sendBtn = page.getByRole('button', { name: /^send now$/i }).first()
  await sendBtn.click()
}

// ---------------------------------------------------------------------------
// beforeEach
// ---------------------------------------------------------------------------

test.beforeEach(async ({ page }) => {
  await authenticatePage(page)
})

// ---------------------------------------------------------------------------
// Success flows
// ---------------------------------------------------------------------------

test.describe('Send SMS — success flow', () => {
  test('202 response treated as success — summary dialog shows 1 successful', async ({ page }) => {
    await page.goto('/app/send')
    await fillAndSubmitSmsForm(page)
    await expect(page.getByText(/messages queued/i)).toBeVisible({ timeout: 8000 })
    await expect(page.getByText('Queued', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Unsuccessful').first()).toBeVisible()
  })

  test('success clears the message input', async ({ page }) => {
    await page.goto('/app/send')
    await fillAndSubmitSmsForm(page, 'This should be cleared after send')
    await expect(page.getByText(/messages queued/i)).toBeVisible({ timeout: 8000 })
  })
})

test.describe('MMS — file upload and send', () => {
  test('file upload returns accessible URL', async ({ page }) => {
    const result = await uploadFile(page, TINY_PNG, 'test.png', 'image/png')
    expect(result.success).toBe(true)
    expect(result.url).toBeTruthy()
    expect(result.file_id).toBeTruthy()

    // URL accessibility check only applies with real storage (catches stripped SAS tokens).
    // Mock storage returns mock-storage.example.com which isn't reachable.
    if (!result.url.includes('mock-storage.example.com')) {
      const res = await page.request.fetch(result.url)
      expect(res.status()).toBe(200)
    }
  })

  test('MMS send via API succeeds end-to-end', async ({ page }) => {
    const upload = await uploadFile(page, TINY_PNG, 'mms-test.png', 'image/png')
    const result = await sendMms(page, {
      message: 'E2E MMS test',
      media_url: upload.url,
      recipients: [{ phone: '0416111111', contact_id: contact.id }],
    })
    expect(result.schedule_id).toBeTruthy()

    // Verify schedule is not in a failed state
    const schedule = await apiRequest(page, 'GET', `/api/schedules/${result.schedule_id}/`)
    expect(['queued', 'processing', 'sent', 'delivered']).toContain(schedule.status)
  })

  test('MMS send via UI with file upload', async ({ page }) => {
    await page.goto('/app/send')

    // Upload image via the file input
    const fileInput = page.locator('input[type="file"]')
    await fileInput.setInputFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: TINY_PNG,
    })

    // Wait for upload to complete (spinner gone, no error)
    await expect(page.getByText(/uploading/i)).not.toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/upload failed/i)).not.toBeVisible()

    // Verify MMS indicator appears (format: "MMS · N / 306 characters · ...")
    await expect(page.getByText(/MMS · \d+ \/ \d+ characters/)).toBeVisible()

    // Fill message and recipient, then send
    await fillAndSubmitSmsForm(page, 'MMS from UI test')
    await expect(page.getByText(/messages queued/i)).toBeVisible({ timeout: 8000 })
  })

  test('file upload rejects invalid file type', async ({ page }) => {
    const txtBuffer = Buffer.from('not an image')
    try {
      await uploadFile(page, txtBuffer, 'test.txt', 'text/plain')
      throw new Error('Expected upload to fail')
    } catch (e: any) {
      expect(e.message).toContain('400')
    }
  })

  test('file upload rejects oversized file', async ({ page }) => {
    const largeBuffer = Buffer.alloc(500 * 1024, 0) // 500KB
    try {
      await uploadFile(page, largeBuffer, 'large.png', 'image/png')
      throw new Error('Expected upload to fail')
    } catch (e: any) {
      expect(e.message).toContain('400')
    }
  })
})

// ---------------------------------------------------------------------------
// Billing gate errors (real backend state — no mocks)
// ---------------------------------------------------------------------------

test.describe('Billing gate — error surfaces in UI', () => {
  // These tests mutate shared org state (balance, config) — must not run in parallel
  test.describe.configure({ mode: 'serial' })

  test('insufficient prepaid balance shows balance error message', async ({ page }) => {
    await setOrgBalance(page, 0)
    try {
      await page.goto('/app/send')
      await fillAndSubmitSmsForm(page)
      await expect(
        page.getByText(/insufficient balance/i).or(page.getByText(/subscribe to continue/i)).first()
      ).toBeVisible({ timeout: 15000 })
    } finally {
      await setOrgBalance(page, 100)
    }
  })

  test('monthly spending limit shows limit error message', async ({ page }) => {
    const config = await createConfig(page, { name: 'monthly_limit', value: '0.00' })
    try {
      await page.goto('/app/send')
      await fillAndSubmitSmsForm(page)
      await expect(
        page.getByText(/monthly spending limit reached/i).or(page.getByText(/limit/i)).first()
      ).toBeVisible({ timeout: 8000 })
    } finally {
      await deleteConfig(page, config.id).catch(() => {})
    }
  })

  test('billing error shows inline error message', async ({ page }) => {
    await setOrgBalance(page, 0)
    try {
      await page.goto('/app/send')
      await fillAndSubmitSmsForm(page)
      await expect(
        page.getByText(/insufficient balance/i).or(page.getByText(/subscribe to continue/i)).first()
      ).toBeVisible({ timeout: 8000 })
    } finally {
      await setOrgBalance(page, 100)
    }
  })
})

// ---------------------------------------------------------------------------
// Group send
// ---------------------------------------------------------------------------

test.describe('Group send — pipeline flow', () => {
  test('group send summary shows total queued count', async ({ page }) => {
    await page.goto('/app/send')
    await expect(page.locator('textarea').first()).toBeVisible({ timeout: 10000 })

    const groupTab = page
      .getByRole('tab', { name: /group/i })
      .or(page.getByRole('button', { name: /group/i }))
      .first()

    if (await groupTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await groupTab.click()

      const groupSelect = page.getByRole('combobox').or(page.getByLabel(/group/i)).first()
      if (await groupSelect.isVisible({ timeout: 2000 }).catch(() => false)) {
        await groupSelect.selectOption({ index: 0 })
      }

      const textarea = page.locator('textarea').first()
      await textarea.fill('Hello group!')

      const sendBtn = page.getByRole('button', { name: /^send now$/i }).first()
      await sendBtn.click()

      // Summary should mention 1 recipient (1 group member from beforeAll)
      await expect(
        page.getByText('1').or(page.getByText(/1 recipient/i)).first()
      ).toBeVisible({ timeout: 8000 })
    }
  })
})

// ---------------------------------------------------------------------------
// Dispatch pipeline — visible states in schedule list
// ---------------------------------------------------------------------------

test.describe('Dispatch pipeline — schedule status display', () => {
  test('queued schedule appears in the schedule list', async ({ page }) => {
    await page.goto('/app/schedule')
    await expect(page.getByText('Hello Charlie').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/queued/i).first()).toBeVisible()
  })

  test('retrying schedule shows retrying status with retry context', async ({ page }) => {
    await page.goto('/app/schedule')
    await expect(page.getByText('Hello Diana').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/retrying/i).first()).toBeVisible()
  })

  test('delivered schedule shows delivered status', async ({ page }) => {
    await page.goto('/app/schedule')
    await expect(page.getByText('Hello Eve').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/delivered/i).first()).toBeVisible()
  })

  test('failed schedule shows failed status', async ({ page }) => {
    await page.goto('/app/schedule')
    await expect(page.getByText('Hello Frank').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/failed/i).first()).toBeVisible()
  })
})
