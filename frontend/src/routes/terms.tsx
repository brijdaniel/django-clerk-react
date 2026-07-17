import { createFileRoute } from '@tanstack/react-router'
import { LegalPage } from '../components/legal/LegalPage'

export const Route = createFileRoute('/terms')({
  component: TermsPage,
})

// Placeholder page demonstrating the public-route pattern (see the
// PUBLIC_ROUTES allowlist in routes/__root.tsx). Replace with your own
// terms of service before going live.
function TermsPage() {
  return (
    <LegalPage title="Terms of Service" updated="1 January 2026">
      <p>
        Replace this page with your terms of service. It should set out the
        agreement between you and the organisations that use your application.
      </p>

      <h2>Suggested sections</h2>
      <ul>
        <li>Description of the service</li>
        <li>Accounts and responsibilities</li>
        <li>Acceptable use</li>
        <li>Billing, credits, and subscriptions</li>
        <li>Data ownership and privacy</li>
        <li>Liability and termination</li>
        <li>Governing law and contact details</li>
      </ul>
    </LegalPage>
  )
}
