import { type Page } from '@playwright/test'
import { setupClerkTestingToken } from '@clerk/testing/playwright'
import fs from 'fs'

/**
 * Set up Clerk authentication for E2E tests.
 *
 * With explicit userId: performs a full sign-in (used from auth.setup.ts).
 *
 * Without userId: tries storageState first (fast path for page fixture contexts),
 * then falls back to a full sign-in using the userId from /tmp/e2e-state.json
 * (needed for browser.newPage() contexts in beforeAll which don't get storageState).
 *
 * Without CLERK_SECRET_KEY (e.g. local dev), auth is skipped entirely.
 */
export async function authenticatePage(page: Page, userId?: string) {
  const secretKey = process.env.CLERK_SECRET_KEY
  if (!secretKey) return

  await setupClerkTestingToken({ page })

  // orgId is set when reading from state file (fallback path) so we can
  // activate it after sign-in. When called with explicit userId (auth.setup.ts),
  // the caller handles org activation itself.
  let orgId: string | undefined

  if (!userId) {
    // Try fast path: storageState may have pre-loaded a Clerk session.
    if (page.url() === 'about:blank') {
      await page.goto('/', { timeout: 45_000 })
    }
    // Wait for Clerk to restore session from storageState (takes a moment to initialize)
    try {
      await page.waitForFunction(
        () => (window as any).Clerk?.user?.id != null,
        { timeout: 10_000 }
      )
      return // storageState had a valid session (org already active)
    } catch {
      // No stored session — fall through to full sign-in
    }

    // Fallback: browser.newPage() contexts don't get storageState.
    // Read userId + orgId from state file and do a full sign-in.
    const stateFile = '/tmp/e2e-state.json'
    if (fs.existsSync(stateFile)) {
      const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'))
      userId = state.clerkUserId
      orgId = state.clerkOrgId
    }
    if (!userId) return
  }

  // Full sign-in path

  // CI diagnostics — surface browser-side errors in test output
  page.on('console', msg => {
    if (msg.type() === 'error') console.log(`[PAGE] ${msg.text()}`)
  })
  page.on('pageerror', err => console.log(`[PAGE ERROR] ${err.message}`))

  // Create a one-time sign-in token via the Clerk Backend API (retry on 429)
  let ticket!: string
  for (let attempt = 0; attempt < 5; attempt++) {
    const response = await fetch('https://api.clerk.com/v1/sign_in_tokens', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${secretKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ user_id: userId }),
    })
    if (response.ok) {
      ticket = (await response.json()).token
      break
    }
    if (response.status === 429 && attempt < 4) {
      const wait = 2000 * Math.pow(2, attempt)
      console.log(`[AUTH] 429 on sign-in token (attempt ${attempt + 1}), retrying in ${wait}ms...`)
      await new Promise(r => setTimeout(r, wait))
      continue
    }
    throw new Error(`Clerk sign-in token failed: ${response.status} ${await response.text()}`)
  }

  // Navigate to app if not already there (explicit userId path from auth.setup.ts)
  if (page.url() === 'about:blank' || page.url().startsWith('data:')) {
    await page.goto('/', { timeout: 45_000 })
  }

  // Wait for Clerk JS to appear — retry once for Vite 504 cold-start failures
  try {
    await page.waitForFunction(
      () => (window as any).Clerk != null,
      { timeout: 30_000 }
    )
  } catch {
    console.log('[AUTH] Clerk not found after 30s, reloading once...')
    await page.goto('/', { timeout: 45_000 })
    await page.waitForFunction(
      () => (window as any).Clerk != null,
      { timeout: 30_000 }
    )
  }

  // Poll until sign-in succeeds — don't rely on Clerk.loaded (unreliable in CI).
  await page.evaluate(async (ticket: string) => {
    const deadline = Date.now() + 30_000
    while (Date.now() < deadline) {
      try {
        const clerk = (window as any).Clerk
        if (clerk?.client?.signIn?.create) {
          const result = await clerk.client.signIn.create({ strategy: 'ticket', ticket })
          if (result.status === 'complete') {
            await clerk.setActive({ session: result.createdSessionId })
            return
          }
        }
      } catch { /* Clerk not ready yet */ }
      await new Promise(r => setTimeout(r, 1000))
    }
    const c = (window as any).Clerk
    throw new Error(
      `Clerk sign-in failed after 30s. ` +
      `Clerk exists: ${!!c}, loaded: ${c?.loaded}, version: ${c?.version}`
    )
  }, ticket)

  await page.waitForFunction(
    () => (window as any).Clerk?.user?.id != null,
    { timeout: 10_000 }
  )

  // Activate org so JWTs include org claims (matches auth.setup.ts behavior).
  // Only needed for fallback sign-in; explicit userId callers handle this themselves.
  if (orgId) {
    await page.evaluate(async (oid: string) => {
      await (window as any).Clerk.setActive({ organization: oid })
    }, orgId)
    await page.waitForFunction(
      (oid: string) => (window as any).Clerk?.organization?.id === oid,
      orgId,
      { timeout: 10_000 }
    )
  }
}

// ---------------------------------------------------------------------------
// Authenticated API helpers — use the Clerk session token from the page
// ---------------------------------------------------------------------------

const API_BASE = process.env.E2E_API_BASE_URL || 'http://localhost:8000'

export async function getAuthToken(page: Page): Promise<string> {
  return page.evaluate(() => {
    const clerk = (window as any).Clerk
    if (!clerk?.session) throw new Error('No Clerk session')
    return clerk.session.getToken() as Promise<string>
  })
}

export async function apiRequest(
  page: Page,
  method: string,
  path: string,
  data?: object,
): Promise<any> {
  const token = await getAuthToken(page)
  const res = await page.request.fetch(`${API_BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: data ? JSON.stringify(data) : undefined,
  })
  if (!res.ok()) throw new Error(`${method} ${path} → ${res.status()}`)
  const text = await res.text()
  return text ? JSON.parse(text) : null
}

// Typed CRUD helpers
export const createConfig   = (p: Page, d: object) => apiRequest(p, 'POST', '/api/configs/', d)
export const deleteConfig   = (p: Page, id: number) => apiRequest(p, 'DELETE', `/api/configs/${id}/`)
export const setOrgBalance  = (p: Page, balance: number) =>
  apiRequest(p, 'PATCH', '/api/billing/test-set-balance/', { balance })
export const seedUsage      = (p: Page, d: { usage_type: string; amount: string; description?: string; backdate_days?: number }) =>
  apiRequest(p, 'POST', '/api/billing/test-seed-usage/', d)
export const generateInvoices = (p: Page) =>
  apiRequest(p, 'POST', '/api/billing/test-generate-invoices/', {})

/** Days to backdate so the resulting date lands on ~the 15th of the previous month. */
export function daysIntoPreviousMonth(): number {
  const now = new Date()
  return now.getDate() + 15
}
export const getBillingSummary = (p: Page) =>
  apiRequest(p, 'GET', '/api/billing/summary/')
export const linkBillingCustomer = (p: Page) =>
  apiRequest(p, 'POST', '/api/billing/test-link-billing-customer/', {})

// Clerk webhook simulation (TEST mode skips Svix signature verification)
// Used when Clerk webhooks can't reach the local Docker backend
async function postWebhook(body: object) {
  const url = `${API_BASE}/api/webhooks/clerk/`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10000),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Webhook POST failed (${res.status}): ${text}`)
  }
}

export async function simulateSubscriptionActive(orgId: string) {
  await postWebhook({
    type: 'subscription.updated',
    data: {
      payer: { organization_id: orgId },
      status: 'active',
      items: [{ status: 'active', plan: { amount: 30000, name: 'Professional' } }],
    },
  })
}

export async function simulateSubscriptionCanceled(orgId: string) {
  await postWebhook({
    type: 'subscription.updated',
    data: { payer: { organization_id: orgId }, status: 'canceled' },
  })
}
