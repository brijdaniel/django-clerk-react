"""
Celery application and async tasks.

Bootstrap ordering in this module is load-bearing: the Celery app is created
and configured from Django settings BEFORE django.setup() runs, and model
imports happen only AFTER django.setup() — the worker is a fresh Python
process with no prior Django initialization, so importing models earlier
raises AppRegistryNotReady.

Tasks
-----
worker_heartbeat()
    Beat task (every WORKER_HEARTBEAT_INTERVAL_SECONDS). Writes a timestamp to
    Redis so /api/health/worker/ can prove that beat fired AND a worker
    consumed the task.

link_billing_customer(org_pk)
    Retries linking a Stripe customer ID to an org after subscription
    activation, with exponential backoff.

generate_monthly_invoices()
    Beat task (1st of each month). Aggregates usage from the CreditTransaction
    ledger and creates one invoice per subscribed org via the configured
    MeteredBillingProvider.
"""

import logging
import os
from datetime import datetime as dt
import zoneinfo

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')

import django
import redis
from celery import Celery, shared_task
from celery.signals import beat_init, task_failure, worker_process_init, worker_ready, worker_shutting_down
from django.conf import settings
from django.utils import timezone
from django.db import connections

app = Celery('app')
app.config_from_object('django.conf:settings', namespace='CELERY')
django.setup()

from app.models import Invoice, Organisation
from app.utils.billing import build_line_items
from app.utils.metered_billing import get_billing_provider
from app.health import _get_redis_client

logger = logging.getLogger(__name__)


@beat_init.connect
def _on_beat_init(**kwargs):
    logger.info('celery beat started (pid=%d)', os.getpid())


@worker_ready.connect
def _on_worker_ready(**kwargs):
    logger.info('celery worker ready (pid=%d)', os.getpid())


@worker_shutting_down.connect
def _on_worker_shutting_down(sig=None, how=None, **kwargs):
    logger.warning('celery worker shutting down (sig=%s, how=%s, pid=%d)', sig, how, os.getpid())


@worker_process_init.connect
def _close_db_connections_on_fork(**kwargs):
    """Close inherited DB connections after Celery worker fork.

    Prefork workers inherit the parent's DB connections, which are invalid
    in the child process.  With psycopg3 pooling this also resets the
    connection pool so the child starts fresh.
    """
    connections.close_all()


@task_failure.connect
def _on_task_failure(sender=None, task_id=None, exception=None, traceback=None, **kwargs):
    logger.error(
        'celery task failed: task=%s id=%s error=%s',
        sender.name if sender else 'unknown',
        task_id,
        str(exception),
        exc_info=(type(exception), exception, traceback) if exception else None,
    )


# ---------------------------------------------------------------------------
# Worker liveness heartbeat
# ---------------------------------------------------------------------------

@shared_task(name='app.celery.worker_heartbeat')
def worker_heartbeat() -> dict:
    """Record that beat fired a task and a worker consumed it.

    Read by /api/health/worker/ to detect a dead/misconfigured worker or beat.
    Stored in the broker Redis — NOT django cache — because the api container
    that serves the health probe is a separate process/replica from the worker.
    Best-effort: a Redis blip must never fail the task.
    """
    interval = float(getattr(settings, 'WORKER_HEARTBEAT_INTERVAL_SECONDS', 60))
    ttl = max(60, int(5 * interval))
    try:
        _get_redis_client().set(settings.WORKER_HEARTBEAT_KEY, timezone.now().isoformat(), ex=ttl)
    except redis.RedisError:
        logger.warning('Failed to write worker heartbeat', exc_info=True)
        return {'written': False}
    return {'written': True}


# ---------------------------------------------------------------------------
# Metered billing
# ---------------------------------------------------------------------------

@shared_task(name='app.celery.link_billing_customer', bind=True, max_retries=5)
def link_billing_customer(self, org_pk: int) -> None:
    """Retry linking a Stripe customer ID to an org after subscription activation.

    Called when the initial lookup in _handle_subscription_active fails
    (e.g. Clerk hasn't created the Stripe customer yet). Retries with
    exponential backoff: 60s, 120s, 240s, 480s, 960s.
    """
    org = Organisation.objects.get(pk=org_pk)
    if org.billing_customer_id:
        return  # already linked

    provider = get_billing_provider()
    result = provider.find_customer_by_org(org.clerk_org_id)
    if result.success:
        Organisation.objects.filter(pk=org.pk).update(
            billing_customer_id=result.customer_id,
        )
        logger.info(
            'Linked Stripe customer %s for org %s',
            result.customer_id, org.clerk_org_id,
        )
    else:
        logger.warning(
            'link_billing_customer: still no Stripe customer for org %s (attempt %d): %s',
            org.clerk_org_id, self.request.retries + 1, result.error,
        )
        raise self.retry(countdown=60 * (2 ** self.request.retries))


# One Stripe invoice (several API calls) per subscribed org — monthly, slow.
@shared_task(name='app.celery.generate_monthly_invoices', time_limit=3600, soft_time_limit=3540)
def generate_monthly_invoices() -> dict:
    """Generate and send invoices for all subscribed orgs for the previous month.

    Runs on the 1st of each month via beat schedule. Aggregates usage from
    CreditTransaction records, nets refunds, and creates an invoice per org
    via the configured MeteredBillingProvider.

    Idempotent: skips orgs that already have a non-void invoice for the period.
    """
    billing_tz = zoneinfo.ZoneInfo(getattr(settings, 'BILLING_TIMEZONE', 'UTC'))
    period_start, period_end = _previous_month_boundaries(billing_tz)
    provider = get_billing_provider()

    created = 0
    skipped = 0
    failed = 0

    for org in Organisation.objects.filter(
        billing_mode=Organisation.BILLING_SUBSCRIBED,
        billing_customer_id__isnull=False,
    ):
        # Idempotency: skip if a non-void invoice already exists for this period
        if Invoice.objects.filter(
            organisation=org,
            period_start=period_start,
        ).exclude(status=Invoice.STATUS_VOID).exists():
            skipped += 1
            continue

        line_items = build_line_items(org, period_start, period_end)

        if not line_items:
            skipped += 1
            continue

        result = provider.create_invoice(
            customer_id=org.billing_customer_id,  # type: ignore[arg-type]  # filtered by __isnull=False
            line_items=line_items,
            period_start=period_start,
            period_end=period_end,
        )

        if result.success:
            Invoice.objects.create(
                organisation=org,
                provider_invoice_id=result.invoice_id,
                status=result.status or Invoice.STATUS_OPEN,
                amount=sum(item.amount for item in line_items),
                invoice_url=result.invoice_url,
                period_start=period_start,
                period_end=period_end,
            )
            logger.info(
                'Created invoice %s ($%s) for org %s, period %s to %s',
                result.invoice_id,
                sum(item.amount for item in line_items),
                org.clerk_org_id,
                period_start.date(), period_end.date(),
            )
            created += 1
        else:
            logger.error(
                'Failed to create invoice for org %s (period %s to %s): %s',
                org.clerk_org_id, period_start.date(), period_end.date(), result.error,
            )
            failed += 1

    logger.info(
        'generate_monthly_invoices: created=%d, skipped=%d, failed=%d',
        created, skipped, failed,
    )
    return {'created': created, 'skipped': skipped, 'failed': failed}


def _previous_month_boundaries(tz) -> tuple:
    """Return (start, end) datetimes for the previous calendar month in the given timezone."""

    now = dt.now(tz)
    # First day of current month
    first_of_current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Last moment of previous month = first of current - 1 microsecond
    # But we use period_end as exclusive upper bound, so period_end = first_of_current
    period_end = first_of_current
    # First of previous month
    if now.month == 1:
        period_start = first_of_current.replace(year=now.year - 1, month=12)
    else:
        period_start = first_of_current.replace(month=now.month - 1)
    return period_start, period_end
