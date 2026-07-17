import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderWithProviders, screen, waitFor, loginAs } from '../../test/test-utils'
import { Suspense } from 'react'

// #22 — The global Clerk mock (test/setup.ts) is a static signed-in org:admin.
// Here we re-mock @clerk/clerk-react with hoisted vi.fn()s so `loginAs` can point
// them at org:member or a signed-out state per test, then exercise an admin-only
// route (billing) and a signed-out branch.
const { mockUseAuth, mockUseUser, mockUseOrganization, mockUseSubscription } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
  mockUseUser: vi.fn(),
  mockUseOrganization: vi.fn(),
  mockUseSubscription: vi.fn().mockReturnValue({ data: null, isLoading: false }),
}))

vi.mock('@tanstack/react-router', () => ({
  createFileRoute: () => (options: Record<string, unknown>) => options,
}))

vi.mock('@clerk/clerk-react', () => ({
  useAuth: mockUseAuth,
  useUser: mockUseUser,
  useOrganization: mockUseOrganization,
  useOrganizationList: () => ({
    organizationList: [{ organization: { id: 'org_test123', name: 'Test Org' } }],
    isLoaded: true,
    setActive: vi.fn(),
  }),
  ClerkProvider: ({ children }: { children: React.ReactNode }) => children,
  // SignedIn/SignedOut honor the mocked auth state so the signed-out branch renders.
  SignedIn: ({ children }: { children: React.ReactNode }) =>
    mockUseAuth().isSignedIn ? <>{children}</> : null,
  SignedOut: ({ children }: { children: React.ReactNode }) =>
    mockUseAuth().isSignedIn ? null : <>{children}</>,
  UserButton: () => null,
  PricingTable: () => <div data-testid="pricing-table">PricingTable</div>,
}))

vi.mock('@clerk/clerk-react/experimental', () => ({
  useSubscription: mockUseSubscription,
  SubscriptionDetailsButton: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

const clerkMocks = { useAuth: mockUseAuth, useUser: mockUseUser, useOrganization: mockUseOrganization }

import { BillingContent } from '../app/_layout.billing'
import { useAuth } from '@clerk/clerk-react'

function BillingWithSuspense() {
  return (
    <Suspense fallback={<div>Loading billing...</div>}>
      <BillingContent />
    </Suspense>
  )
}

// A minimal signed-in/out guard that mirrors the app's pattern of branching on
// Clerk's session state.
function AuthGate() {
  const { isSignedIn } = useAuth()
  return isSignedIn ? <div>Welcome back</div> : <div>Please sign in</div>
}

describe('Clerk role-gated access (#22)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseSubscription.mockReturnValue({ data: null, isLoading: false })
    // Default to admin signed-in; individual tests override via loginAs.
    loginAs(clerkMocks, 'org:admin')
  })

  it('shows billing details to an org:admin', async () => {
    loginAs(clerkMocks, 'org:admin')
    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText('Billing')).toBeInTheDocument()
    })
    expect(screen.queryByText(/Access restricted/i)).not.toBeInTheDocument()
  })

  it('blocks an org:member from the billing route with an access-denied message', async () => {
    loginAs(clerkMocks, 'org:member')
    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText(/Access restricted to organisation admins/i)).toBeInTheDocument()
    })
    // None of the admin-only controls should be present.
    expect(screen.queryByRole('button', { name: 'Buy Credits' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Subscribe' })).not.toBeInTheDocument()
  })

  it('treats a signed-out session as non-admin on the billing route', async () => {
    loginAs(clerkMocks, null) // signed out
    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText(/Access restricted to organisation admins/i)).toBeInTheDocument()
    })
  })

  it('renders the signed-out branch of an auth gate when signed out', () => {
    loginAs(clerkMocks, null)
    renderWithProviders(<AuthGate />)

    expect(screen.getByText('Please sign in')).toBeInTheDocument()
    expect(screen.queryByText('Welcome back')).not.toBeInTheDocument()
  })

  it('renders the signed-in branch of an auth gate when signed in', () => {
    loginAs(clerkMocks, 'org:member')
    renderWithProviders(<AuthGate />)

    expect(screen.getByText('Welcome back')).toBeInTheDocument()
  })
})
