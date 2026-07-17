import { createFileRoute } from '@tanstack/react-router'
import { LegalPage } from '../components/legal/LegalPage'

export const Route = createFileRoute('/privacy')({
  component: PrivacyPage,
})

// Placeholder page demonstrating the public-route pattern (see the
// PUBLIC_ROUTES allowlist in routes/__root.tsx). Replace with your own
// privacy policy before going live.
function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="1 January 2026">
      <p>
        Replace this page with your privacy policy. It should explain what
        personal information your application collects, how it is used, which
        third parties it is shared with, and how users can exercise their
        rights over their data.
      </p>

      <h2>Suggested sections</h2>
      <ul>
        <li>Information we collect</li>
        <li>How we use information</li>
        <li>Third parties we share data with (e.g. Clerk, Stripe, hosting and monitoring providers)</li>
        <li>Retention and security</li>
        <li>Your rights</li>
        <li>Contact details for privacy questions</li>
      </ul>
    </LegalPage>
  )
}
