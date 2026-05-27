import { describe, it, expect } from 'vitest'
import baseConfig from '../../staticwebapp.config.base.json'
import devCsp from '../../csp.dev.json'
import prodCsp from '../../csp.prod.json'

describe('staticwebapp.config.base.json', () => {
  it('has navigation fallback to index.html', () => {
    expect(baseConfig.navigationFallback.rewrite).toBe('/index.html')
  })

  it('has required security headers', () => {
    expect(baseConfig.globalHeaders['X-Content-Type-Options']).toBe('nosniff')
    expect(baseConfig.globalHeaders['X-Frame-Options']).toBe('DENY')
    expect(baseConfig.globalHeaders['Referrer-Policy']).toBe('strict-origin-when-cross-origin')
    expect(baseConfig.globalHeaders['Permissions-Policy']).toBeDefined()
  })
})

describe('CSP policies', () => {
  const requiredDomains = {
    'script-src': ["'self'", 'https://*.clerk.com', 'https://challenges.cloudflare.com', 'https://js.stripe.com'],
    'style-src': ["'self'", 'https://fonts.googleapis.com'],
    'font-src': ["'self'", 'https://fonts.gstatic.com'],
    'img-src': ["'self'", 'https://*.blob.core.windows.net', 'https://img.clerk.com'],
    'connect-src': ["'self'", 'https://*.clerk.com', 'https://clerk-telemetry.com', 'https://*.ingest.us.sentry.io', 'https://api.stripe.com'],
    'frame-src': ['https://*.clerk.com', 'https://challenges.cloudflare.com', 'https://js.stripe.com'],
    'worker-src': ["'self'", 'blob:'],
  }

  const devOnlyDomains = [
    'https://*.clerk.accounts.dev',
    'https://*.clerk.dev',
    'https://*.azurewebsites.net',
    'https://*.azurecontainerapps.io',
  ]

  for (const [directive, domains] of Object.entries(requiredDomains)) {
    it(`dev CSP ${directive} includes required domains`, () => {
      const values = (devCsp as Record<string, string[]>)[directive]
      for (const domain of domains) {
        expect(values, `${directive} missing ${domain}`).toContain(domain)
      }
    })

    it(`prod CSP ${directive} includes required domains`, () => {
      const values = (prodCsp as Record<string, string[]>)[directive]
      for (const domain of domains) {
        expect(values, `${directive} missing ${domain}`).toContain(domain)
      }
    })
  }

  it('prod CSP does NOT contain dev-only domains', () => {
    const allProdValues = Object.values(prodCsp as Record<string, string[]>).flat()
    for (const domain of devOnlyDomains) {
      expect(allProdValues, `prod CSP should not contain ${domain}`).not.toContain(domain)
    }
  })

  it('dev CSP contains dev-only Clerk domains', () => {
    const connectSrc = (devCsp as Record<string, string[]>)['connect-src']
    expect(connectSrc).toContain('https://*.clerk.accounts.dev')
    expect(connectSrc).toContain('https://*.clerk.dev')
  })

  it('prod CSP connect-src uses specific API domain', () => {
    const connectSrc = (prodCsp as Record<string, string[]>)['connect-src']
    expect(connectSrc).toContain('https://api.1reach.net')
  })
})
