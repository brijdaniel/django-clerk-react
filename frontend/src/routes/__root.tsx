import { createRootRouteWithContext, Outlet, useRouterState } from '@tanstack/react-router'
import { SignedIn, SignedOut, SignIn } from '@clerk/clerk-react'
import * as Sentry from '@sentry/react'
import type { QueryClient } from '@tanstack/react-query'

// Bypass Clerk auth in local E2E test mode. This variable is set in frontend/.env
// (local dev only) and is never present in production builds.
const E2E_TEST_MODE = import.meta.env.VITE_E2E_TEST_MODE === 'true'

export const Route = createRootRouteWithContext<{
  queryClient: QueryClient
}>()({
  component: Root,
  errorComponent: ({ error }) => {
    if (error instanceof Error) {
      Sentry.captureException(error)
    }
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4 dark:text-white p-8">
        <h1 className="text-2xl font-bold">Something went wrong</h1>
        <p className="text-gray-500 dark:text-gray-400 text-center max-w-md">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-brand-purple text-white rounded-lg hover:bg-brand-purple/80"
        >
          Reload page
        </button>
      </div>
    )
  },
})

// Legal pages must be reachable by signed-out visitors (the SignedOut branch
// otherwise renders the sign-in view for every route).
const PUBLIC_ROUTES = ['/privacy', '/terms']

function Root() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  // Public legal pages are plain long documents — render them WITHOUT the app
  // shell's `max-h-screen overflow-hidden` wrapper so the page scrolls normally.
  // (Inside that wrapper, anything past the viewport is clipped with no scrollbar.)
  if (PUBLIC_ROUTES.includes(pathname)) {
    return <Outlet />
  }

  if (E2E_TEST_MODE) {
    return (
      <div className="md:max-h-screen overflow-hidden">
        <Outlet />
      </div>
    )
  }

  return (
    <>
      <SignedIn>
        <div className="md:max-h-screen overflow-hidden">
          <Outlet />
        </div>
      </SignedIn>
      <SignedOut>
        <div className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
          <SignIn />
        </div>
      </SignedOut>
    </>
  )
}
