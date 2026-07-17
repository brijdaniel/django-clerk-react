import { render, type RenderOptions } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import { ApiClient } from '../lib/helper'
import { ApiClientProvider } from '../lib/ApiClientProvider'
import type { ReactElement, ReactNode } from 'react'

// Create a mock ApiClient that uses the mock token
function createMockApiClient() {
  return new ApiClient(async () => 'mock-token')
}

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
        staleTime: Infinity,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

interface WrapperProps {
  children: ReactNode
}

function createWrapper() {
  const queryClient = createTestQueryClient()

  function Wrapper({ children }: WrapperProps) {
    return (
      <QueryClientProvider client={queryClient}>
        <ApiClientProvider>
          {children}
        </ApiClientProvider>
      </QueryClientProvider>
    )
  }

  return { Wrapper, queryClient }
}

export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) {
  const { Wrapper, queryClient } = createWrapper()
  const result = render(ui, { wrapper: Wrapper, ...options })
  return { ...result, queryClient }
}

// ---------------------------------------------------------------------------
// Clerk auth role helpers (#22)
//
// The global Clerk mock in test/setup.ts is static (always signed-in
// org:admin). To exercise org:member and signed-out flows, a test file
// re-mocks `@clerk/clerk-react` with vi.fn()s created via vi.hoisted, then
// uses `loginAs` to point those mocks at the desired role/state per test.
// ---------------------------------------------------------------------------

export type ClerkRole = 'org:admin' | 'org:member'

export interface ClerkAuthMocks {
  useAuth: ReturnType<typeof vi.fn>
  useUser: ReturnType<typeof vi.fn>
  useOrganization: ReturnType<typeof vi.fn>
}

export interface LoginAsOptions {
  /** When false, simulates a fully signed-out Clerk session. */
  signedIn?: boolean
  userId?: string
  orgId?: string
}

/**
 * Point a set of hoisted Clerk hook mocks at a given role (or a signed-out
 * state). Pass `null` as the role to simulate signed-out.
 *
 * Usage (inside a test file):
 *   const { mockUseAuth, mockUseUser, mockUseOrganization } = vi.hoisted(() => ({ ... }))
 *   vi.mock('@clerk/clerk-react', () => ({ useAuth: mockUseAuth, ... }))
 *   loginAs({ useAuth: mockUseAuth, useUser: mockUseUser, useOrganization: mockUseOrganization }, 'org:member')
 */
export function loginAs(
  mocks: ClerkAuthMocks,
  role: ClerkRole | null,
  options: LoginAsOptions = {},
) {
  const signedIn = options.signedIn ?? role !== null
  const userId = options.userId ?? 'user_test123'
  const orgId = options.orgId ?? 'org_test123'

  if (!signedIn) {
    mocks.useAuth.mockReturnValue({
      getToken: vi.fn().mockResolvedValue(null),
      isSignedIn: false,
      isLoaded: true,
      userId: null,
      orgId: null,
    })
    mocks.useUser.mockReturnValue({ user: null, isLoaded: true, isSignedIn: false })
    mocks.useOrganization.mockReturnValue({ organization: null, membership: null, isLoaded: true })
    return
  }

  mocks.useAuth.mockReturnValue({
    getToken: vi.fn().mockResolvedValue('mock-token'),
    isSignedIn: true,
    isLoaded: true,
    userId,
    orgId,
  })
  mocks.useUser.mockReturnValue({
    user: { id: userId, firstName: 'Test', lastName: 'User' },
    isLoaded: true,
    isSignedIn: true,
  })
  mocks.useOrganization.mockReturnValue({
    organization: { id: orgId, name: 'Test Org' },
    membership: { role },
    isLoaded: true,
  })
}

// Re-export everything from testing-library
export * from '@testing-library/react'
export { default as userEvent } from '@testing-library/user-event'

// Export utilities
export { createWrapper, createTestQueryClient, createMockApiClient }
