import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderWithProviders, screen, loginAs } from '../../test/test-utils'

// Render the REAL AppLayout (../app/_layout). Two things need mocking:
//  1. @tanstack/react-router — createFileRoute passthrough, plus Link/Outlet/
//     useMatches so the navbar (which renders the UI Link → TanStack Link) and
//     the layout's <Outlet/> mount in jsdom without a real router.
//  2. @clerk/clerk-react — the global mock (test/setup.ts) is a static
//     org:admin; we re-mock useOrganization via vi.hoisted so `loginAs` can
//     switch between org:admin and org:member per test. AppLayout derives
//     isAdmin from useOrganization().membership?.role === 'org:admin'.
const { mockUseAuth, mockUseUser, mockUseOrganization } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
  mockUseUser: vi.fn(),
  mockUseOrganization: vi.fn(),
}))

vi.mock('@tanstack/react-router', () => ({
  createFileRoute: () => (options: Record<string, unknown>) => options,
  // Render router Links as plain anchors carrying their children (the nav
  // label), stripping router-only props so they don't leak onto the DOM <a>.
  Link: ({ children }: { children?: React.ReactNode } & Record<string, unknown>) => (
    <a>{children}</a>
  ),
  Outlet: () => <div data-testid="outlet">Outlet Content</div>,
  // No active route in the test → no nav item is marked current.
  useMatches: () => [],
}))

vi.mock('@clerk/clerk-react', () => ({
  useAuth: mockUseAuth,
  useUser: mockUseUser,
  useOrganization: mockUseOrganization,
  UserButton: () => <div data-testid="user-button" />,
}))

// Import the REAL exported layout after the mocks are set up.
import { AppLayout } from '../app/_layout'

const clerkMocks = {
  useAuth: mockUseAuth,
  useUser: mockUseUser,
  useOrganization: mockUseOrganization,
}

// Nav items gated behind adminOnly: true.
const ADMIN_NAV = ['Users', 'Billing']

describe('AppLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    loginAs(clerkMocks, 'org:admin')
  })

  describe('role-gated navigation', () => {
    it('shows admin-only nav (Users + Billing) to an org:admin', () => {
      loginAs(clerkMocks, 'org:admin')
      renderWithProviders(<AppLayout />)

      // NavbarItem renders a Catalyst UI Link → (mocked) TanStack <Link> as a
      // plain href-less <a>, which jsdom does not expose with role="link", so we
      // assert nav presence by the rendered label text instead.
      for (const label of ADMIN_NAV) {
        expect(screen.getByText(label)).toBeInTheDocument()
      }
    })

    it('hides admin-only nav (Users + Billing) from an org:member', () => {
      loginAs(clerkMocks, 'org:member')
      renderWithProviders(<AppLayout />)

      for (const label of ADMIN_NAV) {
        expect(screen.queryByText(label)).not.toBeInTheDocument()
      }
    })
  })

  describe('chrome', () => {
    it('renders the brand mark and the Clerk UserButton', () => {
      loginAs(clerkMocks, 'org:admin')
      renderWithProviders(<AppLayout />)

      expect(screen.getByText('App')).toBeInTheDocument()
      expect(screen.getByTestId('user-button')).toBeInTheDocument()
    })

    it('renders the routed Outlet for page content', () => {
      loginAs(clerkMocks, 'org:admin')
      renderWithProviders(<AppLayout />)

      expect(screen.getByTestId('outlet')).toBeInTheDocument()
    })
  })
})
