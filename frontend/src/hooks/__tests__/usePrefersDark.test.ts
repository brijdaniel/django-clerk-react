import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePrefersDark } from '../usePrefersDark'

// The global matchMedia stub in test/setup.ts is static (matches:false,
// addEventListener is a bare vi.fn that ignores its handler). To drive the
// hook we override window.matchMedia locally with a controllable mock that
// captures the 'change' listener and lets us flip `matches`.
let mql: {
  matches: boolean
  media: string
  addEventListener: ReturnType<typeof vi.fn>
  removeEventListener: ReturnType<typeof vi.fn>
}
let changeHandler: ((event: MediaQueryListEvent) => void) | null
let originalMatchMedia: typeof window.matchMedia

beforeEach(() => {
  originalMatchMedia = window.matchMedia
  changeHandler = null

  mql = {
    matches: false,
    media: '(prefers-color-scheme: dark)',
    addEventListener: vi.fn((event: string, handler: (e: MediaQueryListEvent) => void) => {
      if (event === 'change') changeHandler = handler
    }),
    removeEventListener: vi.fn(),
  }

  // Return the SAME mql object on every call so getSnapshot reads the live
  // `matches` value and subscribe registers against the captured handler.
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation(() => mql),
  })
})

afterEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: originalMatchMedia,
  })
})

describe('usePrefersDark', () => {
  it('reflects the initial matchMedia matches state (false)', () => {
    mql.matches = false
    const { result } = renderHook(() => usePrefersDark())
    expect(result.current).toBe(false)
  })

  it('reflects the initial matchMedia matches state (true)', () => {
    mql.matches = true
    const { result } = renderHook(() => usePrefersDark())
    expect(result.current).toBe(true)
  })

  it('subscribes to the change event of the prefers-color-scheme query', () => {
    renderHook(() => usePrefersDark())
    expect(window.matchMedia).toHaveBeenCalledWith('(prefers-color-scheme: dark)')
    expect(mql.addEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    expect(changeHandler).toBeTypeOf('function')
  })

  it('updates when the media query change event fires', () => {
    mql.matches = false
    const { result } = renderHook(() => usePrefersDark())
    expect(result.current).toBe(false)

    act(() => {
      mql.matches = true
      changeHandler?.({ matches: true } as MediaQueryListEvent)
    })

    expect(result.current).toBe(true)
  })

  it('removes its change listener on unmount', () => {
    const { unmount } = renderHook(() => usePrefersDark())
    expect(mql.removeEventListener).not.toHaveBeenCalled()

    unmount()

    expect(mql.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    // The removed handler is the same one that was added.
    expect(mql.removeEventListener.mock.calls[0][1]).toBe(
      mql.addEventListener.mock.calls[0][1],
    )
  })
})
