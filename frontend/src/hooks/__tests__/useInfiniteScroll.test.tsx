import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act } from '@testing-library/react'
import { useRef } from 'react'
import { useInfiniteScroll } from '../useInfiniteScroll'

// Track the most recent observer instance
let lastObserverCallback: IntersectionObserverCallback
let mockObserve: ReturnType<typeof vi.fn>
let mockDisconnect: ReturnType<typeof vi.fn>

beforeEach(() => {
  mockObserve = vi.fn()
  mockDisconnect = vi.fn()

  const MockIntersectionObserver = class {
    constructor(callback: IntersectionObserverCallback) {
      lastObserverCallback = callback
    }
    observe = mockObserve
    disconnect = mockDisconnect
    unobserve = vi.fn()
    root = null
    rootMargin = ''
    thresholds: number[] = []
    takeRecords = vi.fn()
  }

  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// Test component that renders actual DOM elements so refs get attached
function TestComponent({
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  rootMargin,
}: {
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => void
  rootMargin?: string
}) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const sentinelRef = useInfiniteScroll({
    scrollContainerRef,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    rootMargin,
  })

  return (
    <div ref={scrollContainerRef} data-testid="scroll-container">
      <div>Content</div>
      <div ref={sentinelRef} data-testid="sentinel" />
    </div>
  )
}

describe('useInfiniteScroll', () => {
  it('observes the sentinel element when hasNextPage is true', () => {
    render(
      <TestComponent hasNextPage={true} isFetchingNextPage={false} fetchNextPage={vi.fn()} />,
    )

    expect(mockObserve).toHaveBeenCalledWith(expect.any(HTMLDivElement))
  })

  it('calls fetchNextPage when sentinel is intersecting and hasNextPage is true', () => {
    const fetchNextPage = vi.fn()
    render(
      <TestComponent hasNextPage={true} isFetchingNextPage={false} fetchNextPage={fetchNextPage} />,
    )

    act(() => {
      lastObserverCallback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      )
    })

    expect(fetchNextPage).toHaveBeenCalledTimes(1)
  })

  it('does NOT call fetchNextPage when hasNextPage is false', () => {
    const fetchNextPage = vi.fn()
    render(
      <TestComponent hasNextPage={false} isFetchingNextPage={false} fetchNextPage={fetchNextPage} />,
    )

    act(() => {
      lastObserverCallback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      )
    })

    expect(fetchNextPage).not.toHaveBeenCalled()
  })

  it('does NOT call fetchNextPage when isFetchingNextPage is true', () => {
    const fetchNextPage = vi.fn()
    render(
      <TestComponent hasNextPage={true} isFetchingNextPage={true} fetchNextPage={fetchNextPage} />,
    )

    act(() => {
      lastObserverCallback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      )
    })

    expect(fetchNextPage).not.toHaveBeenCalled()
  })

  it('does NOT call fetchNextPage when sentinel is not intersecting', () => {
    const fetchNextPage = vi.fn()
    render(
      <TestComponent hasNextPage={true} isFetchingNextPage={false} fetchNextPage={fetchNextPage} />,
    )

    act(() => {
      lastObserverCallback(
        [{ isIntersecting: false } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      )
    })

    expect(fetchNextPage).not.toHaveBeenCalled()
  })

  it('disconnects observer on unmount', () => {
    const { unmount } = render(
      <TestComponent hasNextPage={true} isFetchingNextPage={false} fetchNextPage={vi.fn()} />,
    )

    unmount()
    expect(mockDisconnect).toHaveBeenCalled()
  })

  it('reconnects observer when hasNextPage changes', () => {
    const { rerender } = render(
      <TestComponent hasNextPage={true} isFetchingNextPage={false} fetchNextPage={vi.fn()} />,
    )

    const disconnectCountBefore = mockDisconnect.mock.calls.length

    rerender(
      <TestComponent hasNextPage={false} isFetchingNextPage={false} fetchNextPage={vi.fn()} />,
    )

    expect(mockDisconnect.mock.calls.length).toBeGreaterThan(disconnectCountBefore)
  })
})
