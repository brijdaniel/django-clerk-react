import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useDebounce } from '../useDebounce'

describe('useDebounce', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns the initial value immediately', () => {
    const { result } = renderHook(() => useDebounce('hello', 300))
    expect(result.current).toBe('hello')
  })

  it('does not update value before delay expires', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      { initialProps: { value: 'hello', delay: 300 } }
    )

    rerender({ value: 'world', delay: 300 })

    // Value should still be 'hello' before timer fires
    expect(result.current).toBe('hello')

    act(() => {
      vi.advanceTimersByTime(299)
    })
    expect(result.current).toBe('hello')
  })

  it('updates value after delay expires', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      { initialProps: { value: 'hello', delay: 300 } }
    )

    rerender({ value: 'world', delay: 300 })

    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(result.current).toBe('world')
  })

  it('resets timer on rapid value changes', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      { initialProps: { value: 'a', delay: 300 } }
    )

    // Rapid changes
    rerender({ value: 'ab', delay: 300 })
    act(() => {
      vi.advanceTimersByTime(100)
    })

    rerender({ value: 'abc', delay: 300 })
    act(() => {
      vi.advanceTimersByTime(100)
    })

    rerender({ value: 'abcd', delay: 300 })

    // Still should be initial value since timer keeps resetting
    expect(result.current).toBe('a')

    // Wait for full delay after last change
    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(result.current).toBe('abcd')
  })

  it('handles different delay values', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      { initialProps: { value: 'initial', delay: 500 } }
    )

    rerender({ value: 'updated', delay: 500 })

    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(result.current).toBe('initial')

    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(result.current).toBe('updated')
  })

  it('cleans up timeout on unmount', () => {
    const clearTimeoutSpy = vi.spyOn(global, 'clearTimeout')
    const { unmount } = renderHook(() => useDebounce('test', 300))

    unmount()
    expect(clearTimeoutSpy).toHaveBeenCalled()
    clearTimeoutSpy.mockRestore()
  })
})
