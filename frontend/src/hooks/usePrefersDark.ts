import { useSyncExternalStore } from 'react'

const query = '(prefers-color-scheme: dark)'

function subscribe(callback: () => void) {
  const mql = window.matchMedia(query)
  mql.addEventListener('change', callback)
  return () => mql.removeEventListener('change', callback)
}

function getSnapshot() {
  return window.matchMedia(query).matches
}

function getServerSnapshot() {
  return false
}

export function usePrefersDark() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
