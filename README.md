# 1Reach

A multi-tenant SMS/MMS messaging platform for managing contacts, groups, templates, and scheduled messages.

---

## Overview

1Reach lets organisations send and schedule SMS/MMS messages to individual contacts or groups. Each organisation is isolated — contacts, templates, schedules, and configs are all scoped per organisation. Admins sign up via Clerk, create an organisation, and invite team members.

**Key capabilities:**
- Contact management with CSV import
- Group messaging with scheduling
- Template library
- SMS/MMS sending — single or batch (multi-recipient), async dispatch via Celery with automatic retry and credit refund on failure
- Alphanumeric sender ID — org admins configure allowed sender IDs, users select one at send time (displayed instead of phone number on recipient handsets; one-way only)
- Manual retry — failed messages can be retried from the schedule page UI (billing re-checked, credits re-charged for prepaid orgs)
- Scheduled sends — Celery beat dispatches due messages every 60 s
- Org user management — invite, deactivate, grant/revoke admin
- Usage stats dashboard
- Billing system — prepaid credits on signup, subscribed mode with metered tracking, monthly spending limits, transaction history, credit refunds on failed sends, inline subscription management via Clerk PricingTable, automated metered invoicing via Stripe

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6 + Django REST Framework + PostgreSQL 16 |
| Auth & Billing | Clerk (JWT + webhooks + subscription billing) + Stripe (metered usage invoicing) |
| Frontend | React 19 + Vite 7 + TanStack Router + TanStack Query |
| Styling | Tailwind CSS 3 + HeadlessUI + Lucide icons |
| SMS/Storage | Pluggable provider interface (Mock by default, Azure Blob for storage) |
| Task queue | Celery 5 + Redis 7 (async send pipeline, retry logic, beat scheduler) |
| Monitoring | Sentry + structured JSON logging |
| Testing | pytest (backend), Vitest + Playwright (frontend) |

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- A [Clerk](https://clerk.com) account with an application configured

### Environment Setup

Copy and fill in the environment files:

```bash
# Root (Docker Compose postgres + rate limiting)
cp .envexample .env

# Backend (Django settings + Clerk + optional Azure/Sentry)
cp backend/.envexample backend/.env

# Frontend (Clerk publishable key)
cp frontend/.envexample frontend/.env
```

**Root `.env`** — PostgreSQL credentials and rate limiting:

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_DB` | `app` | Database name |
| `POSTGRES_USER` | `app` | Database user |
| `POSTGRES_PASSWORD` | `app` | Database password |
| `THROTTLE_RATE_ANON` | `1000/min` | Anonymous request rate limit |
| `THROTTLE_RATE_USER` | `1000/min` | Authenticated user rate limit |
| `THROTTLE_RATE_SMS` | `100/min` | SMS endpoint rate limit |
| `THROTTLE_RATE_IMPORT` | `10/min` | CSV import rate limit |

**`backend/.env`** — Django + Clerk:

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Django secret key |
| `ALLOWED_HOSTS` | No | Comma-separated allowed host headers (default: `localhost,127.0.0.1`) |
| `CORS_ALLOWED_ORIGINS` | No | Comma-separated allowed CORS origins (default: `http://localhost:5173`) |
| `CLERK_AUTHORIZED_PARTIES` | No | Comma-separated frontend URLs that may present Clerk JWTs (default: `http://localhost:5173`) |
| `CLERK_FRONTEND_API` | Yes | Clerk frontend API URL |
| `CLERK_SECRET_KEY` | Yes | Clerk secret key (`sk_...`) |
| `CLERK_WEBHOOK_SIGNING_SECRET` | Yes | Clerk webhook signing secret (`whsec_...`) |
| `DEBUG` | No | Set to `1` for development |
| `STORAGE_PROVIDER_CLASS` | No | Defaults to `MockStorageProvider`; set to `AzureBlobStorageProvider` for real storage |
| `AZURE_STORAGE_ACCOUNT_NAME` | If using Azure | Azure Storage account name |
| `AZURE_STORAGE_ACCOUNT_KEY` | If using Azure | Azure Storage account key (for per-blob SAS tokens) |
| `AZURE_CONTAINER` | If using Azure | Blob container name (default: `media`) |
| `SENTRY_DSN` | No | Sentry DSN for error tracking |
| `LOG_LEVEL` | No | `INFO` or `DEBUG` (default: `INFO`) |
| `LOG_FORMAT` | No | `json` or `text` (default: `json`) |
| `FREE_CREDIT_AMOUNT` | No | Dollar credits granted to new orgs on signup (default: `10.00`) |
| `SMS_RATE` | No | Default cost per SMS message part in dollars (default: `0.10`). Can be overridden per org via Config. |
| `MMS_RATE` | No | Default cost per MMS send in dollars (default: `0.50`). Can be overridden per org via Config. |
| `CELERY_BROKER_URL` | No | Redis URL for Celery broker (default: `redis://redis:6379/0`) |
| `CELERY_RESULT_BACKEND` | No | Redis URL for task results (default: `redis://redis:6379/0`) |
| `MESSAGE_MAX_RETRIES` | No | Max retry attempts per message (default: `3`) |
| `MESSAGE_RETRY_BASE_DELAY` | No | Base backoff delay in seconds (default: `60`) |
| `MESSAGE_RETRY_MAX_DELAY` | No | Max backoff delay in seconds (default: `3600`) |
| `MESSAGE_RETRY_JITTER` | No | Jitter fraction for backoff (default: `0.25` = ±25%) |
| `WELCORP_BASE_URL` | No | Welcorp API URL (default: `https://api.message-service.org/api/v1`) |
| `WELCORP_USERNAME` | If using Welcorp | Welcorp Basic auth username |
| `WELCORP_PASSWORD` | If using Welcorp | Welcorp Basic auth password |
| `WELCORP_CALLBACK_SECRET` | No | Shared secret for delivery callback URL token verification |
| `BASE_URL` | No | Publicly accessible base URL for this application (e.g. `https://your-domain.com`) — used for provider delivery callbacks |
| `STRIPE_SECRET_KEY` | If using Stripe | Stripe secret key (`sk_...`) — required for `StripeMeteredBillingProvider` |
| `STRIPE_WEBHOOK_SECRET` | If using Stripe | Stripe webhook signing secret (`whsec_...`) |

**`frontend/.env`** — Vite + Clerk:

| Variable | Required | Description |
|---|---|---|
| `VITE_CLERK_PUBLISHABLE_KEY` | Yes | Clerk publishable key (`pk_...`) |
| `VITE_API_BASE_URL` | No | Backend URL (default: `http://localhost:8000`) |
| `VITE_SENTRY_DSN` | No | Sentry DSN for frontend error tracking (disabled if not set) |
| `VITE_SENTRY_ENVIRONMENT` | No | Sentry environment tag (default: `production`) |

### Running Locally

```bash
docker compose up
```

This starts six services:

| Service | URL | Description |
|---|---|---|
| Backend API | http://localhost:8000 | Django REST API |
| Frontend | http://localhost:5173 | React dev server |
| Swagger UI | http://localhost:8000/api/docs/ | Interactive API docs |
| ReDoc | http://localhost:8000/api/redoc/ | API reference |
| Redis | localhost:6379 | Celery broker + result backend |
| Celery worker | — | Processes `send_message` tasks (async SMS/MMS dispatch) |
| Celery beat | — | Runs `dispatch_due_messages` every 60 s, `reconcile_stale_sent` (polls provider for missed callbacks), `cleanup_stale_media_blobs` (daily — deletes MMS media blobs for failed schedules >7 days old), `generate_monthly_invoices` (1st of month — creates Stripe invoices for subscribed orgs) |

---

## Architecture

### Backend (`backend/`)

```
backend/
├── app/
│   ├── models.py          # Contact, Group, Template, Schedule, Organisation, User, Config, CreditTransaction, Invoice, CreditPurchase
│   ├── views.py           # ViewSets for all API endpoints + BillingViewSet
│   ├── serializers.py     # DRF serializers + CreditTransactionSerializer
│   ├── authentication.py  # ClerkJWTAuthentication — extracts org context from JWT
│   ├── permissions.py     # IsOrgMember, IsOrgAdmin
│   ├── filters.py         # django-filter (search, date, group)
│   ├── celery.py          # Celery app + send_message + dispatch_due_messages + process_delivery_event + reconcile_stale_sent + cleanup_stale_media_blobs + generate_monthly_invoices + link_billing_customer tasks + task_failure signal handler
│   ├── worker.py          # UvicornWorker subclass with lifespan=off (Django doesn't handle ASGI lifespan events)
│   ├── health.py          # HealthCheckView (DB + Redis connectivity) + SmokeCheckView (DB write + Redis write) + DEPLOY_SHA version tracking
│   ├── middleware/        # RequestLoggingMiddleware, ClerkTenantMiddleware
│   ├── utils/
│   │   ├── billing.py          # grant_credits, check_can_send, record_usage, refund_usage, etc.
│   │   ├── failure_classifier.py  # classify_failure() — maps provider errors to FailureCategory
│   │   ├── clerk.py            # Webhook handlers (user/org/membership sync + billing subscription events)
│   │   ├── sms.py              # Pluggable SMS provider (SMSProvider base + MockSMSProvider + DeliveryEvent)
│   │   ├── welcorp.py          # Welcorp SMS/MMS provider (API integration + delivery callbacks + job polling)
│   │   ├── storage.py          # Pluggable storage provider (Mock + Azure Blob)
│   │   ├── metered_billing.py  # Pluggable metered billing provider (MeteredBillingProvider base + MockMeteredBillingProvider)
│   │   └── stripe.py           # Stripe metered billing provider (StripeMeteredBillingProvider + StripeWebhookView)
│   └── mixins.py          # SoftDeleteMixin, TenantScopedMixin
├── Dockerfile             # Multi-stage build for API, worker, and beat (same image)
├── entrypoint.sh          # Role-based command selection (api/worker/beat) + DB wait loop
└── tests/
```

**Multi-tenancy:** All business models inherit `TenantModel`, which adds an `organisation` FK. All queries are scoped to the authenticated user's organisation via `TenantScopedMixin`. Org context is extracted from the Clerk JWT `o` claim during authentication.

**Clerk integration:** Users and organisations are created in Clerk and synced to the local DB via webhooks (`POST /api/webhooks/clerk/`). Membership changes (role updates, deactivation, invitations) go through Clerk's API and sync back via webhooks — Clerk is the source of truth.

**Async send pipeline:** Send endpoints (`POST /api/sms/send/`, `send-mms/`, `send-to-group/`) return `202 Accepted` immediately. Single-recipient sends dispatch a `send_message` task; multi-recipient sends create a parent Schedule with per-recipient child Schedules and dispatch a `send_batch_message` task that calls the provider's bulk send interface:

```
Single recipient:
  HTTP POST → validate + billing gate → Schedule(QUEUED) → send_message.delay() → 202

Multiple recipients:
  HTTP POST → validate + billing gate → parent Schedule(QUEUED) + N child Schedules
            → send_batch_message.delay(parent.pk) → 202

Celery worker (both paths):
  QUEUED → PROCESSING → SENT → DELIVERED (receipt)
                      ↓ transient fail → RETRYING (backoff)
                      ↓ permanent fail → FAILED + refund

Manual retry (UI):
  FAILED → POST /api/schedules/{id}/retry/ → QUEUED → (re-enters pipeline)
```

Retry backoff: `min(base × 2^n, max_delay) × (1 ± 25% jitter)` — defaults to ~1m → 2m → 4m → 8m, capped at 1h. A `dispatch_due_messages` beat task runs every 60 s to pick up scheduled sends and recover stuck RETRYING/PROCESSING schedules.

**Worker startup:** `celery.py` calls `django.setup()` after `app.config_from_object(...)` and before any model imports. This is required because the worker starts a fresh Python process where Django's app registry is not yet populated. Without it, model imports raise `AppRegistryNotReady` and the worker exits silently, leaving all dispatched messages stuck in QUEUED. The `backend/entrypoint.sh` script handles role-based command selection via the `CONTAINER_ROLE` env var (`api`, `worker`, or `beat`), includes a DB readiness wait loop (up to 2.5 minutes), and delegates to `uv run` for all Python execution. Lifecycle events are logged via Celery signals: `beat_init`, `worker_ready`, `worker_shutting_down`, `task_failure`. The API uses `app.worker.Worker` (a `UvicornWorker` subclass with `lifespan=off`) because Django doesn't handle ASGI lifespan events — without this, Sentry is flooded with `ValueError` on every worker start.

**Failure classification:** `failure_classifier.py` maps provider errors to `FailureCategory` (permanent: `invalid_number`, `opt_out`, `blacklisted`, etc.; transient: `network_error`, `rate_limited`, `server_error`, etc.). Permanent failures skip retries and trigger `refund_usage()`. MMS media blobs are **not** deleted on failure — they are retained for 7 days to allow manual retry, then cleaned up by the `cleanup_stale_media_blobs` daily beat task.

**Billing system:** `Organisation` has `credit_balance` (Decimal), `billing_mode` (`prepaid` | `subscribed` | `past_due`), and `billing_customer_id` (Stripe Customer ID). Every billable action (send or grant) creates a `CreditTransaction` row. `billing.py` exposes `check_can_send`, `record_usage`, and `refund_usage`. SMS costs `message_parts × rate`; MMS costs `1 × rate`. Rates default to the global `SMS_RATE`/`MMS_RATE` settings but can be overridden per organisation using the `Config` model (see [Per-org rate overrides](#per-org-rate-overrides) below). Each `CreditTransaction` stores the `unit_rate` used at the time of recording, so invoices remain accurate even if an org's rate changes mid-month. Prepaid credits are reserved at HTTP dispatch time; on terminal failure `refund_usage()` restores the balance idempotently. Subscribed orgs record usage on `SENT`. `check_can_send` blocks all sends when `billing_mode='past_due'`. Clerk Billing handles subscription lifecycle: `subscription.active` sets `billing_mode='subscribed'` and clears the Clerk `billing_suspended` metadata flag; `subscriptionItem.canceled`/`subscriptionItem.ended` reverts to `'prepaid'`; `subscription.past_due` sets `billing_mode='past_due'` and sets `billing_suspended=True` in Clerk org metadata. The billing page has a "Manage Plan" button that opens a dialog with Clerk's `PricingTable` component, allowing admins to subscribe, switch, or cancel inline.

**Prepaid credit purchases:** Orgs start in `prepaid` mode with free credits ($10 by default via `FREE_CREDIT_AMOUNT`). When credits run out, admins can purchase more via Stripe Checkout. The billing page shows a "Buy Credits" button that opens a dialog with preset amounts ($10, $25, $50, $100, $500, $1,000) plus a custom amount input ($5–$10,000). `POST /api/billing/buy-credits/` validates the amount, creates a `CreditPurchase` record (status=pending), generates a Stripe Checkout Session, and returns the checkout URL. After payment, Stripe sends a `checkout.session.completed` webhook which grants the credits to the org via `grant_credits()`, links the Stripe customer ID (for first-time buyers), and marks the purchase as completed. If the session expires (user abandons checkout), a `checkout.session.expired` webhook marks it as expired. The `CreditPurchase` model provides a full audit trail of all purchase attempts.

**Metered billing (Stripe):** Clerk does not support metered billing, so Stripe handles per-message usage invoicing. When an org subscribes through Clerk, Clerk creates a Stripe Customer in the app's Stripe account with `metadata.organization_id` set to the Clerk org ID. The `_handle_subscription_active` webhook handler searches Stripe for this customer and saves the `billing_customer_id` on the `Organisation`; if the lookup fails (timing), a `link_billing_customer` Celery task retries with exponential backoff. Monthly invoices are generated by a `generate_monthly_invoices` beat task (runs on the 1st of each month): it aggregates `CreditTransaction` records (usage minus refunds) by format, builds line items, and creates a Stripe Invoice via the `MeteredBillingProvider` interface. Stripe auto-charges the card saved during Clerk subscription signup. The `Invoice` model tracks invoice status locally; Stripe webhooks (`invoice.paid`, `invoice.payment_failed`, `invoice.overdue`, `invoice.voided`) update the status via `StripeWebhookView`. If payment fails or the invoice becomes overdue, the org is set to `past_due` (blocking all sends); when the customer pays and no other uncollectable invoices remain, the org is restored to `subscribed` (this guard prevents incorrectly restoring an org that was set to `past_due` by Clerk for subscription reasons rather than Stripe payment failure). The metered billing provider is pluggable via `settings.METERED_BILLING_PROVIDER_CLASS` (same pattern as `SMS_PROVIDER_CLASS`), with `MockMeteredBillingProvider` for dev/testing and `StripeMeteredBillingProvider` for production.

**Per-org rate overrides:** By default all organisations are billed at the global `SMS_RATE` and `MMS_RATE` from settings. To give a specific org a custom rate, create a `Config` row for that organisation with `name` set to `{format}_rate` and `value` set to the dollar amount as a decimal string. The `get_rate(format, org)` function checks for a matching Config override first and falls back to the global setting.

| Config `name` | Effect | Example `value` |
|---|---|---|
| `sms_rate` | Override SMS cost per message part | `0.03` |
| `mms_rate` | Override MMS cost per send | `0.10` |

Set via the Configs API (`POST /api/configs/` with `{ "name": "sms_rate", "value": "0.03" }`) or Django admin. The override only applies to the org that owns the Config row — other orgs continue using the global default. Removing the Config row reverts the org to the global rate. When a rate changes, only future sends are affected; past `CreditTransaction` records retain the `unit_rate` they were recorded at, so invoices always reflect the rate that was in effect at time of send.

**Alphanumeric sender ID:** Org admins can configure a whitelist of alphanumeric sender IDs (e.g. "MYCOMPANY", "ALERTS") that replace the default phone number on the recipient's handset. Create a `Config` row with `name='allowed_alphanumeric_senders'` and `value` set to a JSON array of strings. Users can then select a sender ID from a dropdown on the send form. The selected ID is stored on the `Schedule.alphanumeric_sender` field and passed to the Welcorp API as `manual_sender_id` in the job payload. Sender IDs must be 3–11 characters, alphanumeric with optional interior spaces. Messages sent with an alphanumeric sender ID are one-way only — recipients cannot reply. The `GET /api/sms/alphanumeric-senders/` endpoint returns the list of allowed senders for the current org; the send form conditionally shows the dropdown only when this list is non-empty.

| Config `name` | Effect | Example `value` |
|---|---|---|
| `allowed_alphanumeric_senders` | Whitelist of sender IDs users can select at send time | `["MYCOMPANY","ALERTS"]` |

**SMS/Storage/Billing providers:** All three are pluggable via `settings.SMS_PROVIDER_CLASS`, `settings.STORAGE_PROVIDER_CLASS`, and `settings.METERED_BILLING_PROVIDER_CLASS`. Mock providers are used by default (dev/testing). The `SMSProvider` base class defines `send_sms()`, `send_bulk_sms()`, `send_mms()`, and `send_bulk_mms()` public methods that handle phone validation/normalisation, then delegate to abstract `_send_sms_impl()` and `_send_mms_impl()` methods. Bulk methods (`_send_bulk_sms_impl`, `_send_bulk_mms_impl`) have default implementations that loop over the individual send method — providers with native batch support can override them.

**Delivery status tracking:** The `SMSProvider` base class also defines a provider-agnostic delivery callback/polling interface. Providers can override `parse_delivery_callback()` to handle incoming webhooks, `validate_callback_request()` for authentication, `get_callback_url()` to register callbacks in send payloads, and `poll_job_status()` to fetch delivery reports on demand. All methods return `DeliveryEvent` objects consumed by the `process_delivery_event` Celery task, which updates schedule status and triggers billing refunds on carrier-reported failures. A `reconcile_stale_sent` beat task polls the provider for schedules stuck in SENT >24h as a fallback when callbacks are missed. The Welcorp provider (`welcorp.py`) implements all four methods. Welcorp's `SENT` status means "carrier accepted" (the best confirmation available — no handset delivery status exists), so it is mapped to `DELIVERED` to mark the schedule as terminal.

### Frontend (`frontend/`)

```
frontend/
├── src/
│   ├── api/               # Query options + mutation hooks (usersApi, contactsApi, etc.)
│   ├── components/
│   │   ├── landing/       # Landing page sections (Navbar, Hero, Features, Pricing, etc.)
│   │   ├── contacts/      # Contact-related components
│   │   ├── groups/        # Group-related components
│   │   ├── shared/        # Shared components (LoadingSpinner, etc.)
│   │   └── ScheduleDateTimePicker.tsx  # Unified datetime picker (Send page, Contact modal, Group modal)
│   ├── routes/app/        # File-based route components (TanStack Router)
│   ├── ui/                # HeadlessUI + Tailwind component library
│   ├── types/             # TypeScript types matching backend snake_case fields
│   ├── lib/               # ApiClient, ApiClientProvider, cn() utility
│   └── test/              # Vitest setup, MSW handlers, factories
└── e2e/                   # Playwright tests
```

**Scheduling UI:** All scheduling flows (Send page, Contact message modal, Group schedule modal) use a unified `ScheduleDateTimePicker` component. It renders a `datetime-local` input with a `min` attribute set to the current time (preventing past-time selection), outputs UTC ISO strings, and shows contextual status messages (past time warning, immediate send notice, or scheduled confirmation).

**Landing page:** Unauthenticated visitors see a marketing landing page (`src/components/landing/`) rendered via Clerk's `<SignedOut>` gate in `__root.tsx`. It includes a hero section with animated canvas background, features grid, pricing tiers, and CTA sections. Sign In / Sign Up buttons open Clerk modals. Once authenticated, users are redirected to `/app/send`. The landing page supports both light and dark mode via `prefers-color-scheme` media queries — light mode uses white/gray backgrounds with dark text (matching the logged-in app's light palette), while dark mode uses the branded navy backgrounds with white text. The `AnimatedMessagesBg` canvas component detects the colour scheme at runtime via `matchMedia` and reduces particle opacity in light mode.

**Brand colours:** Defined in `tailwind.config.cjs` under `theme.extend.colors.brand`:

| Token | Hex | Usage |
|-------|-----|-------|
| `brand-purple` | `#7400f6` | Primary actions, buttons, progress bars |
| `brand-navy` | `#190075` | Dark text accents |
| `brand-light-purple` | `#9d30a0` | Secondary accents |
| `brand-teal` | `#048fb5` | Tertiary accents |
| `brand-green` | `#2CDFB5` | Success states |
| `brand-red` | `#FC7091` | Error states |
| `brand-amber` | `#FEC200` | Warning states |

Fonts: Inter (body/sans) and Poppins (headings/mono) loaded via Google Fonts in `index.html`.

**Schedule page polling:** All schedule queries use dynamic `refetchInterval` — when any visible schedule is in a transient state (pending, queued, processing, retrying), the page polls every 2 seconds for updates. When all schedules are terminal (sent, delivered, failed, cancelled), polling slows to 60 seconds.

**API client pattern:** All components use `useApiClient()` to get an `ApiClient` instance pre-authenticated with a Clerk JWT. API modules (`src/api/`) export TanStack Query options and mutation hooks that accept the client as their first argument.

**Clerk mutations:** Role and status mutations use a 2-second delayed query invalidation to account for the race condition between the API response and webhook processing.

---

## API Reference

| Resource | Endpoints |
|---|---|
| Contacts | `GET/POST /api/contacts/`, `GET/PUT/PATCH /api/contacts/:id/`, `GET /api/contacts/:id/schedules/`, `POST /api/contacts/import/` |
| Groups | `GET/POST /api/groups/`, `GET/PUT/PATCH/DELETE /api/groups/:id/`, `POST/DELETE /api/groups/:id/members/` |
| Templates | `GET/POST /api/templates/`, `GET/PUT/PATCH /api/templates/:id/` |
| Schedules | `GET/POST /api/schedules/`, `GET/PUT/PATCH /api/schedules/:id/`, `GET /api/schedules/:id/recipients/`, `POST /api/schedules/:id/retry/` → re-queue failed schedule |
| Group Schedules | `GET/POST /api/group-schedules/`, `GET/PUT/DELETE /api/group-schedules/:id/` |
| Users | `GET /api/users/`, `GET /api/users/me/`, `PATCH /api/users/:id/role/`, `PATCH /api/users/:id/status/`, `POST /api/users/invite/` |
| SMS/MMS | `POST /api/sms/send/` → 202, `POST /api/sms/send-to-group/` → 202, `POST /api/sms/send-mms/` → 202, `POST /api/sms/upload-file/`, `GET /api/sms/alphanumeric-senders/` |
| Stats | `GET /api/stats/monthly/` |
| Billing | `GET /api/billing/summary/`, `POST /api/billing/buy-credits/` → checkout URL, `GET /api/billing/invoices/`, `GET /api/billing/invoice-preview/`, `POST /api/billing/invoice-download/` (admin only) |
| Configs | `GET/POST/PUT/PATCH/DELETE /api/configs/`, `GET/PUT/PATCH/DELETE /api/configs/:id/` — per-org key-value settings (e.g. `monthly_limit`, `sms_rate`, `mms_rate`, `allowed_alphanumeric_senders`) |
| Webhooks | `POST /api/webhooks/clerk/`, `POST /api/webhooks/sms-delivery/`, `POST /api/webhooks/stripe/` |
| Health | `GET /api/health/` (DB + Redis connectivity), `GET /api/health/smoke/` (DB write + Redis write + deploy version) |

All endpoints require Clerk JWT authentication except health/smoke endpoints (unauthenticated). Most require `IsOrgMember`; user management and billing endpoints require `IsOrgAdmin`.

---

## Testing

### Backend

```bash
docker compose run --rm backend uv run python -m pytest tests/ -x -q
```

793 tests. Run with `-v` for verbose output or `--cov` for a coverage report. If the schema has changed since the last run, rebuild the test database first:

```bash
docker compose run --rm backend uv run python -m pytest --create-db tests/ -q
```

### Frontend (unit + integration)

```bash
docker compose exec frontend npx vitest run
```

475 tests. Uses Vitest + MSW for API mocking. Covers API modules, components, and route integration tests.

### Frontend (E2E)

```bash
docker compose exec frontend npx playwright test
```

104 Playwright tests covering all user flows: contacts (CRUD + message history + send modal), groups (CRUD + edit + member removal + schedule modal), templates (CRUD + edit + pre-fill verification), schedules (navigation + status badges + cancellation + row expansion + pagination), send SMS (form validation + recipient count + template selection), send pipeline (SMS/MMS success + billing gates + group send + status display), summary (stats table + monthly limit), billing (balance display + transaction history + exhausted warning), billing-stripe (subscribe via PricingTable with Stripe test card + invoice generation + invoice display + cancel subscription), and users (table + invite + role/status management). Tests hit the **real backend** (Django + PostgreSQL) — no `page.route()` mocking.

**Authentication:** E2E tests use real Clerk authentication via `@clerk/testing/playwright`:

1. `global-setup.ts` creates a fresh Clerk user + org per CI run, waits for the backend health endpoint to return 200 (up to 2.5 minutes), then seeds the Django DB by posting simulated webhook events directly to the backend with retry logic (in `TEST` mode, Svix signature verification is skipped).
2. `auth.setup.ts` (Playwright setup project) signs in via Clerk's ticket strategy and saves browser `storageState` to `/tmp/e2e-auth-state.json`.
3. All chromium tests inherit the pre-authenticated state. `beforeAll` blocks that need API access (e.g., `send-pipeline.spec.ts`) use `authenticatePage()` which falls back to a full sign-in from the state file.
4. `global-teardown.ts` deletes the Clerk user + org.

**CI requirements:** Set `CLERK_SECRET_KEY` (Clerk secret key) and `E2E_CLERK_USER_ID` (a test user ID) as CI secrets. For Stripe billing E2E tests, also set `STRIPE_SECRET_KEY` (Stripe test mode key). The backend must have `TEST=True` to enable test-only endpoints (`force-status`, `test-set-balance`, `test-seed-usage`, `test-generate-invoices`, `test-link-billing-customer`) and skip webhook signature verification.

**users.spec.ts** is self-contained: it creates its own Clerk admin, member, and inactive users + org in `beforeAll`, independent of the global test user. It uses `test.use({ storageState: { cookies: [], origins: [] } })` to clear the main user's session.

### E2E Test Limitations

The E2E tests are **UI integration tests** — they exercise real HTTP calls against a real backend and database, but external services and the async task queue are mocked or bypassed:

| Component | E2E Behaviour | What's NOT tested |
|---|---|---|
| **SMS/MMS provider** | `MockSMSProvider` returns fake message IDs | No real message delivery or provider error handling |
| **Storage provider** | `MockStorageProvider` returns fake URLs | No real file uploads (MMS attachments) |
| **Clerk webhooks** | Simulated via direct POST (no Svix signature) | Real webhook delivery, retries, and signature validation |
| **Celery workers** | Not running — tasks enqueued to Redis but never consumed | Async dispatch, retry logic, status transitions, failure recovery |
| **Schedule statuses** | Forced via TEST-only `PATCH /api/schedules/:id/force-status/` | Organic state machine transitions from task execution |
| **Billing** | Real `check_can_send` DB checks; balance set via TEST-only endpoint | Credit transactions from actual task execution; refund-on-failure flow |
| **Stripe** | Real Stripe test mode API calls (`sk_test_` key); invoices created via `StripeMeteredBillingProvider`; usage seeded via TEST-only endpoint | Automatic Stripe webhook delivery (simulated via direct POST); real payment collection |
| **Clerk subscription** | Real Clerk PricingTable + Stripe test card checkout; webhook simulated via direct POST | Real Clerk webhook delivery (locally unreachable) |
| **Redis** | Running but effectively unused (no worker consuming tasks) | Broker reliability, task routing |

**TEST-mode-only endpoints** used by E2E tests:
- `PATCH /api/schedules/:id/force-status/` — set schedule status directly
- `PATCH /api/billing/test-set-balance/` — set org credit balance directly
- `POST /api/billing/test-seed-usage/` — create CreditTransaction usage records (accepts `backdate_days` to shift `created_at` for invoice generation testing)
- `POST /api/billing/test-generate-invoices/` — trigger `generate_monthly_invoices` task synchronously
- `POST /api/billing/test-link-billing-customer/` — trigger Stripe customer lookup and link `billing_customer_id`
- Webhook endpoint skips Svix signature verification

---

## Clerk Configuration

### Development instance

1. Create an application in the [Clerk Dashboard](https://dashboard.clerk.com)
2. Enable **Organizations** in the Clerk Dashboard
3. Enable **Organization Invitations** (Organizations → Settings)
4. Configure your **Webhook** endpoint to point to `https://your-domain/api/webhooks/clerk/` and subscribe to all events below:

   **Core (user/org/membership sync):** `user.created`, `user.updated`, `user.deleted`, `organization.created`, `organization.updated`, `organization.deleted`, `organizationMembership.created`, `organizationMembership.updated`, `organizationMembership.deleted`

   **Clerk Billing:** `subscription.active`, `subscriptionItem.canceled`, `subscriptionItem.ended`, `subscription.past_due`

5. **Enable Billing** in the Clerk Dashboard. Create **one paid subscription plan for Organizations** only. Do **not** create a free or trial plan in Clerk — the prepaid credit system is managed entirely in-app; a Clerk trial plan would immediately fire `subscription.active` on signup and bypass the prepaid credit period.
6. Set the **Application name** in Settings → General (appears in invitation emails)

For E2E tests in CI, set `CLERK_SECRET_KEY` as a secret. The test infrastructure creates and tears down its own Clerk users and orgs automatically via `global-setup.ts` / `global-teardown.ts`.

### Production instance

The production Clerk instance is created from the development instance using Clerk's **clone** feature, which copies auth methods, password policies, organization settings, session config, and billing plans automatically.

**What must be configured manually in the production instance:**

1. **Domain** — add your custom domain in Clerk Dashboard → Domains. Clerk provides DNS records (CNAME for the Clerk FAPI subdomain + TXT for verification). After DNS propagation and verification, Clerk provisions SSL automatically. The resulting FAPI URL (e.g., `https://clerk.yourdomain.com`) becomes the `CLERK_FRONTEND_API` backend env var — it must exactly match the JWT `iss` claim or all authentication fails.
2. **OAuth providers** — dev uses Clerk's shared OAuth credentials; production requires your own. Register production OAuth apps (Google, GitHub, etc.) and enter the credentials in Clerk Dashboard → Social connections. Clerk provides the redirect URI to add to each provider.
3. **Webhook endpoint** — create in Clerk Dashboard → Webhooks with the production backend URL. Subscribe to all events listed above. Record the new `whsec_...` signing secret.
4. **Bot protection** — enable CAPTCHA (Cloudflare Turnstile) in Clerk Dashboard → Attack protection. Only available in production instances.
5. **Stripe connection** — connect your production Stripe account in Clerk Billing settings. Verify the cloned subscription plan is correct.

**Production API keys** use `pk_live_`/`sk_live_` prefixes (vs. `pk_test_`/`sk_test_` in dev). Update all environment variables accordingly — see [Environment Variables](#environment-variables).

**E2E tests must NOT run against the production instance** — `global-setup.ts` uses `skipPasswordRequirement` (not supported in production) and posts unsigned webhooks (rejected when `TEST=False`).

## Stripe Configuration

Stripe is used for metered usage invoicing (Clerk handles subscription billing).

1. **Connect your Stripe account** to Clerk in the Clerk Dashboard (Billing → Settings). Clerk creates Stripe Customers in your Stripe account when orgs subscribe — this is what enables single card entry.
2. **Configure a Stripe Webhook** endpoint in the [Stripe Dashboard](https://dashboard.stripe.com/webhooks) pointing to `https://your-domain/api/webhooks/stripe/`. Subscribe to: `invoice.paid`, `invoice.payment_failed`, `invoice.overdue`, `invoice.voided`, `checkout.session.completed`, `checkout.session.expired`. When creating the endpoint, select API version **`2026-03-25.dahlia`** to match the version pinned in `StripeMeteredBillingProvider.STRIPE_API_VERSION`.
3. Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in `backend/.env`. When `STRIPE_SECRET_KEY` is set, the backend auto-selects `StripeMeteredBillingProvider`; when unset, it falls back to `MockMeteredBillingProvider`.
4. The Stripe API version is pinned in `StripeMeteredBillingProvider.STRIPE_API_VERSION` (`2026-03-25.dahlia`). Update this version deliberately when upgrading, after verifying compatibility. The webhook endpoint API version must match.

---

## Known Gaps

### 1. Switching SMS/MMS Provider

The app currently uses `WelcorpSMSProvider` (with `MockSMSProvider` available for dev/testing). To switch to a different provider:

- Subclass `SMSProvider` in `backend/app/utils/sms.py`
- Implement `_send_sms_impl()` and `_send_mms_impl()` — return a `SendResult` with `error_code`, `http_status`, `retryable`, `failure_category`
- Optionally override `_send_bulk_sms_impl()` and `_send_bulk_mms_impl()` for native batch support (the base class provides default implementations that loop over the individual send methods)
- For delivery callbacks: override `parse_delivery_callback()`, `validate_callback_request()`, `get_callback_url()`, and `poll_job_status()` — they all return `DeliveryEvent` objects consumed by the existing `process_delivery_event` Celery task
- Set `settings.SMS_PROVIDER_CLASS` to the new provider class path

Note: Welcorp does not provide true handset delivery confirmation — their `SENT` status means "carrier accepted". If the new provider supports handset delivery receipts, map them to `DeliveryEvent(status='delivered')` and the existing pipeline will transition schedules to `DELIVERED` status.


### 2. Remaining Clerk Production Configuration

- Confirm Clerk email templates (invitation, sign-up, magic link) are correctly branded

---

## Azure Deployment

The app deploys to Azure Container Apps (ACA) using Docker images pushed to Azure Container Registry (ACR). Infrastructure is defined as code in Bicep templates (`infra/`). GitHub Actions workflows deploy automatically on push to `development` (dev) and `main` (production).

### Architecture

| Component | Azure Service | Description |
|-----------|---------------|-------------|
| Backend API | ACA Container App (external ingress) | Gunicorn + Uvicorn ASGI workers |
| Celery Worker | ACA Container App (no ingress) | Processes `default,messages` queues |
| Celery Beat | ACA Container App (no ingress, singleton) | `DatabaseScheduler`, dispatches due messages every 60s |
| Frontend | Azure Static Web Apps | Vite build → `dist/` uploaded |
| Database | Azure Database for PostgreSQL | Flexible Server |
| Redis | Azure Cache for Redis | Celery broker + result backend |
| Storage | Azure Blob Storage | MMS media files |
| Registry | Azure Container Registry (Basic) | Docker image storage |

All three backend container apps use the **same Docker image** (`backend/Dockerfile`). The `CONTAINER_ROLE` env var selects the command — see `backend/entrypoint.sh` for the role-based command selection (`api`, `worker`, or `beat`).

### Environments

| Resource | Dev | Production |
|----------|-----|------------|
| ACA Environment | `1reach-dev` | `1reach-prod` |
| Container Apps | `1reach-api-dev`, `1reach-worker-dev`, `1reach-beat-dev` | `1reach-api-prod`, `1reach-worker-prod`, `1reach-beat-prod` |
| API scaling | min 0, max 1 | min 1, max 3 |
| Worker scaling | min 0, max 1 | min 1, max 3 |
| Beat scaling | min 1, max 1 (always-on singleton) | min 1, max 1 |
| Static Web App | Separate (free tier) | Separate |
| Image tags | `dev-<sha>` | `<sha>` |

Dev containers scale to zero when idle to save cost (~30s cold start on first request).

### Branching & CI/CD

```
feature branch
  ├── PR to development → CI: pytest, vitest, tsc -b, E2E (docker-compose in GitHub runners)
  ▼
development branch
  ├── CD: deploy-dev.yml → build image, push to ACR, update dev ACA, E2E against dev URLs
  ▼
main branch
  ├── CD: deploy-prod.yml → replica-test migrations, build image, push to ACR, update prod ACA
  └── Smoke test verifies health + SHA
```

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| `ci.yml` | PRs to `development` | Runs pytest, vitest, typecheck, E2E in GitHub docker runners |
| `deploy-dev.yml` | Push to `development` (`backend/**` or `infra/**`) | Migrations → builds image → Bicep deploy (code + config atomic) → E2E tests |
| `deploy-prod.yml` | Push to `main` (`backend/**` or `infra/**`) | Replica-tests migrations → builds image → Bicep deploy (code + config atomic) → smoke test |
| `deploy-frontend.yml` | Push to `development` or `main` (frontend changes) | Builds Vite → deploys to dev or prod Static Web App |

### Infrastructure as Code (Bicep)

All Azure resources are defined in `infra/`:

```
infra/
├── main.bicep                  # Orchestrator — all params, modules, env vars
├── manage.sh                   # CLI tool (init, preview, stop, start)
├── .env.example                # Template — copy to .env.dev / .env.prod
└── modules/
    ├── identity.bicep          # User-assigned managed identity
    ├── acr.bicep               # Container Registry + AcrPull role (conditional — shared across environments)
    ├── aca-environment.bicep   # ACA Environment + Log Analytics
    └── container-app.bicep     # Reusable container app module
```

**Deployments are CI-driven.** Push to `development` or `main` to deploy. GitHub Actions builds the Docker image, runs migrations, and deploys via Bicep — code, config, secrets, and env vars are all applied in one atomic revision. This avoids config/image mismatch. ACA performs a rolling revision update — it creates a new revision, routes traffic to it once healthy, and deactivates the old revision (`activeRevisionsMode: 'Single'`). No downtime. If nothing changed, Bicep detects no diff and does nothing.

**Local management commands** (non-deployment operations):

```bash
# First-time setup — creates ACA environment, VNet, identity, container apps with placeholder image
./infra/manage.sh init dev

# Preview what Bicep will create/change (dry run — no changes applied)
./infra/manage.sh preview dev

# Stop all containers (scales to zero replicas — no cost while stopped)
# Use when: done working for the day, environment not needed temporarily
./infra/manage.sh stop dev

# Start all containers (restores scaling from .env file)
# Use when: resuming work, need the environment running again
./infra/manage.sh start dev
```

Local `.env` files (`infra/.env.dev`, `infra/.env.prod`) are gitignored and used only by `manage.sh` for `init`, `preview`, `stop`, and `start`. All deployment config lives in GitHub Environment secrets and variables.

### Environment Variables

Env vars are **not baked into the Docker image**. The image is generic — the same image runs in dev and production. Configuration is injected at runtime by ACA, defined in the Bicep templates.

| Config type | Where it lives | Examples |
|-------------|---------------|---------|
| **Secrets** | ACA secrets (Bicep `@secure()` params, values from `.env` files) | `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `STRIPE_SECRET_KEY` |
| **Non-secret env vars** | ACA env vars (Bicep params) | `DEBUG=0`, `LOG_FORMAT=json`, `DB_POOL=true` |
| **Build-time only** | Docker `ARG` | `DEPLOY_SHA` (the only build-time value) |
| **Frontend** | Baked into JS bundle by Vite | `VITE_API_BASE_URL`, `VITE_CLERK_PUBLISHABLE_KEY` |

### GitHub Actions Configuration

The deploy workflows use **GitHub Environments** (`dev` and `prod`) so that the same secret/variable names resolve to different values per environment. Create both environments in Settings → Environments.

**Environment-level secrets** (set per environment — `dev` and `prod` each get their own values):

| Secret | Purpose |
|--------|---------|
| `DJANGO_SECRET_KEY` | Django secret key |
| `POSTGRES_PASSWORD` | Database password |
| `CLERK_SECRET_KEY` | Clerk secret key (`sk_...`) |
| `CLERK_WEBHOOK_SIGNING_SECRET` | Clerk webhook signing secret (`whsec_...`) |
| `STRIPE_SECRET_KEY` | Stripe secret key (`sk_...`) |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `CELERY_BROKER_URL` | Redis URL for Celery broker |
| `AZURE_STORAGE_ACCOUNT_KEY` | Azure Storage account key |
| `WELCORP_PASSWORD` | Welcorp API password |
| `WELCORP_CALLBACK_SECRET` | Welcorp callback verification secret |
| `AZURE_POSTGRES_HOST` | PostgreSQL host (for CI migrations) |
| `AZURE_POSTGRES_DB` | PostgreSQL database name |
| `AZURE_POSTGRES_USER` | PostgreSQL user |
| `AZURE_POSTGRES_PASSWORD` | PostgreSQL password |
| `AZURE_POSTGRES_RESOURCE_GROUP` | PostgreSQL resource group (prod only — for replica/firewall) |
| `AZURE_POSTGRES_SERVER_NAME` | PostgreSQL server name (prod only — for replica/firewall) |

**Environment-level variables** (set per environment):

| Variable | Purpose | Example (dev) | Example (prod) |
|----------|---------|---------------|----------------|
| `RESOURCE_GROUP` | Azure resource group | `v2-1reach-dev` | `v2-1reach-prod` |
| `ENVIRONMENT_NAME` | Environment identifier | `dev` | `prod` |
| `ACR_NAME` | ACR name | `1reachcr` | `1reachcr` |
| `CREATE_ACR` | Create ACR or reuse | `true` | `false` |
| `USE_VNET` | Enable VNet isolation | `false` | `true` |
| `VNET_NAME` | VNet name (if enabled) | *(empty)* | `onereach-vnet-prod` |
| `VNET_CIDR` | VNet CIDR | *(empty)* | `10.0.0.0/24` |
| `ACA_SUBNET_CIDR` | ACA subnet | *(empty)* | `10.0.0.0/26` |
| `PE_SUBNET_CIDR` | Private endpoints subnet | *(empty)* | `10.0.0.64/28` |
| `API_MIN_REPLICAS` | API min replicas | `1` | `1` |
| `API_MAX_REPLICAS` | API max replicas | `1` | `3` |
| `WORKER_MIN_REPLICAS` | Worker min replicas | `1` | `1` |
| `WORKER_MAX_REPLICAS` | Worker max replicas | `1` | `3` |
| `API_CPU` / `API_MEMORY` | API resources | `0.25` / `0.5Gi` | `0.5` / `1Gi` |
| `WORKER_CPU` / `WORKER_MEMORY` | Worker resources | `0.25` / `0.5Gi` | `0.5` / `1Gi` |
| `BEAT_CPU` / `BEAT_MEMORY` | Beat resources | `0.25` / `0.5Gi` | `0.5` / `1Gi` |
| `POSTGRES_HOST` / `POSTGRES_DB` / `POSTGRES_USER` | Database | dev values | prod values |
| `CLERK_FRONTEND_API` | Clerk FAPI URL | dev URL | prod URL |
| `CLERK_AUTHORIZED_PARTIES` | Allowed JWT origins | dev origins | prod origins |
| `ALLOWED_HOSTS` | Django allowed hosts | dev hosts | prod hosts |
| `CORS_ALLOWED_ORIGINS` | CORS allowed origins | dev origins | prod origins |
| `BASE_URL` | Public backend URL | dev URL | prod URL |
| `STORAGE_PROVIDER_CLASS` | Storage backend | class path | class path |
| `AZURE_STORAGE_ACCOUNT_NAME` / `AZURE_CONTAINER` | Blob storage | dev values | prod values |
| `SMS_PROVIDER_CLASS` | SMS backend | class path | class path |
| `WELCORP_BASE_URL` / `WELCORP_USERNAME` | SMS API | values | values |
| `SENTRY_DSN` / `SENTRY_ENVIRONMENT` | Monitoring | DSN / `development` | DSN / `production` |
| `FREE_CREDIT_AMOUNT` / `SMS_RATE` / `MMS_RATE` | Billing | `5.00` / `0.10` / `0.50` | `5.00` / `0.10` / `0.50` |
| `DEBUG` / `TEST` | Django flags | `1` / `True` | `0` / `False` |
| `SKIP_AUTO_MIGRATE` | Entrypoint migration guard | `false` | `true` |

**Repo-level secrets** (shared across environments):

| Secret | Purpose |
|--------|---------|
| `AZURE_CREDENTIALS` | Service principal JSON for `azure/login` |
| `SENTRY_AUTH_TOKEN` | Sentry release tracking (optional) |
| `SENTRY_ORG` / `SENTRY_PROJECT_BACKEND` | Sentry org and project slugs |
| `E2E_VITE_CLERK_PUBLISHABLE_KEY` | Clerk publishable key for E2E tests |
| `E2E_CLERK_SECRET_KEY` | Clerk secret key for E2E tests |
| `AZURE_SWA_TOKEN_DEV` / `AZURE_SWA_TOKEN_PROD` | Static Web App deploy tokens |
| `VITE_CLERK_PUBLISHABLE_KEY_DEV` / `VITE_CLERK_PUBLISHABLE_KEY_PROD` | Clerk publishable keys for frontend builds |
| `VITE_SENTRY_DSN` | Frontend Sentry DSN |

**Repo-level variables** (shared across environments):

| Variable | Purpose |
|----------|---------|
| `ACR_LOGIN_SERVER` | e.g., `1reachcr.azurecr.io` |
| `VITE_API_BASE_URL_DEV` | Dev API URL (for health checks + E2E) |
| `VITE_API_BASE_URL_PROD` | Prod API URL (for health checks) |
| `E2E_BASE_URL_DEV` | Dev frontend URL (for E2E) |

#### Creating AZURE_CREDENTIALS

```bash
az ad sp create-for-rbac \
  --name "github-deploy-1reach" \
  --role contributor \
  --scopes /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP_NAME> \
  --json-auth
```

The service principal also needs `AcrPush` role on the ACR for image pushes.

### Step-by-Step Setup

#### Prerequisites

You need an existing Azure resource group with PostgreSQL Flexible Server, Azure Cache for Redis, and Azure Blob Storage already provisioned. The Bicep templates create the ACA-specific resources (ACR, ACA environment, container apps, managed identity, Log Analytics) inside that resource group.

#### 1. Create and fill in the environment config

```bash
cp infra/.env.example infra/.env.dev
```

Edit `infra/.env.dev` with all values — infrastructure params (scaling, CPU/memory), secrets (DB password, API keys), and app config (Clerk URLs, Sentry DSN, etc.). See `.env.example` for the full list. This file is used by `manage.sh` for init/preview/stop/start operations.

#### 2. Initialise infrastructure

```bash
# Dry run — see what will be created
./infra/manage.sh preview dev

# First-time setup (creates ACR, ACA environment, VNet, identity, container apps with placeholder images)
./infra/manage.sh init dev
```

#### 3. Deploy the backend

Populate the GitHub `dev` environment with all secrets and variables listed in [GitHub Actions Configuration](#github-actions-configuration), then push to `development`:

```bash
git push origin development
```

This triggers `deploy-dev.yml` which builds the Docker image, runs migrations, and deploys via Bicep (code + config atomic). The old revision is automatically deactivated (`activeRevisionsMode: 'Single'`).

#### 4. Verify

```bash
# Check the API container logs
az containerapp logs show --name onereach-api-dev --resource-group $RG --follow

# Health check (DB + Redis connectivity)
curl https://<api-fqdn>/api/health/

# Smoke test (DB write + Redis write + deploy version)
curl https://<api-fqdn>/api/health/smoke/
```

The API FQDN is shown in the `deploy` output, or find it in the Azure Portal under the container app's Overview page.

#### 5. Configure Clerk and Stripe webhooks

- **Clerk Dashboard → Webhooks → Add Endpoint:** URL: `https://<api-fqdn>/api/webhooks/clerk/`. Subscribe to all events listed in [Clerk Configuration](#clerk-configuration).
- **Stripe Dashboard → Webhooks → Add endpoint:** URL: `https://<api-fqdn>/api/webhooks/stripe/`. API version `2026-03-25.dahlia`. Subscribe to events listed in [Stripe Configuration](#stripe-configuration).

#### 6. Grant AcrPush to GitHub Actions service principal

Required for the CD workflows to push images:

```bash
az role assignment create --assignee <SP_APP_ID> --role AcrPush --scope <ACR_RESOURCE_ID>
```

#### 7. Set GitHub Environment secrets and variables

Create a `dev` environment in Settings → Environments. Populate all secrets and variables listed in the [GitHub Actions Configuration](#github-actions-configuration) section above. The deploy workflow will not succeed until all required values are set.

#### 8. Test the full flow

- Sign in via Clerk on the dev frontend
- Send a test message — verify schedule transitions
- Check billing, webhook delivery, worker/beat logs

#### 9. Set up production

Production uses its own resource group, ACA environment, Redis, and PostgreSQL database — but **shares the ACR** with dev. The same Docker image is deployed to both environments, so E2E tests on dev validate the exact image that runs in prod.

1. **Azure prerequisites:**
   - Create resource group (e.g., `v2-1reach-prod`)
   - Create a separate Redis instance (enable access key auth + "Allow Azure services")
   - Create a database on the production PostgreSQL server
   - Check `max_connections` on the prod PostgreSQL — increase if low
   - Create a production Static Web App (free tier)

2. **Create `infra/.env.prod`** (for `manage.sh init`/`preview`/`stop`/`start`):
   ```bash
   cp infra/.env.dev infra/.env.prod
   ```
   Key differences from dev:
   - `RESOURCE_GROUP` → prod resource group
   - `ENVIRONMENT_NAME=prod`
   - `CREATE_ACR=false` (reuse dev's ACR)
   - `ACR_LOGIN_SERVER=1reachcr.azurecr.io`
   - `DEBUG=0`, `TEST=False`
   - Higher scaling: `API_MAX_REPLICAS=3`, `WORKER_MAX_REPLICAS=3`
   - More resources: `API_CPU=0.5`, `API_MEMORY=1Gi`, `WORKER_CPU=0.5`, `WORKER_MEMORY=1Gi`
   - Production DB, Redis, Clerk, Stripe, and Sentry values
   - `SENTRY_ENVIRONMENT=production`
   - New strong `DJANGO_SECRET_KEY`

3. **Provision and deploy:**
   ```bash
   # Initialise infrastructure (local — one-time)
   ./infra/manage.sh preview prod
   ./infra/manage.sh init prod

   # Create 'prod' GitHub Environment with all secrets and variables
   # (see GitHub Actions Configuration section above)

   # Deploy via CI
   git push origin main
   curl https://<prod-api-fqdn>/api/health/
   ```

4. **Grant prod identity access to shared ACR:**
   ```bash
   ACR_ID=$(az acr show --name 1reachcr --resource-group v2-1reach-dev --query "id" -o tsv)
   PROD_PRINCIPAL=$(az identity show --name onereach-identity-prod --resource-group v2-1reach-prod --query "principalId" -o tsv)
   az role assignment create --assignee $PROD_PRINCIPAL --role AcrPull --scope $ACR_ID
   ```

5. **Configure Clerk + Stripe webhooks** with the prod API FQDN — see [Clerk Production instance](#production-instance) and [Stripe Configuration](#stripe-configuration)

6. **Set GitHub variables** — set `VITE_API_BASE_URL_PROD` (repo-level) and `AZURE_SWA_TOKEN_PROD` (repo-level secret). Create the `prod` GitHub Environment with all secrets and variables listed in [GitHub Actions Configuration](#github-actions-configuration)

7. **Update prod env vars** — in the `prod` GitHub Environment variables, set `ALLOWED_HOSTS` and `BASE_URL` with the prod API FQDN, `CLERK_AUTHORIZED_PARTIES` and `CORS_ALLOWED_ORIGINS` with the custom frontend domain, production Clerk keys (`sk_live_`, `CLERK_FRONTEND_API`), and production Stripe keys in the environment secrets. Then push to `main` to deploy via CI

### Migration Safety (production only)

The `deploy-prod.yml` workflow checks for pending migrations and, if found, tests them on a disposable PostgreSQL replica before applying to production:

```
1. Add GitHub runner IP to PostgreSQL firewall
2. Check for pending migrations
   → If NONE: skip to step 8
3. Create DB replica → promote to read-write
4. Test migration on replica
   → If FAILS: abort (production untouched)
5. Backup production DB
6. Apply migration to production (proven safe in step 4)
7. Delete replica (cleanup)
8. Remove firewall rule (cleanup)
9. Build image, deploy to ACA, verify health
```

The replica-test step requires General Purpose or Memory Optimized PostgreSQL tier. On Burstable tier, the workflow skips directly to backup + migrate.

`entrypoint.sh` includes a migration guard controlled by `SKIP_AUTO_MIGRATE`:
- **Production** (`SKIP_AUTO_MIGRATE=true`): The API container **refuses to start** if pending migrations are detected, forcing all migrations through the CD pipeline (which tests on a replica and creates a backup first).
- **Development** (`SKIP_AUTO_MIGRATE=false`): The API container auto-applies pending migrations on startup as a convenience safety net.

### Database Connection Pooling

The backend uses **psycopg3 with Django's native connection pool** (`DATABASES["default"]["POOL"]`). This is essential for ASGI deployments — without it, Django under Uvicorn spawns a new thread per request, and each thread opens a persistent DB connection. Under load, connections accumulate unboundedly until PostgreSQL runs out of slots.

Pool sizes are set per container app via env vars in the Bicep templates:

| Container | `DB_POOL_MIN_SIZE` | `DB_POOL_MAX_SIZE` |
|-----------|--------------------|--------------------|
| API | 2 | 8 |
| Worker | 1 | 4 |
| Beat | 1 | 2 |

#### Connection budget

With default settings (1 API replica with 2 gunicorn workers, 1 worker replica, 1 beat replica):

| Process | Instances | Pool max_size | Total connections |
|---|---|---|---|
| Web workers (Uvicorn) | 2 | 8 | 16 |
| Celery workers | 2 | 4 | 8 |
| Celery Beat | 1 | 2 | 2 |
| **Total** | | | **26** |

Azure PostgreSQL Flexible Server typically allows 50–100+ connections depending on tier, so this leaves ample headroom.

#### Scaling horizontally

When ACA auto-scales to multiple replicas, each replica creates its own pools. The total connection count multiplies:

| API replicas | Pool max_size | Web connections | + Celery/Beat | Total |
|---|---|---|---|---|
| 1 (default) | 8 | 16 | 10 | **26** |
| 2 | 8 | 32 | 10 | **42** |
| 3 (max) | 8 | 48 | 10 | **58** |

If you scale beyond 3 API replicas, reduce `DB_POOL_MAX_SIZE` proportionally via the Bicep params to stay within PostgreSQL's connection limit. If you need more than ~100 concurrent DB connections, enable [PgBouncer on PostgreSQL Flexible Server](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-pgbouncer).

#### Troubleshooting

- **`PoolTimeout` errors in Sentry:** The pool is full and requests are waiting longer than `DB_POOL_TIMEOUT` (default 10s). Increase `DB_POOL_MAX_SIZE` or investigate slow queries.
- **`remaining connection slots are reserved`:** Total connections across all replicas exceed PostgreSQL's `max_connections`. Reduce `DB_POOL_MAX_SIZE`, scale down, or enable PgBouncer.
- **Celery tasks hanging after deploy:** Forked worker processes may have inherited stale connections. The `worker_process_init` signal handler in `celery.py` closes these automatically, but if you see issues, restart the worker container app.

### Monitoring & Alerts

#### Sentry

**Backend:** Set `SENTRY_DSN` on all container apps (via Bicep env vars). `settings.py` initialises `sentry_sdk` with `DjangoIntegration()` (request context, unhandled exceptions) and `CeleryIntegration()` (task failures with task name, args, retry count). A `task_failure` Celery signal handler also logs all task failures at ERROR level. Optional env vars: `SENTRY_ENVIRONMENT` (default `production`), `SENTRY_TRACES_SAMPLE_RATE` (default `0.1`).

**Frontend:** `@sentry/react` initialised in `main.tsx` (conditional on `VITE_SENTRY_DSN`). The root error boundary in `__root.tsx` calls `Sentry.captureException()`. `VITE_SENTRY_DSN` is baked into the JS bundle at build time.

**CI/CD releases:** Both deploy workflows create a Sentry release tagged with the git SHA via `getsentry/action-release@v3` (skipped if `SENTRY_AUTH_TOKEN` is not set).

#### Log Analytics

Each ACA environment has a linked Log Analytics workspace (provisioned by Bicep). Container logs are automatically shipped there. Use the Azure Portal → Log Analytics → Logs to query.

#### Recommended alert rules

| Alert | Condition | Threshold | Severity |
|-------|-----------|-----------|----------|
| API errors | HTTP 5xx count | > 10 in 5 minutes | Sev 1 |
| API latency | Avg response time | > 5 seconds for 5 minutes | Sev 2 |
| Container restarts | Restart count | > 3 in 10 minutes | Sev 1 |
| Beat stopped | No `dispatch_due_messages` log | > 5 minutes gap | Sev 1 |

### Gotchas & Troubleshooting

#### Django / ASGI
- **`SECURE_SSL_REDIRECT` must NOT be True** — ACA terminates TLS at the ingress. The container receives plain HTTP internally. Setting it `True` causes an infinite redirect loop.
- **Uvicorn lifespan** — `app.worker.Worker` sets `lifespan=off` to prevent Django ASGI `ValueError` on every worker start. Django (as of 6.0) doesn't handle ASGI lifespan events.

#### Frontend
- **`VITE_API_BASE_URL` must include `https://`** — it's baked into the JS bundle at build time. Without the protocol, the browser resolves it as a relative path. Must NOT have a trailing slash.

#### CORS / Auth
- **`CORS_ALLOWED_ORIGINS` — no trailing slash** — Django-cors-headers silently rejects origins with a trailing slash. Use `https://<host>.azurestaticapps.net`, not `https://<host>.azurestaticapps.net/`.
- **`CLERK_AUTHORIZED_PARTIES`** — the backend validates the `azp` claim in Clerk JWTs against this comma-separated list. If the frontend origin (custom domain or Azure SWA URL) is missing, all authenticated API calls return 403. In production, this must match the custom domain exactly (e.g., `https://yourdomain.com`).
- **Clerk webhook URL** — `POST /api/webhooks/clerk/` (trailing slash required — Django's `APPEND_SLASH` doesn't work for POST requests).
- **Clerk webhook signing secret** — must exactly match the signing secret in the Clerk Dashboard. A mismatch causes Svix verification to fail → 400 → webhooks silently not processed.

#### Azure Cache for Redis
- **ACA outbound IPs and Redis firewall** — ACA on the Consumption plan uses shared outbound IPs that aren't predictable. If your Redis firewall blocks all connections, enable "Allow public network access from Azure services and resources" in Azure Cache for Redis → Networking. This is what allows ACA (and App Services) to connect without explicit IP rules. Without it, the health endpoint hangs on the Redis ping and startup probes fail.
- **Access key authentication disabled by default** — new Azure Redis instances have access key auth disabled. Celery connections fail with "invalid username-password pair". Fix: Azure Cache for Redis → Authentication → untick "Disable Access Keys Authentication".
- **Use `rediss://` (TLS) on port `6380`** — Azure Redis requires TLS. Connection URL format: `rediss://:<access-key>@<redis-name>.redis.cache.windows.net:6380/0`.
- **Do not URL-encode the access key** — Azure Redis access keys may end in `=`. Do **not** URL-encode `=` to `%3D` — `redis-py` handles `=` correctly. URL-encoding causes auth failures.
- **`redis.from_url()` and TLS** — the `_ensure_redis_ssl()` helper in `settings.py` handles `ssl_cert_reqs=CERT_NONE` for Celery, but direct `redis.from_url()` calls (e.g., health endpoint) need explicit `ssl_cert_reqs=ssl.CERT_NONE` as a keyword argument. See `health.py` for the pattern.

#### Bicep Deploy Time
- **Bicep deployments add ~1-3 minutes** to each deploy compared to `az containerapp update` (~30s). This is the cost of atomic config + code deploys. If nothing changed, the ARM deployment completes quickly as a no-op.

#### Celery Beat
- **Beat must be a singleton** — `maxReplicas: 1` in Bicep. `DatabaseScheduler` provides some protection against duplicates but should not be relied upon.

#### Frontend deploy
- **`skip_app_build: true`** — the `Azure/static-web-apps-deploy@v1` action runs its own build by default without GitHub secrets. The workflow builds first with `npm run build` (where `VITE_*` secrets are available), then deploys with `skip_app_build: true`.

#### Migration recovery
The `deploy-prod.yml` workflow creates a PostgreSQL backup before every migration. If a migration fails mid-apply:

1. Find the backup in Azure Portal → PostgreSQL Flexible Server → Backups
2. Restore: `az postgres flexible-server restore --resource-group <RG> --name <new-server> --source-server <current-server> --backup-name <pre-deploy-YYYYMMDD-HHMMSS>`
3. Update `POSTGRES_HOST` in the Bicep params and re-deploy
4. Fix the migration and redeploy

To manually rollback a specific migration: `uv run python manage.py migrate <app_label> <previous_migration_name>` (only works if the migration has a `reverse()` operation).

#### PostgreSQL Burstable tier
The replica-tested migration flow requires General Purpose or Memory Optimized tier. On Burstable tier, replica creation fails with "Read replica is not supported for the Burstable pricing tier". The workflow gracefully skips the replica test and falls back to backup + migrate directly.

---

See [v1_migration.md](v1_migration.md) for v1 → v2 migration details.
