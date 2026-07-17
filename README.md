# django-clerk-react

A production-grade starter for multi-tenant SaaS applications: Django + DRF
backend, React frontend, Clerk authentication and organisations, and a
credit/usage billing engine with Stripe invoicing — plus the CI/CD and Azure
infrastructure to ship it.

---

## What you get

- **Multi-tenancy** — Clerk Organizations mapped to a local `Organisation`
  model; every business model and query is scoped to the authenticated user's
  org automatically.
- **Authentication** — Clerk JWT verification on every request, org context
  extracted from the token, role-based permissions (`IsOrgMember`,
  `IsOrgAdmin`).
- **Clerk webhook sync** — 13 idempotent webhook handlers keep users, orgs,
  memberships, and subscription state in sync (Clerk is the source of truth).
- **Billing engine** — prepaid credits, subscription mode via Clerk Billing,
  metered usage tracking, Stripe Checkout top-ups, and automated monthly
  Stripe invoicing.
- **User management** — invite, deactivate, and grant/revoke admin from the
  app; changes round-trip through Clerk's API and webhooks.
- **Async tasks** — Celery worker + beat with a Redis heartbeat health probe,
  all running from the same Docker image as the API.
- **Test infrastructure** — pytest suite, Vitest + MSW unit/integration
  tests, and a Playwright E2E harness that signs in through **real Clerk**.
- **Deployment** — GitHub Actions CI, parameterized Azure Bicep templates,
  and deploy workflows with migration rehearsal and zero-downtime traffic
  shifting.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Django + Django REST Framework + PostgreSQL 16 |
| Auth & billing | Clerk (JWT + webhooks + subscription billing) + Stripe (checkout + metered invoicing) |
| Frontend | React 19 + Vite + TanStack Router + TanStack Query |
| Styling | Tailwind CSS + Headless UI (Catalyst-style component kit in `src/ui/`) |
| Task queue | Celery 5 + Redis 7 |
| Storage | Pluggable provider (Mock by default, Azure Blob included) |
| Monitoring | Sentry + structured JSON logging |
| Testing | pytest (backend), Vitest + Playwright (frontend) |

---

## Getting started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- A [Clerk](https://clerk.com) application (free tier is fine)
- Optionally a [Stripe](https://stripe.com) test-mode account (for billing)

### Environment setup

```bash
cp backend/.envexample backend/.env       # Django + Postgres + Clerk + Stripe + Celery
cp frontend/.envexample frontend/.env     # Clerk publishable key + API URL
```

Minimum required values to boot: `DJANGO_SECRET_KEY`, `CLERK_FRONTEND_API`,
`CLERK_SECRET_KEY`, `CLERK_WEBHOOK_SIGNING_SECRET` (backend) and
`VITE_CLERK_PUBLISHABLE_KEY` (frontend). Everything else has working
defaults for local development — see the comments in each `.envexample`.

### Run

```bash
docker compose up
```

| Service | URL | Description |
|---|---|---|
| Backend API | http://localhost:8000 | Django REST API |
| Frontend | http://localhost:5173 | Vite dev server |
| Swagger UI | http://localhost:8000/api/docs/ | Interactive API docs (DEBUG only) |
| Redis | localhost:6379 | Celery broker + result backend |
| Celery worker | — | Executes async tasks |
| Celery beat | — | Schedules `worker_heartbeat` + `generate_monthly_invoices` |

All three backend roles (API, worker, beat) run from the **same Docker
image**; `backend/entrypoint.sh` selects the command from the
`CONTAINER_ROLE` env var (`api` / `worker` / `beat`).

### Clerk configuration

1. Create an application in the [Clerk Dashboard](https://dashboard.clerk.com).
2. Enable **Organizations**, and **Organization Invitations**
   (Organizations → Settings).
3. Create a **Webhook** endpoint pointing at
   `https://your-domain/api/webhooks/clerk/` and subscribe to:

   **Core sync:** `user.created`, `user.updated`, `user.deleted`,
   `organization.created`, `organization.updated`, `organization.deleted`,
   `organizationMembership.created`, `organizationMembership.updated`,
   `organizationMembership.deleted`

   **Clerk Billing:** `subscription.created`, `subscription.updated`,
   `subscription.active`, `subscription.pastDue`

   Note the trailing slash on the webhook URL — Django's `APPEND_SLASH`
   does not apply to POST requests.
4. If you use subscriptions: enable **Billing** and create **one paid
   subscription plan for Organizations**. Do **not** create a free/trial plan
   in Clerk — the prepaid credit period is managed in-app, and a Clerk free
   plan would fire `subscription.active` on signup and bypass it.
5. Copy the Frontend API URL, secret key, and webhook signing secret into
   `backend/.env`, and the publishable key into `frontend/.env`.

Webhook handlers live in `backend/app/utils/clerk.py`. They are idempotent
and retry-safe; billing events are deduplicated by `svix-id` and ordered by
the payload's `updated_at`, so out-of-order or duplicate deliveries are
handled gracefully.

For production, create a separate Clerk production instance (Clerk's clone
feature copies most settings), add your custom domain (the resulting FAPI
URL becomes `CLERK_FRONTEND_API` and must exactly match the JWT `iss`
claim), register your own OAuth apps for social sign-in, and create a new
webhook endpoint with its own signing secret.

### Stripe configuration (optional)

Stripe powers prepaid credit purchases (Checkout) and monthly metered
invoices. Clerk creates the Stripe Customers when orgs subscribe (connect
your Stripe account in Clerk Billing settings), which is what lets a
customer enter a card once.

1. Create a webhook endpoint in the
   [Stripe Dashboard](https://dashboard.stripe.com/webhooks) pointing at
   `https://your-domain/api/webhooks/stripe/`, subscribed to: `invoice.paid`,
   `invoice.payment_failed`, `invoice.overdue`, `invoice.voided`,
   `checkout.session.completed`, `checkout.session.expired`. Select the API
   version pinned in `StripeMeteredBillingProvider.STRIPE_API_VERSION`.
2. Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in `backend/.env`.
   When `STRIPE_SECRET_KEY` is set the backend auto-selects
   `StripeMeteredBillingProvider`; when unset it falls back to
   `MockMeteredBillingProvider` (dev/testing).

---

## Architecture

### Multi-tenancy

- `Organisation` and `OrganisationMembership` mirror Clerk orgs and
  memberships. Business models inherit `TenantModel`, which adds an
  `organisation` FK.
- `ClerkJWTAuthentication` verifies the Clerk JWT and extracts the active
  org from the token's `o` claim; middleware exposes it as `request.org` and
  the member's role as `request.org_role`.
- `TenantScopedMixin` filters every ViewSet queryset to `request.org` — a
  view cannot accidentally leak another tenant's rows.

### API conventions

- **Pagination**: `StandardPagination` wraps list responses as
  `{ "results": [...], "pagination": { total, page, limit, totalPages,
  hasNext, hasPrev } }`.
- **Errors**: a shared exception handler produces consistent error
  envelopes; the frontend `ApiClient` parses them into typed errors.
- **Throttling**: DRF scoped throttles, rates configurable via
  `THROTTLE_RATE_*` env vars.
- **Config**: the `Config` model is a per-org key/value store (e.g.
  `monthly_limit`, per-usage-type rate overrides) editable via
  `/api/configs/`.

### Endpoints

| Resource | Endpoints |
|---|---|
| Users | `GET /api/users/`, `GET /api/users/me/`, `PATCH /api/users/:id/role/`, `PATCH /api/users/:id/status/`, `POST /api/users/invite/` |
| Billing | `GET /api/billing/summary/`, `POST /api/billing/buy-credits/`, `GET /api/billing/invoices/`, `GET /api/billing/invoice-preview/`, `POST /api/billing/invoice-download/` (admin only) |
| Configs | `GET/POST/PUT/PATCH/DELETE /api/configs/` |
| Webhooks | `POST /api/webhooks/clerk/`, `POST /api/webhooks/stripe/` |
| Health | `GET /api/health/` (DB + Redis), `GET /api/health/smoke/` (DB/Redis write + deploy SHA), `GET /api/health/worker/` (Celery heartbeat freshness) |

### Celery

`backend/app/celery.py` holds the Celery app. Bootstrap ordering matters:
`config_from_object(...)` runs **before** `django.setup()`, which runs before
any model import — the worker is a fresh Python process with no Django app
registry, and getting this wrong makes the worker die silently on startup
(guarded by a subprocess import smoke test in the suite).

Beat schedules two tasks: `worker_heartbeat` (writes a Redis key with a TTL —
proves both that beat fired *and* that a worker consumed the task; read by
`GET /api/health/worker/`) and `generate_monthly_invoices` (1st of each
month). A `link_billing_customer` task retries Stripe customer lookup with
backoff when webhook timing races the Stripe API.

### Storage

File storage is behind a provider interface (`app/utils/storage.py`):
`MockStorageProvider` (default, in-memory) and `AzureBlobStorageProvider`
(per-blob SAS tokens). Select via `STORAGE_PROVIDER_CLASS`.

---

## Billing model

Organisations have a `billing_mode`:

| Mode | Meaning |
|---|---|
| `prepaid` | Default on signup. Usage is charged against `credit_balance`; new orgs receive `FREE_CREDIT_AMOUNT` (default $5.00) free credits. Admins top up via Stripe Checkout. |
| `subscribed` | Set by Clerk Billing webhooks when the org has an active paid plan. Usage is tracked in the ledger and invoiced monthly via Stripe. |
| `past_due` | Set when a Clerk subscription or Stripe invoice goes unpaid. All spending is blocked until resolved. |

Every billable action writes a `CreditTransaction` row (grant / usage /
refund / deduct), snapshotting the `unit_rate` in effect at the time — so
invoices stay correct even if rates change mid-month.

**Core functions** (`backend/app/utils/billing.py`):

- `check_can_spend(org, units, usage_type)` — the gate: blocks `past_due`,
  enforces the org's `monthly_limit` Config, and pre-checks prepaid balance.
  Returns an `(allowed, error)` tuple — it never raises, so callers must act
  on the result.
- `record_usage(org, units, usage_type, description, user=None,
  reference=None)` — charges the ledger (and, for prepaid orgs, enforces the
  balance floor — insufficient funds surface as HTTP 402). Pass a
  `reference` string to correlate the charge with your domain object.
- `refund_usage(org, reference)` — refunds the most recent unrefunded charge
  for that reference. Idempotent: a DB-level one-to-one
  (`refunded_transaction`) guarantees a charge can only be refunded once.
- `grant_credits(org, amount, description)` — credit top-ups (used by the
  signup grant and the Stripe Checkout webhook).

**Rates** resolve in order: per-org `Config(name='<usage_type>_rate')` →
`settings.USAGE_RATES[usage_type]` → `USAGE_RATES['default']` (the
`USAGE_RATE_DEFAULT` env var, default `0.10`).

**Locale knobs**: monthly billing periods (usage caps, invoices) roll over in
`BILLING_TIMEZONE` (default `UTC`), and Stripe checkouts/invoices use
`STRIPE_CURRENCY` (default `usd`) — both plain env vars.

**Invoicing**: on the 1st of each month `generate_monthly_invoices`
aggregates the previous month's ledger (usage minus refunds, grouped by
usage type and rate) into line items and creates a Stripe Invoice for each
subscribed org. Stripe auto-charges the card saved at subscription signup;
`invoice.paid` / `invoice.payment_failed` / `invoice.overdue` /
`invoice.voided` webhooks keep the local `Invoice` status in sync and toggle
`past_due` when payment fails.

### Adding a usage type

Say you're building a PDF-report feature billed per report:

1. Add a rate — either globally in settings
   (`USAGE_RATES = {'default': ..., 'report': Decimal('0.50')}`) or per-org
   via `POST /api/configs/` with `{"name": "report_rate", "value": "0.50"}`.
2. Gate the action in your view (`check_can_spend` returns a tuple — it does
   not raise):
   ```python
   allowed, error = check_can_spend(request.org, units=1, usage_type='report')
   if not allowed:
       return Response({'detail': error}, status=402)
   ```
3. Charge when the work happens:
   ```python
   record_usage(request.org, 1, 'report', 'Generated Q3 report',
                user=request.user, reference=f'report:{report.pk}')
   ```
4. Refund if it fails downstream:
   ```python
   refund_usage(request.org, reference=f'report:{report.pk}')
   ```

The billing summary, monthly limits, prepaid balance, Stripe invoicing, and
the frontend billing page all pick up the new usage type automatically —
line items and usage breakdowns group by `usage_type`.

---

## Frontend guide

```
frontend/src/
├── routes/            # TanStack Router file-based routes
│   ├── __root.tsx     # Clerk gate: SignedOut → sign-in, E2E bypass, Sentry boundary
│   ├── index.tsx      # Auto-activates the user's org, then redirects into /app
│   └── app/           # Authenticated shell (_layout.tsx) + pages (users, billing)
├── api/               # One module per resource — queryOptions factories + mutation hooks
├── lib/               # ApiClient (Clerk bearer injection, typed errors, 401 redirect)
├── ui/                # Catalyst-style Tailwind + Headless UI component kit (26 components)
├── components/shared/ # LoadingSpinner, RouteErrorComponent, TableSkeleton, ...
└── test/              # Vitest setup, MSW handlers, factories, test-utils
```

**API pattern**: components call `useApiClient()` to get an `ApiClient`
pre-authenticated with the current Clerk JWT, then pass it into query and
mutation factories:

```ts
const client = useApiClient()
const { data } = useQuery(getAllUsersQueryOptions(client))
```

Each module in `src/api/` exports `queryOptions()` factories (cache keys
co-located with fetchers) and `useMutation` hooks that invalidate the right
queries. Types in `src/types/` mirror the backend's snake_case responses,
including the pagination envelope.

**Admin gating**: the app shell reads the Clerk org role and hides/blocks
admin-only pages (billing, user management) for members. Clerk role/status
mutations invalidate queries on a short delay to absorb the race between the
Clerk API response and the webhook that syncs the change into the local DB.

**Unit tests**: `renderWithProviders()` wraps components with Query/Router/
Clerk mocks; `loginAs(mocks, 'org:admin' | 'org:member')` switches the
mocked Clerk role per test. MSW serves realistic API responses from
`src/test/handlers.ts` + `factories.ts`.

---

## Testing

### Backend

```bash
docker compose run --rm backend uv run python -m pytest tests/ -q
```

If the schema changed since your last run, rebuild the test database:

```bash
docker compose run --rm backend uv run python -m pytest --create-db tests/ -q
```

Covers auth, tenancy middleware, permissions, pagination, webhook handlers
(with **real Svix/Stripe signature verification**), the billing engine
(gate, charge, refund idempotency, invoice generation), Celery bootstrap
(subprocess import smoke test), and health probes.

### Frontend unit/integration

```bash
docker compose exec frontend npx vitest run          # tests only
docker compose exec frontend npm run test:coverage   # what CI runs
```

Route tests render the **real** route components (not test doubles) against
MSW, and `loginAs` covers admin-vs-member access.

### End-to-end (Playwright, real Clerk)

```bash
docker compose exec frontend npx playwright test
```

The E2E suite authenticates through **real Clerk**:

1. `e2e/global-setup.ts` creates a fresh Clerk user + org via the Clerk API,
   then seeds the Django DB by POSTing simulated webhook events (with
   `TEST=1`, Svix signature verification is skipped).
2. `e2e/auth.setup.ts` signs in via Clerk's ticket strategy and saves
   `storageState`; all specs inherit the authenticated session.
3. `global-teardown.ts` deletes the Clerk user + org.

**Requirements:** the backend must run with `TEST=1` (enables the test-only
endpoints below and skips webhook signature verification), and the
environment needs `CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY`. The Stripe
billing specs (`billing-stripe`, `buy-credits`, `invoices-modal`)
additionally need a **test-mode** `STRIPE_SECRET_KEY` on the backend.

TEST-mode-only endpoints used by E2E: `PATCH /api/billing/test-set-balance/`,
`POST /api/billing/test-seed-usage/`, `POST /api/billing/test-generate-invoices/`,
`POST /api/billing/test-link-billing-customer/`. A Django `--deploy` system
check fails the build if `TEST=1` is ever set without `DEBUG`, so these
cannot leak into production.

---

## Deployment

### Docker image

One multi-stage image (`backend/Dockerfile`) serves all three roles; ACA (or
any orchestrator) sets `CONTAINER_ROLE=api|worker|beat` per container. The
build stamps the git SHA into `app/health.py` (`DEPLOY_SHA` build arg) so
`/api/health/smoke/` reports exactly which version is serving — the deploy
workflows poll for it.

`entrypoint.sh` also has a migration guard: with `SKIP_AUTO_MIGRATE=true`
(production) the API container refuses to start if migrations are pending,
forcing them through the rehearsed CD path; with `false` (dev) it
auto-applies them on startup.

### CI (`.github/workflows/ci.yml`)

Three jobs on PRs:

- **backend** — pytest with a coverage floor, `makemigrations --check`
  (schema-drift guard), `pip-audit` (report-only), and
  `manage.py check --deploy` under production-like settings.
- **frontend** — typecheck, eslint (report-only), Vitest with coverage gate,
  `npm audit` (report-only).
- **e2e** — boots the full compose stack (including worker + beat, gated on
  `/api/health/worker/`), then runs Playwright against real Clerk.

### Azure (Bicep + deploy workflows)

`infra/` contains parameterized Bicep for: ACR, an ACA environment +
Log Analytics, a user-assigned managed identity, optional VNet with private
endpoints (prod), and three container apps (API with ingress + health
probes, worker, beat singleton). All resource names derive from the
`APP_NAME` param (default `app`): `<APP_NAME>-api-<env>`,
`<APP_NAME>-worker-<env>`, etc.

The deploy workflows (`deploy-dev.yml`, `deploy-prod.yml`,
`deploy-frontend.yml`) keep several patterns worth stealing even if you
don't deploy to Azure:

- **OIDC federation** — no long-lived cloud credentials in GitHub; Entra
  trusts short-lived tokens scoped to this repo + environment.
- **Migration rehearsal (prod)** — pending migrations are applied to a
  disposable promoted DB replica first, and a backup is taken, before
  touching the production database (requires a non-Burstable PostgreSQL
  tier; Burstable falls back to backup + migrate).
- **Zero-downtime deploys (prod)** — the API app runs in multiple-revision
  mode; the new revision is smoke-tested on its revision-specific FQDN at 0%
  traffic (asserting the expected `DEPLOY_SHA`) before traffic shifts and old
  revisions deactivate. A failed smoke test leaves the old revision serving.
- **Post-deploy verification** — public endpoint serves the new SHA, the
  Celery heartbeat is fresh (`/api/health/worker/`), and debug/test surfaces
  (Swagger, test endpoints) are confirmed unreachable in prod.

First-time provisioning is local: copy `infra/.env.example` to
`infra/.env.dev` / `.env.prod`, fill it in, then
`./infra/manage.sh preview dev` and `./infra/manage.sh init dev`. After
that, pushing to `development`/`main` deploys via CI. `manage.sh stop|start`
scales an environment to zero and back (dev cost control).

**Placeholders to fill before deploying:**

| Where | What |
|---|---|
| `infra/.env.example` → `.env.dev`/`.env.prod` | `RESOURCE_GROUP`, `APP_NAME`, `ACR_NAME`, secrets, DB/Clerk/Stripe/Sentry values |
| `.github/workflows/deploy-dev.yml` / `deploy-prod.yml` | `IMAGE_NAME` and `APP_BASE_NAME` workflow env (defaults `app-backend` / `app`; `APP_BASE_NAME` must match the Bicep `APP_NAME` param) |
| GitHub environment **variables** (`dev`, `prod`) | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (OIDC), `RESOURCE_GROUP`, `ENVIRONMENT_NAME`, `ACR_NAME`, `ACR_LOGIN_SERVER`, `CREATE_ACR`, `USE_VNET` + CIDRs, replica/CPU/memory sizing, `POSTGRES_HOST/DB/USER`, `CLERK_FRONTEND_API`, `CLERK_AUTHORIZED_PARTIES`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `BASE_URL`, `FRONTEND_URL`, `STORAGE_PROVIDER_CLASS`, `AZURE_STORAGE_ACCOUNT_NAME`, `AZURE_CONTAINER`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `FREE_CREDIT_AMOUNT`, `USAGE_RATE_DEFAULT`, `DEBUG`, `TEST`, `SKIP_AUTO_MIGRATE`, `API_CUSTOM_DOMAIN(_CERT)` (prod), `VITE_API_BASE_URL_DEV`/`_PROD`, `E2E_BASE_URL_DEV`, prod-only `AZURE_POSTGRES_RESOURCE_GROUP`/`AZURE_POSTGRES_SERVER_NAME` |
| GitHub environment **secrets** | `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `AZURE_POSTGRES_HOST/DB/USER/PASSWORD`, `CLERK_SECRET_KEY`, `CLERK_WEBHOOK_SIGNING_SECRET`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `CELERY_BROKER_URL`, `AZURE_STORAGE_ACCOUNT_KEY`, `E2E_CLERK_SECRET_KEY`, `E2E_VITE_CLERK_PUBLISHABLE_KEY`, `AZURE_SWA_TOKEN_DEV`/`_PROD`, `VITE_CLERK_PUBLISHABLE_KEY_DEV`/`_PROD`, optional `SENTRY_AUTH_TOKEN`/`SENTRY_ORG`/`SENTRY_PROJECT_BACKEND`/`SENTRY_PROJECT_FRONTEND`/`VITE_SENTRY_DSN` |
| `SECURITY.md` | Replace the placeholder security contact and scope hosts |

### Deployment gotchas (hard-won)

- **`SECURE_SSL_REDIRECT` must NOT be True on ACA** — TLS terminates at the
  ingress; the container sees plain HTTP, so redirecting causes a loop.
- **Uvicorn lifespan** — `app/worker.py` subclasses `UvicornWorker` with
  `lifespan=off`; Django doesn't handle ASGI lifespan events and every
  worker start would otherwise raise.
- **`CORS_ALLOWED_ORIGINS` — no trailing slashes**; `CLERK_AUTHORIZED_PARTIES`
  must contain the exact frontend origin or every authenticated call 403s.
- **Azure Redis** — use `rediss://...:6380`, don't URL-encode `=` in access
  keys, enable access-key auth, and allow Azure-service access in the
  firewall or health probes hang on the Redis ping.
- **DB pooling** — psycopg3 native pools are sized per container role via
  `DB_POOL_MIN_SIZE`/`DB_POOL_MAX_SIZE` (Bicep). When scaling API replicas,
  keep the multiplied total under PostgreSQL's `max_connections`.
- **Custom domains must live in Bicep** (`API_CUSTOM_DOMAIN`/`_CERT`) — a
  domain bound manually is stripped on the next declarative deploy.
- **Beat is a singleton** — `maxReplicas: 1`; don't rely on the scheduler to
  dedupe itself.
- **Frontend deploy uses `skip_app_build: true`** — the workflow builds with
  `npm run build` first (where `VITE_*` secrets exist), then uploads `dist/`.

---

## Project layout

```
backend/
├── app/
│   ├── models.py            # User, Organisation, OrganisationMembership, Config,
│   │                        # CreditTransaction, Invoice, CreditPurchase, WebhookEvent
│   ├── views.py             # UserViewSet, BillingViewSet, ConfigViewSet, ClerkWebhookView
│   ├── authentication.py    # ClerkJWTAuthentication
│   ├── middleware/          # Tenant context + request logging
│   ├── permissions.py       # IsOrgMember, IsOrgAdmin
│   ├── pagination.py        # StandardPagination envelope
│   ├── celery.py            # Celery app + heartbeat + invoicing tasks
│   ├── health.py            # health / smoke / worker probes
│   └── utils/
│       ├── billing.py       # credit/usage/refund/invoice engine
│       ├── clerk.py         # 13 webhook handlers
│       ├── stripe.py        # StripeMeteredBillingProvider + StripeWebhookView
│       ├── metered_billing.py  # provider ABC + mock
│       └── storage.py       # storage provider ABC + Azure/Mock
├── entrypoint.sh            # CONTAINER_ROLE=api|worker|beat dispatch + DB wait
└── tests/

frontend/
├── src/                     # see "Frontend guide" above
└── e2e/                     # Playwright + real-Clerk auth harness

infra/                       # Bicep modules + manage.sh + .env.example
.github/workflows/           # ci.yml, deploy-dev.yml, deploy-prod.yml, deploy-frontend.yml
```
