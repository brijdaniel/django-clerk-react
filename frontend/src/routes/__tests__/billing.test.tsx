import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { renderWithProviders, screen, waitFor, userEvent } from '../../test/test-utils'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/handlers'
import { createBillingSummary, createCreditTransaction } from '../../test/factories'
import { Suspense } from 'react'

// Mock TanStack Router — capture route options so errorComponent can be tested
// Use vi.hoisted so capturedBillingRouteOptions is available inside the hoisted vi.mock factory
const { capturedBillingRouteOptions } = vi.hoisted(() => ({
  capturedBillingRouteOptions: {} as Record<string, unknown>,
}))
vi.mock('@tanstack/react-router', () => ({
  createFileRoute: () => (options: Record<string, unknown>) => {
    Object.assign(capturedBillingRouteOptions, options)
    return options
  },
}))

// Use vi.hoisted so mocks are available inside vi.mock (which is hoisted)
const { mockUseOrganization, mockUseSubscription } = vi.hoisted(() => ({
  mockUseOrganization: vi.fn().mockReturnValue({ membership: { role: 'org:admin' }, isLoaded: true }),
  mockUseSubscription: vi.fn().mockReturnValue({ data: null, isLoading: false }),
}))

// Override Clerk mock to include admin membership with mutable useOrganization
vi.mock('@clerk/clerk-react', () => ({
  useAuth: () => ({
    getToken: vi.fn().mockResolvedValue('mock-token'),
    isSignedIn: true,
    isLoaded: true,
    userId: 'user_test123',
    orgId: 'org_test123',
  }),
  useUser: () => ({
    user: { id: 'user_test123', firstName: 'Test', lastName: 'User' },
    isLoaded: true,
    isSignedIn: true,
  }),
  useOrganization: mockUseOrganization,
  useOrganizationList: () => ({
    organizationList: [{ organization: { id: 'org_test123', name: 'Test Org' } }],
    isLoaded: true,
    setActive: vi.fn(),
  }),
  ClerkProvider: ({ children }: { children: React.ReactNode }) => children,
  SignedIn: ({ children }: { children: React.ReactNode }) => children,
  SignedOut: () => null,
  UserButton: () => null,
  PricingTable: ({ for: forType }: { for?: string }) => <div data-testid="pricing-table" data-for={forType}>PricingTable</div>,
}))

vi.mock('@clerk/clerk-react/experimental', () => ({
  useSubscription: mockUseSubscription,
  SubscriptionDetailsButton: ({ children }: { children: React.ReactNode }) => <div data-testid="subscription-details">{children}</div>,
}))

vi.mock('../../ui/dialog', () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) => open ? <div data-testid="plan-dialog">{children}</div> : null,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogBody: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogActions: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

// Import billing route so createFileRoute is called and capturedBillingRouteOptions
// is populated, and import the REAL exported BillingContent component (#6).
import { BillingContent } from '../app/_layout.billing'

// Render the REAL BillingContent inside a Suspense boundary (it uses useInfiniteQuery
// internally but the route's RouteComponent wraps it in Suspense in production).
function BillingWithSuspense() {
  return (
    <Suspense fallback={<div>Loading billing...</div>}>
      <BillingContent />
    </Suspense>
  )
}

describe('BillingLayout', () => {
  // Default to admin for all tests
  afterEach(() => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:admin' }, isLoaded: true })
    mockUseSubscription.mockReturnValue({ data: null, isLoading: false })
  })

  beforeEach(() => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:admin' }, isLoaded: true })
    mockUseSubscription.mockReturnValue({ data: null, isLoading: false })
  })

  it('renders prepaid balance', async () => {
    server.use(
      http.get('http://localhost:8000/api/billing/summary/', () =>
        HttpResponse.json(createBillingSummary({ billing_mode: 'prepaid', balance: '8.50' }))
      )
    )

    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText('Prepaid balance')).toBeInTheDocument()
    })
    expect(screen.getByText('$8.50')).toBeInTheDocument()
  })

  it('renders subscribed billing mode', async () => {
    server.use(
      http.get('http://localhost:8000/api/billing/summary/', () =>
        HttpResponse.json(createBillingSummary({ billing_mode: 'subscribed' }))
      )
    )

    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText('Subscribed')).toBeInTheDocument()
    })
  })

  it('displays monthly spend', async () => {
    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText('Monthly spend')).toBeInTheDocument()
    })
    expect(screen.getByText('$1.50')).toBeInTheDocument()
  })

  it('displays monthly limit when set', async () => {
    server.use(
      http.get('http://localhost:8000/api/billing/summary/', () =>
        HttpResponse.json(createBillingSummary({ monthly_limit: '25.00' }))
      )
    )

    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText('/ $25.00 limit')).toBeInTheDocument()
    })
  })

  it('shows no-limit when monthly_limit is null', async () => {
    server.use(
      http.get('http://localhost:8000/api/billing/summary/', () =>
        HttpResponse.json(createBillingSummary({ monthly_limit: null }))
      )
    )

    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText('no limit set')).toBeInTheDocument()
    })
  })

  it('renders usage by type', async () => {
    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText('Usage:')).toBeInTheDocument()
    })
    // API_CALL: $1.00 ($0.10/unit) — text is split across nodes, so match fragments.
    expect(screen.getByText('API_CALL')).toBeInTheDocument()
    expect(screen.getByText(/\$1\.00 \(\$0\.10\/unit\)/)).toBeInTheDocument()
    expect(screen.getByText('REPORT')).toBeInTheDocument()
    expect(screen.getByText(/\$0\.50 \(\$0\.50\/unit\)/)).toBeInTheDocument()
  })

  it('renders transaction history', async () => {
    server.use(
      http.get('http://localhost:8000/api/billing/summary/', () =>
        HttpResponse.json(
          createBillingSummary({
            results: [
              createCreditTransaction({ id: 1, transaction_type: 'grant', amount: '10.00', balance_after: '10.00' }),
              createCreditTransaction({ id: 2, transaction_type: 'deduct', amount: '0.10', usage_type: 'api_call', balance_after: '9.90' }),
            ],
            pagination: { total: 2, page: 1, limit: 50, totalPages: 1, hasNext: false, hasPrev: false },
          })
        )
      )
    )

    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText('grant')).toBeInTheDocument()
    })
    expect(screen.getByText('deduct')).toBeInTheDocument()
    // tx2 amount $0.10 is unique (tx1's $10.00 also appears in the balance-after column).
    expect(screen.getByText('$0.10')).toBeInTheDocument()
    expect(screen.getByText(/Showing 2 of 2/)).toBeInTheDocument()
  })

  it('shows access denied for non-admin', async () => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' }, isLoaded: true })

    renderWithProviders(<BillingWithSuspense />)

    await waitFor(() => {
      expect(screen.getByText(/Access restricted to organisation admins/i)).toBeInTheDocument()
    })
  })

  it('renders past_due billing mode in the UI', async () => {
    server.use(
      http.get('http://localhost:8000/api/billing/summary/', () =>
        HttpResponse.json(createBillingSummary({ billing_mode: 'past_due' }))
      )
    )
    renderWithProviders(<BillingWithSuspense />)
    await waitFor(() => {
      expect(screen.getAllByText('Past Due').length).toBeGreaterThan(0)
    })
  })

  it('renders error component with message and retry button', () => {
    // capturedBillingRouteOptions is populated when _layout.billing is imported above
    const ErrorComponent = capturedBillingRouteOptions.errorComponent as React.ComponentType<{
      error: Error
      info: { componentStack: string }
      reset: () => void
    }>
    renderWithProviders(
      <ErrorComponent
        error={new Error('Failed to load billing.')}
        info={{ componentStack: '' }}
        reset={() => {}}
      />
    )
    expect(screen.getByText('Failed to load billing.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})

describe('past_due billing mode', () => {
  beforeEach(() => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:admin' }, isLoaded: true })
    server.use(
      http.get('http://localhost:8000/api/billing/summary/', () =>
        HttpResponse.json(createBillingSummary({ billing_mode: 'past_due' }))
      )
    )
  })

  it('shows Past Due badge in the UI', async () => {
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    const badges = await screen.findAllByText('Past Due')
    expect(badges.length).toBeGreaterThan(0)
  })

  it('shows past due warning banner', async () => {
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    await screen.findByText(/All billable usage is currently blocked/i)
  })

  it('does not show prepaid balance when past due', async () => {
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    await screen.findAllByText('Past Due')
    expect(screen.queryByText(/Prepaid balance/i)).not.toBeInTheDocument()
  })
})

describe('Manage Plan dialog', () => {
  beforeEach(() => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:admin' }, isLoaded: true })
  })

  afterEach(() => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:admin' }, isLoaded: true })
    mockUseSubscription.mockReturnValue({ data: null, isLoading: false })
  })

  it('shows Subscribe button for prepaid org', async () => {
    mockUseSubscription.mockReturnValue({
      data: { status: 'active', subscriptionItems: [{ status: 'active', plan: { name: 'Free', fee: { amount: 0 } } }] },
      isLoading: false,
    })
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Subscribe' })).toBeInTheDocument()
    })
    expect(screen.getByText('Free')).toBeInTheDocument()
  })

  it('shows Professional label for org on paid plan', async () => {
    mockUseSubscription.mockReturnValue({
      data: { status: 'active', subscriptionItems: [
        { status: 'active', plan: { name: 'Free', fee: { amount: 0 } } },
        { status: 'active', plan: { name: 'Professional', fee: { amount: 2999 } } },
      ]},
      isLoading: false,
    })
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    await waitFor(() => {
      expect(screen.getByText('Professional')).toBeInTheDocument()
    })
  })

  it('opens dialog with PricingTable when Subscribe is clicked', async () => {
    const user = userEvent.setup()
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Subscribe' })).toBeInTheDocument()
    })
    expect(screen.queryByTestId('plan-dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Subscribe' }))
    expect(screen.getByTestId('plan-dialog')).toBeInTheDocument()
    expect(screen.getByTestId('pricing-table')).toBeInTheDocument()
    expect(screen.getByTestId('pricing-table')).toHaveAttribute('data-for', 'organization')
  })

  it('does not show Manage Plan for non-admin users', async () => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' }, isLoaded: true })
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    await waitFor(() => {
      expect(screen.getByText(/Access restricted/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Subscribe' })).not.toBeInTheDocument()
  })

  it('shows Buy Credits button for prepaid org', async () => {
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Buy Credits' })).toBeInTheDocument()
    })
  })

  it('does not show Buy Credits button for subscribed org', async () => {
    server.use(
      http.get('http://localhost:8000/api/billing/summary/', () =>
        HttpResponse.json(createBillingSummary({ billing_mode: 'subscribed' }))
      )
    )
    mockUseSubscription.mockReturnValue({
      data: { status: 'active', subscriptionItems: [{ status: 'active', plan: { name: 'Professional', fee: { amount: 2999 } } }] },
      isLoading: false,
    })
    const RouteComp = capturedBillingRouteOptions.component as React.ComponentType
    renderWithProviders(<RouteComp />)
    await waitFor(() => {
      expect(screen.getByText('Invoices')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Buy Credits' })).not.toBeInTheDocument()
  })
})
