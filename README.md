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
- Manual retry — failed messages can be retried from the schedule page UI (billing re-checked, credits re-charged for trial orgs)
- Scheduled sends — Celery beat dispatches due messages every 60 s
- Org user management — invite, deactivate, grant/revoke admin
- Usage stats dashboard
- Billing system — trial credits on signup, subscribed mode with metered tracking, monthly spending limits, transaction history, credit refunds on failed sends, inline subscription management via Clerk PricingTable, automated metered invoicing via Stripe

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
| `SMS_RATE` | No | Default cost per SMS message part in dollars (default: `0.05`). Can be overridden per org via Config. |
| `MMS_RATE` | No | Default cost per MMS send in dollars (default: `0.20`). Can be overridden per org via Config. |
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
│   ├── models.py          # Contact, Group, Template, Schedule, Organisation, User, Config, CreditTransaction, Invoice
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
└── tests/                 # 739 tests
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

**Worker startup:** `celery.py` calls `django.setup()` after `app.config_from_object(...)` and before any model imports. This is required because the worker starts a fresh Python process where Django's app registry is not yet populated. Without it, model imports raise `AppRegistryNotReady` and the worker exits silently, leaving all dispatched messages stuck in QUEUED. All three startup scripts include DB readiness wait loops (up to 2.5 minutes). Worker and beat scripts also start a background HTTP server on `$PORT` so Azure App Service health probes get a response (without this, Azure kills the container — see [gotchas](#workerbbeat-require-an-http-listener)). Lifecycle events are logged via Celery signals: `beat_init`, `worker_ready`, `worker_shutting_down`, `task_failure`. Shell-level SIGTERM traps in the startup scripts log when Azure sends a graceful shutdown signal. The API uses `app.worker.Worker` (a `UvicornWorker` subclass with `lifespan=off`) because Django doesn't handle ASGI lifespan events — without this, Sentry is flooded with `ValueError` on every worker start (see [gotchas](#uvicorn-lifespan-events)).

**Failure classification:** `failure_classifier.py` maps provider errors to `FailureCategory` (permanent: `invalid_number`, `opt_out`, `blacklisted`, etc.; transient: `network_error`, `rate_limited`, `server_error`, etc.). Permanent failures skip retries and trigger `refund_usage()`. MMS media blobs are **not** deleted on failure — they are retained for 7 days to allow manual retry, then cleaned up by the `cleanup_stale_media_blobs` daily beat task.

**Billing system:** `Organisation` has `credit_balance` (Decimal), `billing_mode` (`trial` | `subscribed` | `past_due`), and `billing_customer_id` (Stripe Customer ID). Every billable action (send or grant) creates a `CreditTransaction` row. `billing.py` exposes `check_can_send`, `record_usage`, and `refund_usage`. SMS costs `message_parts × rate`; MMS costs `1 × rate`. Rates default to the global `SMS_RATE`/`MMS_RATE` settings but can be overridden per organisation using the `Config` model (see [Per-org rate overrides](#per-org-rate-overrides) below). Each `CreditTransaction` stores the `unit_rate` used at the time of recording, so invoices remain accurate even if an org's rate changes mid-month. Trial credits are reserved at HTTP dispatch time; on terminal failure `refund_usage()` restores the balance idempotently. Subscribed orgs record usage on `SENT`. `check_can_send` blocks all sends when `billing_mode='past_due'`. Clerk Billing handles subscription lifecycle: `subscription.active` sets `billing_mode='subscribed'` and clears the Clerk `billing_suspended` metadata flag; `subscriptionItem.canceled`/`subscriptionItem.ended` reverts to `'trial'`; `subscription.past_due` sets `billing_mode='past_due'` and sets `billing_suspended=True` in Clerk org metadata. The billing page has a "Manage Plan" button that opens a dialog with Clerk's `PricingTable` component, allowing admins to subscribe, switch, or cancel inline.

**Metered billing (Stripe):** Clerk does not support metered billing, so Stripe handles per-message usage invoicing. When an org subscribes through Clerk, Clerk creates a Stripe Customer in the app's Stripe account with `metadata.organization_id` set to the Clerk org ID. The `_handle_subscription_active` webhook handler searches Stripe for this customer and saves the `billing_customer_id` on the `Organisation`; if the lookup fails (timing), a `link_billing_customer` Celery task retries with exponential backoff. Monthly invoices are generated by a `generate_monthly_invoices` beat task (runs on the 1st of each month): it aggregates `CreditTransaction` records (usage minus refunds) by format, builds line items, and creates a Stripe Invoice via the `MeteredBillingProvider` interface. Stripe auto-charges the card saved during Clerk subscription signup. The `Invoice` model tracks invoice status locally; Stripe webhooks (`invoice.paid`, `invoice.payment_failed`, `invoice.overdue`, `invoice.voided`) update the status via `StripeWebhookView`. If payment fails or the invoice becomes overdue, the org is set to `past_due` (blocking all sends); when the customer pays and no other uncollectable invoices remain, the org is restored to `subscribed` (this guard prevents incorrectly restoring an org that was set to `past_due` by Clerk for subscription reasons rather than Stripe payment failure). The metered billing provider is pluggable via `settings.METERED_BILLING_PROVIDER_CLASS` (same pattern as `SMS_PROVIDER_CLASS`), with `MockMeteredBillingProvider` for dev/testing and `StripeMeteredBillingProvider` for production.

**Per-org rate overrides:** By default all organisations are billed at the global `SMS_RATE` and `MMS_RATE` from settings. To give a specific org a custom rate, create a `Config` row for that organisation with `name` set to `{format}_rate` and `value` set to the dollar amount as a decimal string. The `get_rate(format, org)` function checks for a matching Config override first and falls back to the global setting.

| Config `name` | Effect | Example `value` |
|---|---|---|
| `sms_rate` | Override SMS cost per message part | `0.03` |
| `mms_rate` | Override MMS cost per send | `0.10` |

Set via the Configs API (`POST /api/configs/` with `{ "name": "sms_rate", "value": "0.03" }`) or Django admin. The override only applies to the org that owns the Config row — other orgs continue using the global default. Removing the Config row reverts the org to the global rate. When a rate changes, only future sends are affected; past `CreditTransaction` records retain the `unit_rate` they were recorded at, so invoices always reflect the rate that was in effect at time of send.

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
| SMS/MMS | `POST /api/sms/send/` → 202, `POST /api/sms/send-to-group/` → 202, `POST /api/sms/send-mms/` → 202, `POST /api/sms/upload-file/` |
| Stats | `GET /api/stats/monthly/` |
| Billing | `GET /api/billing/summary/` — balance, monthly usage by format, transaction history, latest invoice (admin only) |
| Configs | `GET/POST/PUT/PATCH/DELETE /api/configs/`, `GET/PUT/PATCH/DELETE /api/configs/:id/` — per-org key-value settings (e.g. `monthly_limit`, `sms_rate`, `mms_rate`) |
| Webhooks | `POST /api/webhooks/clerk/`, `POST /api/webhooks/sms-delivery/`, `POST /api/webhooks/stripe/` |
| Health | `GET /api/health/` (DB + Redis connectivity), `GET /api/health/smoke/` (DB write + Redis write + deploy version) |

All endpoints require Clerk JWT authentication except health/smoke endpoints (unauthenticated). Most require `IsOrgMember`; user management and billing endpoints require `IsOrgAdmin`.

---

## Testing

### Backend

```bash
docker compose exec backend python -m pytest tests/ -x -q
```

741 tests. Run with `-v` for verbose output or `--cov` for a coverage report. If the schema has changed since the last run, rebuild the test database first:

```bash
docker compose exec backend python -m pytest --create-db tests/ -q
```

### Frontend (unit + integration)

```bash
docker compose exec frontend npx vitest run
```

447 tests. Uses Vitest + MSW for API mocking. Covers API modules, components, and route integration tests.

### Frontend (E2E)

```bash
docker compose exec frontend npx playwright test
```

89 Playwright tests covering all user flows: contacts (CRUD + message history + send modal), groups (CRUD + edit + member removal + schedule modal), templates (CRUD + edit + pre-fill verification), schedules (navigation + status badges + cancellation + row expansion + pagination), send SMS (form validation + recipient count + template selection), send pipeline (SMS/MMS success + billing gates + group send + status display), summary (stats table + monthly limit), billing (balance display + transaction history + exhausted warning), billing-stripe (subscribe via PricingTable with Stripe test card + invoice generation + invoice display + cancel subscription), and users (table + invite + role/status management). Tests hit the **real backend** (Django + PostgreSQL) — no `page.route()` mocking.

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

1. Create an application in the [Clerk Dashboard](https://dashboard.clerk.com)
2. Enable **Organizations** in the Clerk Dashboard
3. Enable **Organization Invitations** (Organizations → Settings)
4. Configure your **Webhook** endpoint to point to `https://your-domain/api/webhooks/clerk/` and subscribe to all events below:

   **Core (user/org/membership sync):** `user.created`, `user.updated`, `user.deleted`, `organization.created`, `organization.updated`, `organization.deleted`, `organizationMembership.created`, `organizationMembership.updated`, `organizationMembership.deleted`

   **Clerk Billing:** `subscription.active`, `subscriptionItem.canceled`, `subscriptionItem.ended`, `subscription.past_due`

5. **Enable Billing** in the Clerk Dashboard. Create **one paid subscription plan for Organizations** only. Do **not** create a free or trial plan in Clerk — the $10 credit trial is managed entirely in-app; a Clerk trial plan would immediately fire `subscription.active` on signup and bypass the credit trial.
6. Set the **Application name** in Settings → General (appears in invitation emails)

For E2E tests in CI, set `CLERK_SECRET_KEY` as a secret. The test infrastructure creates and tears down its own Clerk users and orgs automatically via `global-setup.ts` / `global-teardown.ts`.

## Stripe Configuration

Stripe is used for metered usage invoicing (Clerk handles subscription billing).

1. **Connect your Stripe account** to Clerk in the Clerk Dashboard (Billing → Settings). Clerk creates Stripe Customers in your Stripe account when orgs subscribe — this is what enables single card entry.
2. **Configure a Stripe Webhook** endpoint in the [Stripe Dashboard](https://dashboard.stripe.com/webhooks) pointing to `https://your-domain/api/webhooks/stripe/`. Subscribe to: `invoice.paid`, `invoice.payment_failed`, `invoice.overdue`, `invoice.voided`. When creating the endpoint, select API version **`2026-03-25.dahlia`** to match the version pinned in `StripeMeteredBillingProvider.STRIPE_API_VERSION`.
3. Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in `backend/.env`. When `STRIPE_SECRET_KEY` is set, the backend auto-selects `StripeMeteredBillingProvider`; when unset, it falls back to `MockMeteredBillingProvider`.
4. The Stripe API version is pinned in `StripeMeteredBillingProvider.STRIPE_API_VERSION` (`2026-03-25.dahlia`). Update this version deliberately when upgrading, after verifying compatibility. The webhook endpoint API version must match.

---

## Known Gaps

These features are not yet implemented and are required before production use:

### 1. Switching SMS/MMS Provider

The app currently uses `WelcorpSMSProvider` (with `MockSMSProvider` available for dev/testing). To switch to a different provider:

- Subclass `SMSProvider` in `backend/app/utils/sms.py`
- Implement `_send_sms_impl()` and `_send_mms_impl()` — return a `SendResult` with `error_code`, `http_status`, `retryable`, `failure_category`
- Optionally override `_send_bulk_sms_impl()` and `_send_bulk_mms_impl()` for native batch support (the base class provides default implementations that loop over the individual send methods)
- For delivery callbacks: override `parse_delivery_callback()`, `validate_callback_request()`, `get_callback_url()`, and `poll_job_status()` — they all return `DeliveryEvent` objects consumed by the existing `process_delivery_event` Celery task
- Set `settings.SMS_PROVIDER_CLASS` to the new provider class path

Note: Welcorp does not provide true handset delivery confirmation — their `SENT` status means "carrier accepted". If the new provider supports handset delivery receipts, map them to `DeliveryEvent(status='delivered')` and the existing pipeline will transition schedules to `DELIVERED` status.

### 2. Production Deployment

Docker is used for local development only. The production target is Azure:

| Component | Target |
|-----------|--------|
| Backend (Django) | Azure App Service — Linux, Python 3.12, `gunicorn -k uvicorn.workers.UvicornWorker` |
| Frontend (React) | Azure Static Web Apps |
| Database | Azure Database for PostgreSQL (Flexible Server) |
| Redis / Celery broker | Azure Cache for Redis |
| Celery worker | Azure App Service (separate instance, custom startup command) |
| Celery beat | Azure App Service (separate instance, `django-celery-beat` DB scheduler) |

**Changes required before first deploy — all completed:**

- ~~`backend/requirements.txt` — add `gunicorn`, `uvicorn[standard]`, `whitenoise[brotli]`, `django-celery-beat`~~ ✓
- ~~`backend/app/settings.py` — fix `DEBUG` parsing, add `STATIC_ROOT`, `WhiteNoiseMiddleware`, security headers (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, `X_FRAME_OPTIONS`, `SECURE_CONTENT_TYPE_NOSNIFF`), switch Celery beat to `DatabaseScheduler`~~ ✓
- ~~`backend/app/urls.py` — gate Swagger/OpenAPI behind `DEBUG=True`; add `GET /api/health/` (DB + Redis liveness check for App Service health probe)~~ ✓
- ~~`backend/startup.sh`, `startup-worker.sh`, `startup-beat.sh` — Azure App Service startup commands~~ ✓
- ~~`frontend/staticwebapp.config.json` — SPA fallback routing for Azure Static Web Apps~~ ✓
- ~~`frontend/vite.config.ts` — explicit `build.outDir` and `sourcemap: false`~~ ✓
- ~~Frontend UX fixes: `_layout.send.index.tsx` (blank page), `__root.tsx` (raw JSON error boundary), missing `errorComponent` on billing/users routes~~ ✓
- ~~`.github/workflows/` — CI (pytest + vitest on PRs) and CD (deploy to Azure on `main`)~~ ✓
- ~~TypeScript build errors — fix ~35 errors caught by `tsc -b` (unused imports, missing status colors, null safety, HeadlessUI/TanStack type conflicts)~~ ✓
- ~~Frontend security headers — `Content-Security-Policy` (allows self, Clerk, Google Fonts, Azure Blob) and `Permissions-Policy` (denies camera, mic, geo, etc.) in `staticwebapp.config.json`~~ ✓
- ~~Backend Sentry — `sentry-sdk[django,celery]` with explicit `DjangoIntegration()` + `CeleryIntegration()`, `task_failure` signal handler, permanent failures logged at ERROR~~ ✓
- ~~Frontend Sentry — `@sentry/react` init in `main.tsx`, `Sentry.captureException` in root error boundary, `VITE_SENTRY_DSN` env var~~ ✓
- ~~Smoke test endpoint — `GET /api/health/smoke/` (DB write/read via ORM + Redis write/read, rolled back via `transaction.set_rollback`)~~ ✓
- ~~Deploy version tracking — `DEPLOY_SHA` baked into `health.py` by CI, returned in health/smoke responses; deploy workflow polls until new SHA is live~~ ✓
- ~~ASGI lifespan fix — `app.worker.Worker` subclass with `lifespan=off` (Django doesn't handle uvicorn lifespan events)~~ ✓
- ~~CI/CD Sentry releases — `getsentry/action-release` in both deploy workflows, `VITE_SENTRY_DSN` passed at frontend build time~~ ✓

**Azure provisioning — see [Azure Deployment](#azure-deployment) below.**

### 3. ~~Metered Billing~~ ✓

Metered usage invoicing is implemented via Stripe. Clerk handles subscription billing; Stripe collects per-message usage payments. See the **Metered billing (Stripe)** section above for details. The metered billing provider is pluggable — to switch from Stripe, implement the `MeteredBillingProvider` ABC in `backend/app/utils/metered_billing.py` and update `settings.METERED_BILLING_PROVIDER_CLASS`.

### 4. Remaining Clerk Production Configuration

From codebase inspection, these items need to be addressed before production:

- Set `CLERK_AUTHORIZED_PARTIES`, `CORS_ALLOWED_ORIGINS`, and `ALLOWED_HOSTS` in `backend/.env` to include the production frontend URL (all three are env-var driven; current values are `localhost` / `localhost:5173`)
- Confirm Clerk email templates (invitation, sign-up, magic link) are correctly branded for the corporate account before sending to real users
- Configure Clerk to require verified email addresses before allowing users to be created or organisations to be joined (Clerk Dashboard → User & Authentication → Email, Phone, Username → enable "Require verified email address")

### 5. Staging-to-Production Readiness

The current Azure deployment is a working staging environment. The following items are needed before serving production traffic.

#### Infrastructure (Azure Portal)

- **Deployment slots** — Add a staging slot to the API App Service. Deploy to staging first, verify health, then swap staging→production for zero-downtime deploys. Worker and beat don't need slots (they have no user-facing traffic; the stop/start cycle is acceptable).
- **Custom domains + SSL** — Configure custom domains for both the Static Web App (frontend) and API App Service (backend). Azure provides free managed SSL certificates for App Service custom domains. Update `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CLERK_AUTHORIZED_PARTIES`, and Clerk Dashboard origins to match.
- **PostgreSQL High Availability** — Enable HA on the Flexible Server (zone-redundant or same-zone standby). This provides automatic failover if the primary instance fails. Verify the automated backup retention period (default 7 days) and test a point-in-time restore to confirm backups work.
- **Application Insights** — See [Monitoring & Alerts](#monitoring--alerts) below.
- **Azure health check probes** — Configure custom health check paths in the Azure Portal for each App Service (Settings → Health check → Path: `/api/health/` for API, `/` for worker/beat). This is more reliable than relying on Always On pings alone — Azure uses health check probes to route traffic away from unhealthy instances during scaling.

#### Configuration

- **Sentry** — Set `SENTRY_DSN` and `SENTRY_ENVIRONMENT=production` on all three App Services. Optional: adjust `SENTRY_TRACES_SAMPLE_RATE` (default `0.1` = 10% of requests traced).
- **CORS** — Tighten `CORS_ALLOWED_ORIGINS` to the production frontend domain only (no `localhost`).
- **Security cookies** — Verify `SESSION_COOKIE_SECURE=True` and `CSRF_COOKIE_SECURE=True` are set on all App Services (they're env-var driven in `settings.py`).

#### CI/CD improvements

- ~~**Post-deploy smoke test**~~ ✓ — The `verify-health` job now polls `GET /api/health/smoke/` which tests DB write/read (ORM + rollback) and Redis write/read/delete. It also checks the `DEPLOY_SHA` version field to confirm the new instance (not the old one) is serving before passing.
- **Secret rotation** — Rotate publish profiles and service principal credentials quarterly. Rotate immediately if a team member with access leaves.
- **Zero-downtime deployment with deployment slots** — see [Production Zero-Downtime Strategy](#production-zero-downtime-strategy) below. The current dev platform already has replica-tested migrations implemented.

#### Not needed

- **Deployment Center Source** — GitHub Actions workflows are the deployment mechanism. Deployment Center in the Azure Portal does not need a configured source.
- **Redis AOF persistence** — The `dispatch_due_messages` beat task recovers stale QUEUED and PROCESSING schedules every 60 seconds. If Redis loses data (restart, flush), tasks are re-dispatched within 1-2 minutes. The brief delay is acceptable and doesn't cause data loss.

#### Migration Safety (implemented)

The deploy workflow checks for pending migrations against the production DB and, if any are found, tests them on a disposable replica before applying to production. Implemented in `deploy-backend.yml`, runs automatically on every deploy:

```
1. Temporarily add GitHub runner IP to PostgreSQL firewall
2. Check for pending migrations (manage.py migrate --check against production DB)
   → If NONE: skip to step 8 (no replica, no backup, fast path)
3. Create DB replica → promote to read-write
4. Test migration on replica
   → If FAILS: delete replica, remove firewall rule, abort (production untouched)
5. Backup production DB (on-demand, taken right before real migration)
6. Run migration on production DB (proven safe in step 4)
7. Delete replica (cleanup)
8. Remove firewall rule (cleanup)
9. Deploy code, restart services, verify health (existing flow)
```

Cleanup steps (7-8) run with `if: always()` so they execute even if earlier steps fail. When there are no pending migrations (the common case), only steps 1-2 and 8 run (~10 seconds total).

The PostgreSQL server may host databases for other apps. This is safe because:
- The replica is always temporary — created and deleted within the workflow
- The replica is never promoted to production — it's only used for testing
- Other apps' databases on the original server are never touched
- The on-demand backup creates a snapshot, not a new server

`startup.sh` has a safety-net migration check: if migrations were somehow missed by the workflow (e.g., manual deploy), it detects and applies them on startup.

**Secrets required:** `AZURE_POSTGRES_HOST`, `AZURE_POSTGRES_SERVER_NAME`, `AZURE_POSTGRES_RESOURCE_GROUP`, `AZURE_POSTGRES_DB`, `AZURE_POSTGRES_USER`, `AZURE_POSTGRES_PASSWORD`.

#### Production Zero-Downtime Strategy

For production, add deployment slots to eliminate downtime during deploys. The replica-tested migration (above) ensures migrations are safe before the full flow runs.

**Prerequisites:** Standard S1+ App Service Plan (for deployment slots).

**Production deploy flow:**

```
1–7. Replica-tested migration (same as above)
8.   Deploy new code to staging slot (points at production DB — already migrated)
9.   Health check staging slot
10.  Swap slots (instant, zero downtime)
     → If health check fails: swap back, old code still works
11.  Restart worker/beat
```

**Backwards-compatible migrations are still recommended** — during the window between migration (step 5) and slot swap (step 10), the production slot runs old code against the new schema. Additive migrations (nullable columns, new tables) are always safe. For destructive changes:

| Change | Approach | Deploys |
|--------|----------|---------|
| Add column | Add as nullable — old code ignores it | 1 |
| Remove column | Deploy 1: remove all code references. Deploy 2: drop column | 2 |
| Rename column | Add new column → write to both → backfill → read from new → drop old | 3–4 |
| Add NOT NULL constraint | Deploy 1: ensure all rows satisfy constraint + set default. Deploy 2: add constraint | 2 |
| Change column type | Add new column with new type → migrate data → swap code → drop old | 3–4 |

**Worker/beat:** Don't need deployment slots. They have no user-facing traffic — the existing stop/start cycle is acceptable.

---

## Azure Deployment

The app deploys to Azure as five services. GitHub Actions workflows (`.github/workflows/deploy-backend.yml` and `deploy-frontend.yml`) deploy automatically on push to `main`.

| Component | Azure Service | Startup |
|-----------|---------------|---------|
| Backend API | App Service (Python 3.12, Linux) | `bash startup.sh` — waits for DB, migrations, collectstatic, gunicorn + uvicorn ASGI workers |
| Celery Worker | App Service (same plan) | `bash startup-worker.sh` — HTTP health responder + waits for DB, processes `messages` queue |
| Celery Beat | App Service (same plan) | `bash startup-beat.sh` — HTTP health responder + waits for DB, `DatabaseScheduler`, dispatches due messages every 60s |
| Frontend | Azure Static Web Apps | Vite build → `dist/` uploaded via `Azure/static-web-apps-deploy` |
| Database | Azure Database for PostgreSQL | Flexible Server |
| Redis | Azure Cache for Redis | Celery broker + result backend |
| Storage | Azure Blob Storage | MMS media files |

### Step-by-Step Azure Setup

#### 1. Provision Azure Resources

Create these resources in a single resource group (a logical container that groups related Azure resources for unified management, billing, and access control):

1. **Azure Database for PostgreSQL** — Flexible Server. Note the server name, database name, admin user, and password.
2. **Azure Cache for Redis** — Basic C0 (~$15/mo). Classic Azure Cache for Redis is being deprecated in 2028; Azure Managed Redis (AMR) is the replacement but starts at ~$30/mo for the B0 tier. For dev/staging, Classic Basic C0 is fine.
   - Connection URL format: `rediss://:<access-key>@<redis-name>.redis.cache.windows.net:6380/0`
   - Must use `rediss://` (TLS) and port `6380` (classic) or `10000` (AMR)
3. **App Service Plan** — Linux, B1 or higher. All three backend services (API, worker, beat) can share one plan for dev/staging.
4. **App Service × 3** — Create three App Services on the plan above (API, worker, beat). Set runtime to Python 3.12.
5. **Azure Static Web Apps** — Free tier. `frontend/staticwebapp.config.json` handles SPA routing fallback.
6. **Azure Blob Storage** — Standard LRS. The `media` container is auto-created on first upload if it doesn't exist. Copy the account name and one of the access keys from Storage Account → Access keys. Per-blob read-only SAS tokens (1h expiry) are generated at upload time.

#### 2. Configure Azure Cache for Redis

After provisioning the Redis instance, configure it to accept connections from the App Services:

1. **Enable access key authentication:** Azure Cache for Redis → Authentication → untick "Disable Access Keys Authentication". This is disabled by default on new instances — without it, all password-based connections from Celery are rejected with "invalid username-password pair".
2. **Enable public network access:** Azure Cache for Redis → Private Endpoint → set Public network access to **Enabled**.
3. **Add firewall rules:** Whitelist the App Service outbound IPs so Redis accepts connections from your backend services. Find them at: any App Service → Networking → Outbound addresses (all 3 services share the same App Service Plan, so they have identical IPs). Use IP ranges to minimize the number of rules (e.g., `20.46.106.0` – `20.46.110.255` to cover a block).
4. **Verify the access key:** Copy the Primary key from Azure Cache for Redis → Authentication → Access keys. This must exactly match the password in your `CELERY_BROKER_URL` env var (`rediss://:<this-key>@...`). Do not URL-encode special characters like `=` — see [gotcha below](#azure-cache-for-redis--do-not-url-encode-the-access-key).

#### 3. Configure App Services

For each App Service (API, worker, beat):

**Settings → Configuration → General settings → Startup command:**
- API: `bash startup.sh`
- Worker: `bash startup-worker.sh`
- Beat: `bash startup-beat.sh`

**Settings → Configuration → General settings → Always On:** Set to **On**. Required for all three services. Azure unloads idle processes without it. Note: Always On alone is not sufficient for worker/beat — they also need the HTTP health responder (see [Worker/beat require an HTTP listener](#workerbbeat-require-an-http-listener) below).

**Settings → Environment variables** — set the variables listed in the [Environment Variables](#environment-variables) table below.

**Settings → Configuration → General settings:**
- Ensure `SCM_DO_BUILD_DURING_DEPLOYMENT` is set to `true` — this triggers Oryx to run `pip install -r requirements.txt` during zip deploy.

**Download publish profiles:**
- Each App Service → Overview → Download publish profile. You need **Basic authentication** enabled (Settings → Configuration → General settings → Basic Auth Publishing Credentials → On).

#### 4. Configure GitHub Secrets

In your GitHub repo → Settings → Secrets and variables → Actions, set the secrets listed in the [GitHub Secrets](#github-secrets-cd) table below.

#### 5. Configure Clerk for Azure

1. **Clerk Dashboard → Domains:** Add the Static Web App URL (`https://<name>.azurestaticapps.net`) as an allowed origin
2. **Clerk Dashboard → Webhooks → Add Endpoint:**
   - URL: `https://<api-app-name>.azurewebsites.net/api/webhooks/clerk/`
   - Subscribe to: `user.created`, `user.updated`, `user.deleted`, `organization.created`, `organization.updated`, `organization.deleted`, `organizationMembership.created`, `organizationMembership.updated`, `organizationMembership.deleted`, `subscription.active`, `subscriptionItem.canceled`, `subscriptionItem.ended`, `subscription.past_due`
   - Copy the **Signing Secret** (`whsec_...`) → set as `CLERK_WEBHOOK_SIGNING_SECRET` on all backend App Services

#### 5b. Configure Stripe Webhook for Azure

1. **Stripe Dashboard → Webhooks → Add endpoint:**
   - URL: `https://<api-app-name>.azurewebsites.net/api/webhooks/stripe/`
   - API version: **`2026-03-25.dahlia`** (must match `StripeMeteredBillingProvider.STRIPE_API_VERSION`)
   - Subscribe to: `invoice.paid`, `invoice.payment_failed`, `invoice.overdue`, `invoice.voided`
   - Copy the **Signing Secret** (`whsec_...`) → set as `STRIPE_WEBHOOK_SECRET` on all backend App Services
2. Copy the **Secret key** from Stripe Dashboard → Developers → API keys → set as `STRIPE_SECRET_KEY` on all backend App Services

#### 6. Deploy

Push to `main` to trigger both GitHub Actions workflows. Alternatively, manually trigger them from the Actions tab. The backend deploy workflow:

1. Stamps the git SHA into `health.py` (`DEPLOY_SHA` constant) during the build step
2. Deploys code to all three App Services via `azure/webapps-deploy`
3. Explicitly stops and starts the worker and beat services via `az webapp stop/start` (Azure doesn't reliably restart non-web App Services after zip deploy — see [gotcha below](#workerbbeat-require-an-http-listener))
4. Polls `GET /api/health/smoke/` for up to 5 minutes, checking both HTTP 200 and the expected git SHA — this confirms the **new** instance is serving (not the old one), DB writes work, and Redis works

#### 7. Verify

- `GET https://<api-app-name>.azurewebsites.net/api/health/` returns 200
- Frontend loads at the Static Web App URL and Clerk sign-in works
- Sign up a user → check Clerk Dashboard → Webhooks → verify events delivered successfully (200)
- App Service → Monitoring → Log stream shows JSON-formatted request/response logs
- Send a test message to verify the Celery worker processes it

### Environment Variables

Set these on **all three** App Services (API, worker, beat) via Settings → Environment variables:

| Variable | Value |
|----------|-------|
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` (triggers `pip install` on deploy) |
| `DJANGO_SECRET_KEY` | Strong random key |
| `DEBUG` | `0` |
| `ALLOWED_HOSTS` | `<api-app-name>.azurewebsites.net,169.254.129.2` |
| `CORS_ALLOWED_ORIGINS` | `https://<static-web-app>.azurestaticapps.net` |
| `POSTGRES_DB` | Database name |
| `POSTGRES_USER` | Database user |
| `POSTGRES_PASSWORD` | Database password |
| `POSTGRES_HOST` | `<server>.postgres.database.azure.com` |
| `POSTGRES_PORT` | `5432` |
| `DB_POOL` | `true` (enable psycopg3 native connection pooling) |
| `DB_POOL_MIN_SIZE` | `2` (API), `1` (worker/beat — set in startup scripts) |
| `DB_POOL_MAX_SIZE` | `8` (API), `4` (worker), `2` (beat — set in startup scripts) |
| `DB_POOL_TIMEOUT` | `10` (seconds to wait for a pooled connection) |
| `CELERY_BROKER_URL` | `rediss://:<key>@<redis-host>:<port>/0` |
| `CELERY_RESULT_BACKEND` | Same as broker URL |
| `CLERK_FRONTEND_API` | Clerk frontend API URL |
| `CLERK_SECRET_KEY` | Clerk secret key |
| `CLERK_WEBHOOK_SIGNING_SECRET` | Clerk webhook signing secret (`whsec_...`) |
| `CLERK_AUTHORIZED_PARTIES` | `https://<static-web-app>.azurestaticapps.net` |
| `STORAGE_PROVIDER_CLASS` | `app.utils.storage.AzureBlobStorageProvider` |
| `AZURE_STORAGE_ACCOUNT_NAME` | `<account-name>` |
| `AZURE_STORAGE_ACCOUNT_KEY` | `<account-key>` |
| `AZURE_CONTAINER` | `media` |
| `LOG_LEVEL` | `INFO` |
| `LOG_FORMAT` | `json` |
| `SESSION_COOKIE_SECURE` | `True` |
| `CSRF_COOKIE_SECURE` | `True` |
| `SECURE_HSTS_SECONDS` | `31536000` |
| `STRIPE_SECRET_KEY` | Stripe live secret key (`sk_live_...`) |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret (`whsec_...`) |

### GitHub Secrets (CD)

| Secret | Where to find it |
|--------|------------------|
| `AZURE_BACKEND_APP_NAME` | API App Service name |
| `AZURE_BACKEND_PUBLISH_PROFILE` | API App Service → Overview → Download publish profile |
| `AZURE_WORKER_APP_NAME` | Worker App Service name |
| `AZURE_WORKER_PUBLISH_PROFILE` | Worker App Service → Download publish profile |
| `AZURE_BEAT_APP_NAME` | Beat App Service name |
| `AZURE_BEAT_PUBLISH_PROFILE` | Beat App Service → Download publish profile |
| `AZURE_CREDENTIALS` | Service principal JSON — see [Creating AZURE_CREDENTIALS](#creating-azure_credentials) below |
| `AZURE_RESOURCE_GROUP` | Resource group name containing all App Services |
| `AZURE_POSTGRES_HOST` | PostgreSQL server FQDN (e.g. `server.postgres.database.azure.com`) — used for migration check and production migrate |
| `AZURE_POSTGRES_SERVER_NAME` | PostgreSQL Flexible Server name (for replica creation and backups) |
| `AZURE_POSTGRES_RESOURCE_GROUP` | Resource group containing the PostgreSQL server (may differ from App Services resource group) |
| `AZURE_POSTGRES_DB` | Azure database name |
| `AZURE_POSTGRES_USER` | Azure PostgreSQL admin username |
| `AZURE_POSTGRES_PASSWORD` | Azure PostgreSQL admin password |
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | Static Web App → Manage deployment token |
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk dashboard |
| `VITE_API_BASE_URL` | `https://<api-app-name>.azurewebsites.net` (also used by backend deploy's post-deploy health check) |
| `VITE_SENTRY_DSN` | Sentry DSN for frontend (baked into JS bundle at build time) |
| `SENTRY_AUTH_TOKEN` | Sentry auth token for CI release tracking (optional — releases skipped if not set) |
| `SENTRY_ORG` | Sentry organization slug |
| `SENTRY_PROJECT_BACKEND` | Sentry project slug for backend |
| `SENTRY_PROJECT_FRONTEND` | Sentry project slug for frontend |

#### Creating AZURE_CREDENTIALS

The backend deploy workflow uses `azure/login` + `az webapp stop/start` to restart worker and beat after deploying. This requires a service principal with Contributor access to the resource group:

```bash
az ad sp create-for-rbac \
  --name "github-deploy-1reach" \
  --role contributor \
  --scopes /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP_NAME> \
  --json-auth
```

Find `<SUBSCRIPTION_ID>` at Azure Portal → Subscriptions. Paste the entire JSON output as the `AZURE_CREDENTIALS` secret value in GitHub.

### Database Connection Pooling

The backend uses **psycopg3 with Django's native connection pool** (`DATABASES["default"]["POOL"]`). This is essential for ASGI deployments — without it, Django under Uvicorn spawns a new thread per request via `asgiref`, and each thread opens a persistent DB connection. Under load, connections accumulate unboundedly until PostgreSQL runs out of connection slots and the entire system (API + Celery) goes down.

The pool provides a **bounded, per-process connection pool**. When all connections in the pool are busy, new requests queue for up to `DB_POOL_TIMEOUT` seconds. If a connection frees up in time, the request proceeds. If not, the request gets a `PoolTimeout` error — but only that request fails, not the whole system.

#### Connection budget

With default settings, the maximum number of PostgreSQL connections is deterministic:

| Process | Instances | Pool max_size | Total connections |
|---|---|---|---|
| Web workers (Uvicorn) | 2 | 8 | 16 |
| Celery workers | 2 | 4 | 8 |
| Celery Beat | 1 | 2 | 2 |
| **Total** | | | **26** |

Azure PostgreSQL Flexible Server typically allows 50–100+ connections depending on tier, so this leaves ample headroom for admin queries, migrations, and monitoring.

#### Throughput estimates

With 16 concurrent web DB connections:

| Avg DB time per request | Approx max throughput |
|---|---|
| 10ms | ~1,600 req/s |
| 50ms | ~320 req/s |
| 200ms | ~80 req/s |

#### Scaling horizontally

When Azure App Service auto-scales to multiple instances, each instance creates its own pools. The total connection count multiplies:

| Web instances | Pool max_size | Web connections | + Celery/Beat | Total |
|---|---|---|---|---|
| 1 (default) | 8 | 16 | 10 | **26** |
| 2 | 8 | 32 | 10 | **42** |
| 4 | 8 | 64 | 10 | **74** |
| 4 | 4 (reduced) | 32 | 10 | **42** |

**If you scale beyond 2 web instances**, reduce `DB_POOL_MAX_SIZE` proportionally via Azure App Settings to stay within PostgreSQL's connection limit. No redeploy is needed — just change the env var and restart.

**If you need more than ~100 concurrent DB connections**, enable Azure PostgreSQL Flexible Server's [built-in PgBouncer](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-pgbouncer). PgBouncer multiplexes hundreds of application connections through a smaller number of actual PostgreSQL connections, removing the per-instance pool sizing constraint.

#### Configuration reference

| Env var | Default | Where set | Description |
|---|---|---|---|
| `DB_POOL` | `true` | Azure App Settings | Enable/disable connection pooling. `false` for local dev. |
| `DB_POOL_MIN_SIZE` | `2` | App Settings or startup scripts | Minimum warm connections per process |
| `DB_POOL_MAX_SIZE` | `8` | App Settings or startup scripts | Maximum connections per process |
| `DB_POOL_TIMEOUT` | `10` | App Settings | Seconds to wait for a connection before `PoolTimeout` |
| `DB_CONN_MAX_AGE` | `0` | Only used when `DB_POOL=false` | Seconds to keep connections alive (0 = close after each request) |

The startup scripts (`startup-worker.sh`, `startup-beat.sh`) set smaller default pool sizes for Celery processes. Azure App Settings override these if set.

#### Troubleshooting

- **`PoolTimeout` errors in Sentry:** The pool is full and requests are waiting longer than `DB_POOL_TIMEOUT`. Increase `DB_POOL_MAX_SIZE` or investigate slow queries.
- **`remaining connection slots are reserved`:** Total connections across all processes exceed PostgreSQL's `max_connections`. Reduce `DB_POOL_MAX_SIZE`, scale down instances, or enable PgBouncer.
- **Celery tasks hanging after deploy:** Forked worker processes may have inherited stale connections from the parent. The `worker_process_init` signal handler in `celery.py` closes these automatically, but if you see issues, restart the worker App Service.

### Monitoring & Alerts

#### Application Insights

Enable Application Insights on all three App Services: Settings → Application Insights → Turn on → Create new resource (or link to an existing one). This provides request tracing, dependency tracking, failure analysis, and live metrics at no extra cost for the included data.

#### Recommended alert rules

Set up these alert rules in Azure Monitor (App Service → Monitoring → Alerts → Create alert rule):

| Alert | Condition | Threshold | Severity |
|-------|-----------|-----------|----------|
| API errors | HTTP 5xx count | > 10 in 5 minutes | Sev 1 |
| API latency | Avg response time | > 5 seconds for 5 minutes | Sev 2 |
| App Service down | Availability | < 100% for 5 minutes | Sev 1 |
| Beat stopped | No `dispatch_due_messages` log | > 5 minutes gap (custom log query) | Sev 1 |

For the beat monitoring alert, use a Log Analytics query on the beat App Service logs:

```kusto
AppServiceConsoleLogs
| where ResultDescription contains "Scheduler: Sending due task"
| summarize LastSeen = max(TimeGenerated)
| where LastSeen < ago(5m)
```

#### Sentry

**Backend:** Set `SENTRY_DSN` on all three App Services. `settings.py` initialises `sentry_sdk` with explicit `DjangoIntegration()` (request context, unhandled exceptions) and `CeleryIntegration()` (task failures with task name, args, retry count). A `task_failure` Celery signal handler also logs all task failures at ERROR level for Azure Log Analytics. Permanent send failures, delivery failures, webhook signature errors, and Clerk API errors are logged at ERROR (not WARNING) so they appear in Sentry and can trigger Azure Monitor alerts. Optional env vars: `SENTRY_ENVIRONMENT` (default `production`), `SENTRY_TRACES_SAMPLE_RATE` (default `0.1`).

**Frontend:** `@sentry/react` initialised in `main.tsx` (conditional on `VITE_SENTRY_DSN`). The root error boundary in `__root.tsx` calls `Sentry.captureException()` to capture unhandled React errors. `VITE_SENTRY_DSN` is baked into the JS bundle at build time via the `deploy-frontend.yml` workflow.

**CI/CD releases:** Both deploy workflows create a Sentry release tagged with the git SHA via `getsentry/action-release@v3` (skipped if `SENTRY_AUTH_TOKEN` is not set). This links Sentry errors to specific deploys.

### Gotchas & Troubleshooting

These are issues encountered during initial deployment that are easy to miss:

#### Oryx build system and startup scripts
Azure App Service uses **Oryx** to build and run Python apps. Oryx extracts the deployed zip to a **temp directory** (e.g., `/tmp/8de8a2ddc57556c`), NOT `/home/site/wwwroot`. Startup scripts must use **relative paths** — never `cd /home/site/wwwroot`. The startup command in Azure Portal must also be relative: `bash startup.sh`, not `bash /home/site/wwwroot/startup.sh`.

#### VITE_API_BASE_URL must include the protocol
`VITE_API_BASE_URL` is baked into the frontend JS bundle at build time. It **must** include `https://` — without it, the browser resolves it as a relative path and API requests go to `https://<frontend-host>/<backend-host>/api/...` instead of `https://<backend-host>/api/...`. It must NOT have a trailing slash (API paths already start with `/api/`).

#### CORS_ALLOWED_ORIGINS — no trailing slash
Django-cors-headers silently rejects origins with a trailing slash. Use `https://<host>.azurestaticapps.net`, not `https://<host>.azurestaticapps.net/`.

#### ALLOWED_HOSTS must include Azure health probe IP
Azure health probes hit the app from internal IP `169.254.129.2`. Add it to `ALLOWED_HOSTS` or Django returns `DisallowedHost` and Azure marks the app as unhealthy. For dev/staging you can use `*`.

#### SECURE_SSL_REDIRECT must NOT be True
Azure terminates TLS at the load balancer. The app receives plain HTTP internally. Setting `SECURE_SSL_REDIRECT=True` causes an infinite redirect loop.

#### Frontend deploy — skip_app_build
The `Azure/static-web-apps-deploy@v1` action runs its own internal build by default, **without** your GitHub secrets as env vars. Since Vite env vars (`VITE_*`) must be present at build time, the workflow builds first with `npm run build` (where secrets are available), then deploys the pre-built `dist/` with `skip_app_build: true`.

#### Clerk webhook URL
The webhook endpoint is `POST /api/webhooks/clerk/` (not `/api/clerk/webhook/` or similar). The trailing slash is required — Django's `APPEND_SLASH` doesn't work for POST requests.

#### Clerk webhook signing secret
The `CLERK_WEBHOOK_SIGNING_SECRET` env var on the backend must exactly match the signing secret shown in the Clerk Dashboard for that webhook endpoint. A mismatch causes Svix signature verification to fail → 400 response → webhooks silently not processed.

#### CLERK_AUTHORIZED_PARTIES
The backend validates the `azp` (authorized party) claim in Clerk JWTs against this comma-separated list. If the Azure frontend URL is missing, all authenticated API calls return 403. Include both local and deployed URLs: `http://localhost:5173,https://<static-web-app>.azurestaticapps.net`.

#### App Service log stream shows stale logs
After redeploying, the Azure Portal log stream may continue showing old logs. **Stop and restart** the App Service (not just restart — do Stop, wait, then Start). If logs still don't update, the deployment may not have triggered an Oryx rebuild — check the deployment logs in the Deployment Center.

#### Publish profile requires Basic Auth
To download a publish profile, Basic Authentication must be enabled: App Service → Settings → Configuration → General settings → Basic Auth Publishing Credentials → On.

#### Azure Cache for Redis — access key authentication disabled by default
New Azure Redis instances have access key auth disabled. Celery connections fail with "invalid username-password pair" even though the key is correct. Fix: Azure Cache for Redis → Authentication → untick "Disable Access Keys Authentication".

#### Azure Cache for Redis — firewall blocks App Service connections
By default, Azure Redis blocks all inbound connections. Without firewall rules, Celery's `.delay()` call hangs (or times out after 5s with the broker/result backend transport options in `settings.py`). Fix: enable public network access and add App Service outbound IP ranges as firewall rules. All 3 services (API, worker, beat) share one App Service Plan so they have the same outbound IPs.

#### Azure Cache for Redis — do not URL-encode the access key
Azure Redis access keys are base64 strings that may end in `=`. Do **not** URL-encode `=` to `%3D` in `CELERY_BROKER_URL` — `redis-py` parses the password using `@` as the delimiter and handles `=` correctly. URL-encoding causes auth failures.

#### Azure Cache for Redis — `redis.from_url()` and TLS `ssl_cert_reqs`
The `_ensure_redis_ssl()` helper in `settings.py` appends `ssl_cert_reqs=CERT_NONE` to `rediss://` URLs. Celery reads this via its own `CELERY_BROKER_USE_SSL` setting, but `redis.from_url()` (used in the health endpoint and startup scripts) rejects the string `"CERT_NONE"` from the URL query param — it expects the `ssl.CERT_NONE` integer constant passed as a keyword argument. The health endpoint (`health.py`) strips the query param and passes `ssl_cert_reqs=ssl.CERT_NONE` explicitly. If you create new `redis.from_url()` calls, do the same.

#### Uvicorn lifespan events
Uvicorn sends ASGI `lifespan.startup` events when workers start. Django (as of 6.0) doesn't handle these — `ASGIHandler.__call__` raises `ValueError: Django can only handle ASGI/HTTP connections, not lifespan.` This is a known Django limitation (there's a `# FIXME` in their source). Without a fix, every worker start floods Sentry with `ValueError`. **Fix:** `startup.sh` uses `-k app.worker.Worker` — a one-line `UvicornWorker` subclass that sets `CONFIG_KWARGS = {..., "lifespan": "off"}`. This is the standard community workaround since gunicorn's `-k` flag is the only way to pass uvicorn config through gunicorn.

#### Worker/beat require an HTTP listener
Azure App Service expects every container to respond to HTTP health probes on `$PORT` (default 8000). The API service satisfies this via gunicorn, but Celery worker and beat have no HTTP listener. Without one:

- Azure may not start the container even when the Portal shows status "Running"
- Azure kills containers that don't respond to health probes within ~2 minutes of startup
- `az webapp restart` and manual restarts from the Portal may have no effect
- Containers get periodically recycled to a blank state, losing the deployment artifact

**Fix:** Both `startup-worker.sh` and `startup-beat.sh` start a minimal Python HTTP server as a background process before launching Celery. This server responds `200 ok` to any request on `$PORT`, satisfying Azure's health probes. This is a standard workaround for running background processes on Azure App Service. For a production setup, consider migrating worker/beat to Azure Container Apps which natively supports non-HTTP workloads.

#### Worker/beat don't restart automatically after deploy
`azure/webapps-deploy` pushes code but doesn't reliably restart non-web App Services. The API restarts because Azure detects new code for web processes, but worker and beat may continue running old code (or not run at all). **Fix:** The deploy workflow uses `az webapp stop` + `az webapp start` after deploying worker and beat. This requires `AZURE_CREDENTIALS` and `AZURE_RESOURCE_GROUP` secrets. Note: `az webapp restart` alone is insufficient — it's a soft restart that Azure may ignore for idle non-web containers. The stop/start cycle forces Azure to tear down and recreate the container.

#### Failed database migration recovery
The deploy workflow creates an on-demand PostgreSQL backup before every deployment (`pre-deploy-YYYYMMDD-HHMMSS`). If a migration fails mid-apply, the database may be in a partially-migrated state where neither old nor new code works. Recovery:

1. **Find the backup:** Azure Portal → PostgreSQL Flexible Server → Backups, or check the `pre-deploy` job logs for the backup name
2. **Restore to a new server:**
   ```bash
   az postgres flexible-server restore \
     --resource-group <RG> --name <new-server-name> \
     --source-server <current-server> \
     --backup-name <pre-deploy-YYYYMMDD-HHMMSS>
   ```
3. **Update `POSTGRES_HOST`** on all three App Services (API, worker, beat) to point to the restored server
4. **Restart all App Services** — Stop, then Start each one
5. **Fix the migration** and redeploy

Restore creates a **new server** — the original server and all other databases on it are untouched. This is safe for shared PostgreSQL servers.

To manually rollback a specific migration without a full DB restore:
```bash
# From the App Service SSH console:
python manage.py migrate <app_label> <previous_migration_name>
```
This only works if the migration has a valid `reverse()` operation (Django auto-generates reverses for most operations, but not `RunPython` or `RunSQL` unless you provide them).

**Secrets required:** `AZURE_POSTGRES_HOST`, `AZURE_POSTGRES_SERVER_NAME`, `AZURE_POSTGRES_RESOURCE_GROUP`, `AZURE_POSTGRES_DB`, `AZURE_POSTGRES_USER`, `AZURE_POSTGRES_PASSWORD` — see [GitHub Secrets](#github-secrets-cd).

#### Deployment artifacts can disappear on container recycle
When Azure recycles a non-web App Service container (which happens periodically), the fresh container may boot with an empty `/home/site/wwwroot` — no build manifest, no virtual environment, no startup script. The log shows `Could not find build manifest file` followed by `bash: startup-worker.sh: No such file or directory`. The HTTP health responder in the startup scripts prevents most recycling by keeping the container alive. If it does happen, re-trigger the deploy workflow or manually stop/start the App Service.

#### Azure CLI `az postgres flexible-server` deprecation (v2.86.0, May 2026)
Several `az postgres flexible-server` argument names are being renamed in CLI version 2.86.0. The deploy workflow uses the current args (which produce warnings but work correctly). When updating to 2.86.0+, apply these changes:

| Command | Current arg | New arg (2.86.0) |
|---------|------------|------------------|
| `firewall-rule create/delete` | `--name` (server name) | `--server-name` |
| `firewall-rule create/delete` | `--rule-name` (rule name) | `--name` |
| `backup create` | `--name` (server name) | `--server-name` |
| `backup create` | `--backup-name` | `--name` |
| `replica create` | `--replica-name` | `--name` (already updated) |

A `TODO` comment in `deploy-backend.yml` marks the affected lines.

#### PostgreSQL Burstable tier does not support replicas
The replica-tested migration flow requires General Purpose or Memory Optimized tier. On Burstable tier (dev/staging), the replica creation step fails with `Read replica is not supported for the Burstable pricing tier`. The workflow should be updated to gracefully skip the replica test and fall back to backup + migrate directly on Burstable (see [Migration Safety](#migration-safety-implemented)). For production, use General Purpose or higher.

---

See [v1_migration.md](v1_migration.md) for v1 → v2 migration details.
