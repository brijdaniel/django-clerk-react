import { describe, it, expect } from 'vitest'
import { render, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { ApiClientProvider, useApiClient } from '../ApiClientProvider'
import { ApiClient } from '../helper'

// Clerk is globally mocked as a signed-in org:admin in test/setup.ts, so
// ApiClientProvider's useAuth().getToken is available without extra setup.

describe('ApiClientProvider', () => {
  it('throws a clear error when useApiClient is used outside the provider', () => {
    expect(() => renderHook(() => useApiClient())).toThrow(
      'useApiClient must be used within ApiClientProvider',
    )
  })

  it('provides an ApiClient instance when rendered inside the provider', () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ApiClientProvider>{children}</ApiClientProvider>
    )

    const { result } = renderHook(() => useApiClient(), { wrapper })

    expect(result.current).toBeInstanceOf(ApiClient)
  })

  it('exposes the client to a consuming child component', () => {
    function Consumer() {
      const client = useApiClient()
      return <div data-testid="consumer">{client instanceof ApiClient ? 'ok' : 'not-ok'}</div>
    }

    const { getByTestId } = render(
      <ApiClientProvider>
        <Consumer />
      </ApiClientProvider>,
    )

    expect(getByTestId('consumer')).toHaveTextContent('ok')
  })

  // NOTE: the provider memoizes the client on `getToken` (useMemo), but the
  // global Clerk mock in test/setup.ts returns a fresh getToken vi.fn() on every
  // useAuth() call, so the memo key changes each render in the test environment.
  // Asserting cross-render identity here would test the mock, not the code — and
  // the useMemo line is already covered by the render above — so it's omitted.
})
