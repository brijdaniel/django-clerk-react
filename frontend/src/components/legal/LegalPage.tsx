import type { ReactNode } from 'react'

/**
 * Shared layout for public legal pages (/privacy, /terms).
 *
 * These routes render for signed-out visitors too — see the public-route
 * allowlist in routes/__root.tsx.
 */
export function LegalPage({ title, updated, children }: {
  title: string
  updated: string
  children: ReactNode
}) {
  return (
    <main className="min-h-screen bg-white dark:bg-[#080020]">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <a href="/" className="mb-8 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-purple">
            <span className="text-sm font-semibold text-white font-mono">A</span>
          </div>
          <span className="text-lg font-semibold text-zinc-950 dark:text-white font-mono">App</span>
        </a>

        <h1 className="text-3xl font-semibold text-zinc-950 dark:text-white font-mono">{title}</h1>
        <p className="mt-2 text-sm text-zinc-500 dark:text-[#a99cc4]">Last updated: {updated}</p>

        <div className="mt-8 space-y-6 text-sm leading-6 text-zinc-700 dark:text-[#cfc6e2] [&_h2]:mt-8 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-zinc-950 dark:[&_h2]:text-white [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:space-y-1 [&_a]:underline">
          {children}
        </div>
      </div>
    </main>
  )
}
