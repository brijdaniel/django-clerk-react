/**
 * Allowlist check for URLs received from the API that the app navigates to or
 * renders as links (Stripe Checkout / hosted invoices). Defense in depth: if
 * an API response were ever tampered with, the browser must not be sent to an
 * arbitrary site from a billing flow.
 */
const TRUSTED_STRIPE_HOSTS = [
  'checkout.stripe.com',
  'invoice.stripe.com',
  'pay.stripe.com',
]

export function isTrustedStripeUrl(url: string | null | undefined): url is string {
  if (!url) return false
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return false
  }
  return (
    parsed.protocol === 'https:' &&
    TRUSTED_STRIPE_HOSTS.some(
      (host) => parsed.hostname === host || parsed.hostname.endsWith(`.${host}`),
    )
  )
}
