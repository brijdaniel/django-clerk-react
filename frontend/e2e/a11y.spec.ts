/**
 * Accessibility pilot. Runs axe-core against the key authenticated routes and
 * fails on CRITICAL violations (show-stoppers like missing form labels / no
 * document language). Serious/moderate findings are logged as a baseline to
 * triage — tighten the gate to fail-on-serious once that backlog is cleared.
 *
 * Requires Clerk auth (uses the pre-authenticated storageState).
 */
import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { authenticatePage } from './helpers'

const ROUTES = ['/app/users', '/app/billing']

test.beforeEach(async ({ page }) => {
  await authenticatePage(page)
})

for (const route of ROUTES) {
  test(`a11y: ${route} has no critical axe violations`, async ({ page }) => {
    test.skip(!process.env.CLERK_SECRET_KEY, 'requires Clerk auth')

    await page.goto(route)
    // Let the route's data load before scanning.
    await page.waitForLoadState('networkidle').catch(() => {})

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze()

    const byImpact = (i: string) => results.violations.filter(v => v.impact === i)
    const critical = byImpact('critical')
    const serious = byImpact('serious')

    // Baseline log of non-blocking findings.
    if (serious.length || critical.length) {
      console.log(
        `[a11y] ${route}: ${critical.length} critical, ${serious.length} serious — ` +
        JSON.stringify(
          [...critical, ...serious].map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
        ),
      )
    }

    expect(
      critical.map(v => v.id),
      `critical a11y violations on ${route}`,
    ).toEqual([])
  })
}
