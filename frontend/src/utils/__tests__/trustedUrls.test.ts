import { describe, expect, it } from 'vitest'
import { isTrustedStripeUrl } from '../trustedUrls'

describe('isTrustedStripeUrl', () => {
  it.each([
    'https://checkout.stripe.com/c/pay/cs_test_123',
    'https://invoice.stripe.com/i/acct_1/inv_123',
    'https://pay.stripe.com/invoice/inv_123',
  ])('accepts %s', (url) => {
    expect(isTrustedStripeUrl(url)).toBe(true)
  })

  it.each([
    ['phishing host', 'https://checkout.stripe.com.evil.example/pay'],
    ['lookalike suffix', 'https://evilcheckout.stripe.com.attacker.net/x'],
    ['plain http', 'http://checkout.stripe.com/c/pay/cs_test_123'],
    ['javascript scheme', 'javascript:alert(1)'],
    ['arbitrary host', 'https://example.com/checkout.stripe.com'],
    ['empty string', ''],
    ['not a url', 'not a url'],
  ])('rejects %s', (_label, url) => {
    expect(isTrustedStripeUrl(url)).toBe(false)
  })

  it('rejects null and undefined', () => {
    expect(isTrustedStripeUrl(null)).toBe(false)
    expect(isTrustedStripeUrl(undefined)).toBe(false)
  })
})
