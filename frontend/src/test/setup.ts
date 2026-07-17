import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { server } from './handlers'

// Mock IntersectionObserver (not implemented in jsdom). Components that use
// useInfiniteScroll construct one in an effect; without this they throw.
// Per-file stubs (e.g. useInfiniteScroll.test.tsx) override this as needed.
const MockIntersectionObserver = class {
  root = null
  rootMargin = ''
  thresholds = []
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  takeRecords = vi.fn(() => [])
}
vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)

// Mock ResizeObserver (not implemented in jsdom). Headless UI's Combobox
// constructs one during open/close transitions; without this it throws an
// async "ResizeObserver is not defined" that vitest reports as an unhandled
// error and fails the run even when every test passes.
const MockResizeObserver = class {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
vi.stubGlobal('ResizeObserver', MockResizeObserver)

// Mock window.matchMedia (not available in jsdom)
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
  })),
})

// Mock environment variables
vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000')
vi.stubEnv('VITE_LOG_LEVEL', 'error')
vi.stubEnv('VITE_CLERK_PUBLISHABLE_KEY', 'pk_test_mock')

// Mock Clerk
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
  useOrganization: () => ({
    organization: { id: 'org_test123', name: 'Test Org' },
    isLoaded: true,
  }),
  useOrganizationList: () => ({
    organizationList: [{ organization: { id: 'org_test123', name: 'Test Org' } }],
    isLoaded: true,
    setActive: vi.fn(),
  }),
  ClerkProvider: ({ children }: { children: React.ReactNode }) => children,
  SignedIn: ({ children }: { children: React.ReactNode }) => children,
  SignedOut: () => null,
  UserButton: () => null,
}))

// Setup MSW
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())
