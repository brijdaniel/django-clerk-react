import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../test/test-utils'

// TASK B4 — Render the REAL index route component (src/routes/index.tsx) and
// exercise its Clerk org auto-activation + redirect behaviour.
//
// The component only touches React Query indirectly (none of its hooks hit the
// ApiClient), so a plain render() is sufficient here. It does, however, call
// useNavigate() (router) and useOrganization()/useOrganizationList() (Clerk),
// so both modules are mocked locally with hoisted vi.fn()s we assert on.

// --- @tanstack/react-router mock ----------------------------------------------
const mockNavigate = vi.fn()
vi.mock('@tanstack/react-router', () => ({
  createFileRoute: () => (options: Record<string, unknown>) => options,
  useNavigate: () => mockNavigate,
  Link: ({ children }: { children?: React.ReactNode } & Record<string, unknown>) => <a>{children}</a>,
  Outlet: () => null,
}))

// --- @clerk/clerk-react mock -------------------------------------------------
// The global mock in test/setup.ts is static; we re-mock here so each test can
// drive the org-activation state (active org present/absent, memberships,
// isLoaded) and assert on setActive.
const { mockUseOrganization, mockUseOrganizationList } = vi.hoisted(() => ({
  mockUseOrganization: vi.fn(),
  mockUseOrganizationList: vi.fn(),
}))

vi.mock('@clerk/clerk-react', () => ({
  useOrganization: mockUseOrganization,
  useOrganizationList: mockUseOrganizationList,
}))

import { IndexPage } from '../index'

/** Build a membership entry shaped like Clerk's userMemberships.data items. */
function membership(orgId: string) {
  return { organization: { id: orgId } }
}

/** Default Clerk state: loaded, no active org, with a list of memberships. */
function setClerkState({
  organization = null,
  memberships = [] as ReturnType<typeof membership>[],
  isLoaded = true,
  setActive = vi.fn(),
}: {
  organization?: { id: string } | null
  memberships?: ReturnType<typeof membership>[]
  isLoaded?: boolean
  setActive?: ReturnType<typeof vi.fn>
} = {}) {
  mockUseOrganization.mockReturnValue({ organization })
  mockUseOrganizationList.mockReturnValue({
    userMemberships: { data: memberships },
    setActive,
    isLoaded,
  })
  return setActive
}

describe('IndexPage — org auto-activation + redirect (B4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the loading splash', () => {
    setClerkState()
    render(<IndexPage />)
    expect(screen.getByText('Loading application...')).toBeInTheDocument()
  })

  it('auto-activates the first membership org when none is active', async () => {
    const setActive = setClerkState({
      organization: null,
      memberships: [membership('org_first'), membership('org_second')],
      isLoaded: true,
    })

    render(<IndexPage />)

    await waitFor(() => {
      expect(setActive).toHaveBeenCalledTimes(1)
    })
    // Activates the FIRST membership's organization id.
    expect(setActive).toHaveBeenCalledWith({ organization: 'org_first' })
  })

  it('does NOT activate an org when one is already active', async () => {
    const setActive = setClerkState({
      organization: { id: 'org_active' },
      memberships: [membership('org_first')],
      isLoaded: true,
    })

    render(<IndexPage />)

    // Give effects a chance to run before asserting the no-op.
    await waitFor(() => expect(mockNavigate).toHaveBeenCalled())
    expect(setActive).not.toHaveBeenCalled()
  })

  it('does NOT activate while Clerk org list is still loading', async () => {
    const setActive = setClerkState({
      organization: null,
      memberships: [membership('org_first')],
      isLoaded: false,
    })

    render(<IndexPage />)

    await waitFor(() => expect(mockNavigate).toHaveBeenCalled())
    expect(setActive).not.toHaveBeenCalled()
  })

  it('does NOT activate when the user has no memberships', async () => {
    const setActive = setClerkState({
      organization: null,
      memberships: [],
      isLoaded: true,
    })

    render(<IndexPage />)

    await waitFor(() => expect(mockNavigate).toHaveBeenCalled())
    expect(setActive).not.toHaveBeenCalled()
  })

  it('redirects to /app/users on mount', async () => {
    setClerkState()
    render(<IndexPage />)

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith({ to: '/app/users' })
    })
  })

  it('still redirects to /app/users even when an org is already active', async () => {
    setClerkState({ organization: { id: 'org_active' }, memberships: [], isLoaded: true })
    render(<IndexPage />)

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith({ to: '/app/users' })
    })
  })
})
