import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.{test,spec}.{ts,tsx}',
        'src/**/__tests__/**',
        'src/test/**',
        'src/**/*.d.ts',
        'src/types/**',
        'src/routeTree.gen.ts',
        'src/main.tsx',
        // --- Presentational / vendored / static: deliberately out of the
        // unit-coverage denominator so the % reflects app LOGIC, not styling.
        // These are exercised by E2E instead; unit-testing them would test
        // Headless UI / static copy, not our code.
        'src/ui/**', // Catalyst kit — styled wrappers over Headless UI
        'src/components/legal/**', // static legal page shell
        'src/routes/privacy.tsx', // static legal copy
        'src/routes/terms.tsx', // static legal copy
        'src/routes/__root.tsx', // Clerk auth-guard + router error boundary (integration)
      ],
      // include counts ALL non-excluded src files (presentational ui/ + landing/
      // + static shells are excluded above, so the % reflects app LOGIC). Filling
      // the API mutations, component modals, and logic-bearing routes lifted this
      // to ~85%; floor sits just below current to catch regressions.
      thresholds: {
        statements: 84,
        branches: 77,
        functions: 81,
        lines: 84,
      },
    },
  },
})
