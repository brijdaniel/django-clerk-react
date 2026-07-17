import { clerkSetup } from '@clerk/testing/playwright'
import { createClerkClient } from '@clerk/backend'
import { type FullConfig } from '@playwright/test'
import fs from 'fs'

export default async function globalSetup(_config: FullConfig) {
  const secretKey = process.env.CLERK_SECRET_KEY

  if (!secretKey) {
    // Local dev without credentials — skip real setup.
    // Tests will skip auth (authenticatePage returns early when secretKey is missing).
    return
  }

  await clerkSetup()

  const clerk = createClerkClient({ secretKey })
  const ts    = Date.now()

  // 1. Create a fresh Clerk user for this CI run
  const user = await clerk.users.createUser({
    emailAddress: [`e2e-${ts}+clerk_test@test.example.com`],
    firstName: 'E2E',
    lastName: 'Test',
    skipPasswordRequirement: true,
  })

  // 2. Create a fresh Clerk org (user becomes admin member automatically)
  const slug = `e2e-${ts}`
  const org  = await clerk.organizations.createOrganization({
    name: `E2E Test Org ${slug}`,
    slug,
    createdBy: user.id,
  })

  // Persist IDs for auth.setup.ts and global-teardown
  const email = `e2e-${ts}+clerk_test@test.example.com`
  fs.writeFileSync('/tmp/e2e-state.json', JSON.stringify({
    clerkUserId: user.id,
    clerkOrgId: org.id,
    userEmail: email,
  }))

  // Seed Django DB by posting simulated webhook events directly to the backend.
  // In TEST mode the backend skips Svix signature verification.
  const apiBase = process.env.E2E_API_BASE_URL || 'http://localhost:8000'
  const webhookUrl = `${apiBase}/api/webhooks/clerk/`

  // Wait for backend to be healthy before seeding (handles Azure restart delays)
  const healthUrl = `${apiBase}/api/health/`
  console.log(`Waiting for backend at ${healthUrl}...`)
  for (let i = 1; i <= 30; i++) {
    try {
      const res = await fetch(healthUrl, { signal: AbortSignal.timeout(5000) })
      if (res.ok) {
        console.log(`Backend healthy after ${i} attempt(s).`)
        break
      }
    } catch {
      // connection refused or timeout — expected during startup
    }
    if (i === 30) throw new Error('Backend did not become healthy within 150s')
    await new Promise(r => setTimeout(r, 5000))
  }

  const post = async (body: object, retries = 3) => {
    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const res = await fetch(webhookUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(10000),
        })
        if (!res.ok) {
          const text = await res.text()
          throw new Error(`Webhook seed failed (${res.status}): ${text}`)
        }
        return
      } catch (err) {
        if (attempt === retries) throw err
        console.log(`Webhook POST failed (attempt ${attempt}/${retries}), retrying in 3s...`)
        await new Promise(r => setTimeout(r, 3000))
      }
    }
  }

  // Seed user + org in parallel, then membership (which references both)
  await Promise.all([
    post({
      type: 'user.created',
      data: {
        id: user.id,
        primary_email_address_id: 'email_1',
        email_addresses: [{ id: 'email_1', email_address: email }],
        first_name: 'E2E',
        last_name: 'Test',
      },
    }),
    post({
      type: 'organization.created',
      data: { id: org.id, name: `E2E Test Org ${slug}`, slug },
    }),
  ])

  await post({
    type: 'organizationMembership.created',
    data: {
      organization: { id: org.id },
      public_user_data: { user_id: user.id },
      role: 'org:admin',
    },
  })
}
