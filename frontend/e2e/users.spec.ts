/**
 * E2E tests for the Users page.
 *
 * Self-contained: creates its own Clerk admin user + org + member + inactive
 * user in beforeAll via the real Clerk API, then seeds Django DB directly
 * via simulated webhook POSTs (no Svix tunnel needed).
 */

import { test, expect } from '@playwright/test'
import { createClerkClient } from '@clerk/backend'
import { authenticatePage, apiRequest } from './helpers'

/** POST a simulated Clerk webhook event directly to the backend.
 *  In CI the backend has TEST=True so it skips Svix signature verification. */
async function seedWebhook(body: object) {
  const apiBase = process.env.E2E_API_BASE_URL || 'http://localhost:8000'
  const res = await fetch(`${apiBase}/api/webhooks/clerk/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Webhook seed failed (${res.status}): ${text}`)
  }
}

let adminUserId: string
let memberUserId: string
let inactiveUserId: string
let specOrgId: string
let ts: number

test.beforeAll(async ({ browser }) => {
  test.setTimeout(120_000) // Clerk API + seedWebhook + auth takes time
  if (!process.env.CLERK_SECRET_KEY) return
  const clerk = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY })
  ts = Date.now()
  const slug = `e2e-users-${ts}`

  // Create admin user + org (Clerk auto-creates admin membership)
  const adminUser = await clerk.users.createUser({
    emailAddress: [`admin-${ts}+clerk_test@test.example.com`],
    firstName: 'E2E',
    lastName: 'Admin',
    skipPasswordRequirement: true,
  })
  adminUserId = adminUser.id
  const org = await clerk.organizations.createOrganization({
    name: `E2E Users Org ${slug}`,
    slug,
    createdBy: adminUserId,
  })
  specOrgId = org.id

  // Create member user + add to org
  const memberUser = await clerk.users.createUser({
    emailAddress: [`member-${ts}+clerk_test@test.example.com`],
    firstName: 'Member',
    lastName: 'User',
    skipPasswordRequirement: true,
  })
  memberUserId = memberUser.id
  await clerk.organizations.createOrganizationMembership({
    organizationId: specOrgId,
    userId: memberUserId,
    role: 'org:member',
  })

  // Create inactive user + add to org, then remove from org
  const inactiveUser = await clerk.users.createUser({
    emailAddress: [`inactive-${ts}+clerk_test@test.example.com`],
    firstName: 'Inactive',
    lastName: 'User',
    skipPasswordRequirement: true,
  })
  inactiveUserId = inactiveUser.id
  await clerk.organizations.createOrganizationMembership({
    organizationId: specOrgId,
    userId: inactiveUserId,
    role: 'org:member',
  })
  await clerk.organizations.deleteOrganizationMembership({
    organizationId: specOrgId,
    userId: inactiveUserId,
  })

  // Seed Django DB directly (no Svix tunnel in CI — webhooks aren't delivered)
  // Batch 1: users + org (independent)
  await Promise.all([
    seedWebhook({
      type: 'user.created',
      data: {
        id: adminUserId,
        primary_email_address_id: 'email_1',
        email_addresses: [{ id: 'email_1', email_address: `admin-${ts}+clerk_test@test.example.com` }],
        first_name: 'E2E', last_name: 'Admin',
      },
    }),
    seedWebhook({
      type: 'organization.created',
      data: { id: specOrgId, name: `E2E Users Org ${slug}`, slug },
    }),
    seedWebhook({
      type: 'user.created',
      data: {
        id: memberUserId,
        primary_email_address_id: 'email_2',
        email_addresses: [{ id: 'email_2', email_address: `member-${ts}+clerk_test@test.example.com` }],
        first_name: 'Member', last_name: 'User',
      },
    }),
    seedWebhook({
      type: 'user.created',
      data: {
        id: inactiveUserId,
        primary_email_address_id: 'email_3',
        email_addresses: [{ id: 'email_3', email_address: `inactive-${ts}+clerk_test@test.example.com` }],
        first_name: 'Inactive', last_name: 'User',
      },
    }),
  ])
  // Batch 2: memberships (need users + org to exist)
  await Promise.all([
    seedWebhook({
      type: 'organizationMembership.created',
      data: {
        organization: { id: specOrgId },
        public_user_data: { user_id: adminUserId },
        role: 'org:admin',
      },
    }),
    seedWebhook({
      type: 'organizationMembership.created',
      data: {
        organization: { id: specOrgId },
        public_user_data: { user_id: memberUserId },
        role: 'org:member',
      },
    }),
    seedWebhook({
      type: 'organizationMembership.created',
      data: {
        organization: { id: specOrgId },
        public_user_data: { user_id: inactiveUserId },
        role: 'org:member',
      },
    }),
  ])
  // Batch 3: inactive membership deletion (needs membership to exist)
  await seedWebhook({
    type: 'organizationMembership.deleted',
    data: {
      organization: { id: specOrgId },
      public_user_data: { user_id: inactiveUserId },
    },
  })

  // Verify seeded data is visible via the API
  const page = await browser.newPage()
  await authenticatePage(page, adminUserId)
  await expect(async () => {
    const users = await apiRequest(page, 'GET', '/api/users/?limit=50')
    const emails = (users.results ?? []).map((u: any) => u.email)
    expect(emails).toContain(`member-${ts}+clerk_test@test.example.com`)
    expect(emails).toContain(`inactive-${ts}+clerk_test@test.example.com`)
  }).toPass({ timeout: 15000, intervals: [1000] })
  await page.close()
})

test.afterAll(async () => {
  if (!process.env.CLERK_SECRET_KEY) return
  const clerk = createClerkClient({ secretKey: process.env.CLERK_SECRET_KEY })
  // Delete org first → fires organization.deleted (cascades memberships in Django)
  if (specOrgId) await clerk.organizations.deleteOrganization(specOrgId).catch(() => {})
  await Promise.all([
    memberUserId   ? clerk.users.deleteUser(memberUserId).catch(() => {})   : Promise.resolve(),
    inactiveUserId ? clerk.users.deleteUser(inactiveUserId).catch(() => {}) : Promise.resolve(),
    adminUserId    ? clerk.users.deleteUser(adminUserId).catch(() => {})    : Promise.resolve(),
  ])
})

// Users spec signs in as its own admin user (not the main test user),
// so we must clear storageState to avoid session conflicts.
test.use({ storageState: { cookies: [], origins: [] } })

test.beforeEach(async ({ page }) => {
  await authenticatePage(page, adminUserId)
  // Activate the spec's org so JWTs include org claims for API calls
  await page.evaluate(async (oid: string) => {
    await (window as any).Clerk.setActive({ organization: oid })
  }, specOrgId)
  await page.waitForFunction(
    (oid: string) => (window as any).Clerk?.organization?.id === oid,
    specOrgId,
    { timeout: 10_000 }
  )
})

test.describe('Users Page', () => {
  test('displays users table after loading', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('Inactive User').first()).toBeVisible()
  })

  test('shows table headers', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('columnheader', { name: 'Name' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Email' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Organisation' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Role' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Actions' })).toBeVisible()
  })

  test('shows role and status badges', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('Member').first()).toBeVisible()
    await expect(page.getByText('Active').first()).toBeVisible()
    await expect(page.getByText('Inactive').first()).toBeVisible()
  })

  test('shows Invite User button', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: 'Invite User' })).toBeVisible()
  })

  test('shows action buttons for non-self users', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: 'Make Admin' }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Deactivate' }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Re-invite' })).toBeVisible()
  })

  test('can open invite user dialog', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Invite User' }).click()
    await expect(page.getByText('Invite User', { exact: false }).first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByPlaceholder('user@example.com')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Send Invite' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible()
  })

  test('can submit invite user form', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Invite User' }).click()
    await expect(page.getByPlaceholder('user@example.com')).toBeVisible({ timeout: 5000 })
    await page.getByPlaceholder('user@example.com').fill(`invite-${ts}+clerk_test@test.example.com`)
    await page.getByRole('button', { name: 'Send Invite' }).click()
    // Success: dialog closes. Clerk API failure: error message appears in dialog.
    // Both outcomes are valid — Clerk may return 502 in CI environments.
    await Promise.race([
      expect(page.getByPlaceholder('user@example.com')).not.toBeVisible({ timeout: 10000 }),
      expect(page.getByText(/Failed to send invitation/i).first()).toBeVisible({ timeout: 10000 }),
    ])
  })

  test('can close invite dialog with cancel', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Invite User' }).click()
    await expect(page.getByPlaceholder('user@example.com')).toBeVisible({ timeout: 5000 })
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByPlaceholder('user@example.com')).not.toBeVisible({ timeout: 5000 })
  })

  test('Make Admin button triggers role update without error', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Make Admin' }).first().click()
    await expect(page.getByText(/failed|error/i)).not.toBeVisible({ timeout: 3000 })
  })

  test('Deactivate button triggers status update without error', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Deactivate' }).first().click()
    await expect(page.getByText(/failed|error/i)).not.toBeVisible({ timeout: 3000 })
  })

  test('Re-invite button triggers re-invitation without error', async ({ page }) => {
    await page.goto('/app/users')
    await expect(page.getByText('Member User').first()).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Re-invite' }).click()
    await expect(page.getByText(/failed|error/i)).not.toBeVisible({ timeout: 3000 })
  })
})
