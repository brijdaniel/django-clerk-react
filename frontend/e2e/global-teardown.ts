import { createClerkClient } from '@clerk/backend'
import fs from 'fs'

export default async function globalTeardown() {
  const stateFile = '/tmp/e2e-state.json'
  if (!fs.existsSync(stateFile)) return

  const secretKey = process.env.CLERK_SECRET_KEY
  if (!secretKey) return

  const { clerkOrgId, clerkUserId } = JSON.parse(fs.readFileSync(stateFile, 'utf8'))
  const clerk = createClerkClient({ secretKey })

  // Mirror the deletion into Django so the run doesn't leave orphaned org/user
  // rows (real Clerk would deliver these via Svix; TEST mode skips signature
  // verification). The cascade handlers soft-delete locally.
  const apiBase = process.env.E2E_API_BASE_URL || 'http://localhost:8000'
  const postWebhook = (body: object) =>
    fetch(`${apiBase}/api/webhooks/clerk/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
    }).catch(() => {})

  await Promise.all([
    clerkOrgId  ? postWebhook({ type: 'organization.deleted', data: { id: clerkOrgId } }) : Promise.resolve(),
    clerkUserId ? postWebhook({ type: 'user.deleted', data: { id: clerkUserId } }) : Promise.resolve(),
  ])

  // Clerk-side cleanup
  await Promise.all([
    clerkOrgId  ? clerk.organizations.deleteOrganization(clerkOrgId).catch(() => {})  : Promise.resolve(),
    clerkUserId ? clerk.users.deleteUser(clerkUserId).catch(() => {}) : Promise.resolve(),
  ])

  fs.unlinkSync(stateFile)
}
