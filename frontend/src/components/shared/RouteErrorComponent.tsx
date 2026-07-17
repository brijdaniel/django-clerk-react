import type { ErrorComponentProps } from '@tanstack/react-router'

export default function RouteErrorComponent({ error, reset }: ErrorComponentProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 dark:text-white p-8">
      <h2 className="text-lg font-semibold">Something went wrong</h2>
      <p className="text-gray-500 dark:text-gray-400 text-center max-w-md">
        {error instanceof Error ? error.message : 'An unexpected error occurred.'}
      </p>
      <button
        onClick={reset}
        className="px-4 py-2 bg-brand-purple text-white rounded-lg hover:bg-brand-purple/80"
      >
        Try again
      </button>
    </div>
  )
}
