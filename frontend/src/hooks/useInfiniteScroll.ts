import { useEffect, useRef, type RefObject } from 'react'

export function useInfiniteScroll({
  scrollContainerRef,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  rootMargin = '0px 0px 200px 0px',
}: {
  scrollContainerRef: RefObject<HTMLElement | null>
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => void
  rootMargin?: string
}) {
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const sentinel = sentinelRef.current
    const scrollRoot = scrollContainerRef.current
    if (!sentinel || !scrollRoot) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { root: scrollRoot, rootMargin },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [scrollContainerRef, hasNextPage, isFetchingNextPage, fetchNextPage, rootMargin])

  return sentinelRef
}
