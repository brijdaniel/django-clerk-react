"""
Billing utilities for the credit/usage system.

Two billing modes:
  - 'prepaid':    org has a dollar balance; spending is blocked when the balance
                  is exhausted. Orgs start with free credits and can purchase
                  more via Stripe.
  - 'subscribed': org has an active Clerk Billing subscription; spending is never
                  balance-gated, but usage is tracked per usage type for
                  end-of-month metered billing.

All monetary amounts are Decimal in dollars. The `usage_type` parameter is a
free-form string ('api_call', 'report', ...) so new usage types need no schema
changes — only a rate in settings.USAGE_RATES (or a per-org Config override)
and a new call site.

Refund idempotency is keyed on `reference` — a free-form correlation string
(e.g. 'order:1234') stored on each charge. refund_usage(org, reference) finds
the most recent DEDUCT/USAGE transaction with that reference that has not been
refunded yet and reverses exactly that charge. The one-to-one
refunded_transaction link enforces refund-at-most-once per charge at the DB
level, while still allowing a reference that is charged again on retry to be
refunded again if the retry also fails.
"""

import logging
import zoneinfo
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.db.models import Case, F, Sum, When

from rest_framework.exceptions import APIException

from app.models import CreditTransaction, Config
from app.utils.metered_billing import InvoiceLineItem

logger = logging.getLogger(__name__)

def _billing_tz() -> zoneinfo.ZoneInfo:
    """Timezone billing month boundaries roll over in (settings.BILLING_TIMEZONE)."""
    return zoneinfo.ZoneInfo(getattr(settings, 'BILLING_TIMEZONE', 'UTC'))


class InsufficientBalanceError(APIException):
    """Raised when a prepaid deduction would take the balance below zero.

    An APIException so view-layer callers surface it as HTTP 402 automatically;
    the deduction transaction is rolled back by the surrounding atomic block.
    """
    status_code = 402
    default_detail = 'Insufficient balance. Purchase more credits to continue.'


def _month_start() -> datetime:
    now = datetime.now(_billing_tz())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def grant_credits(org, amount: Decimal, description: str) -> CreditTransaction:
    """Add dollar credit to org balance. Always succeeds.

    Returns the GRANT transaction (its balance_after holds the new balance),
    so callers can link it directly instead of guessing the row afterwards.
    """
    with db_transaction.atomic():
        org.__class__.objects.filter(pk=org.pk).update(
            credit_balance=F('credit_balance') + amount
        )
        org.refresh_from_db(fields=['credit_balance'])

        tx = CreditTransaction.objects.create(
            organisation=org,
            transaction_type=CreditTransaction.GRANT,
            amount=amount,
            balance_after=org.credit_balance,
            description=description,
            usage_type=None,
            reference=None,
            created_by=None,
        )

    logger.info(
        'Granted $%s to org %s. New balance: $%s',
        amount, org.clerk_org_id, org.credit_balance,
    )
    return tx


def get_balance(org) -> Decimal:
    """Read the current credit_balance fresh from DB."""
    return org.__class__.objects.values_list('credit_balance', flat=True).get(pk=org.pk)


def get_rate(usage_type: str, org=None) -> Decimal:
    """Return the per-unit billing rate for a usage type.

    Resolution order:
      1. Per-org Config override (name='<usage_type>_rate')
      2. settings.USAGE_RATES[usage_type]
      3. settings.USAGE_RATES['default']
    Raises ValueError when no rate can be resolved.
    """
    if org is not None:
        config = Config.objects.filter(organisation=org, name=f'{usage_type}_rate').first()
        if config is not None:
            return Decimal(config.value)

    rates = getattr(settings, 'USAGE_RATES', {})
    rate = rates.get(usage_type, rates.get('default'))
    if rate is None:
        raise ValueError(
            f'No billing rate configured for usage type "{usage_type}". '
            f'Add it (or a "default" entry) to settings.USAGE_RATES.'
        )
    return Decimal(str(rate))


def _net_spend(qs) -> Decimal:
    """Sum charges (deduct/usage) minus refunds over a CreditTransaction queryset.

    Refunded charges must not keep consuming the monthly cap — a failed action
    that was refunded costs the org nothing, so it frees its share of the limit.
    """
    result = qs.filter(
        transaction_type__in=[
            CreditTransaction.DEDUCT, CreditTransaction.USAGE, CreditTransaction.REFUND,
        ],
    ).aggregate(
        total=Sum(
            Case(
                When(transaction_type=CreditTransaction.REFUND, then=-F('amount')),
                default=F('amount'),
            )
        )
    )['total']
    return result or Decimal('0.00')


def get_monthly_usage(org, usage_type: str) -> Decimal:
    """
    Net CreditTransaction dollar amounts for a given usage type this calendar
    month (settings.BILLING_TIMEZONE): deduct/usage charges minus refunds.
    """
    return _net_spend(CreditTransaction.objects.filter(
        organisation=org,
        usage_type=usage_type,
        created_at__gte=_month_start(),
    ))


def get_total_monthly_spend(org) -> Decimal:
    """
    Net CreditTransaction dollar amounts this month across all usage types:
    per-unit charges (type=deduct or type=usage) minus refunds.
    The flat Clerk Billing subscription fee is managed entirely by Clerk and is NOT included.
    """
    return _net_spend(CreditTransaction.objects.filter(
        organisation=org,
        created_at__gte=_month_start(),
    ))


def get_monthly_limit_info(org) -> dict:
    """
    Returns {current, limit, remaining} for the org's monthly spending cap.
    Reads Config(name='monthly_limit') — a single dollar cap for the whole org.
    current = total usage charges this month (not subscription fee).
    limit/remaining are None if no cap is configured (uncapped).
    """
    current = get_total_monthly_spend(org)

    config = Config.objects.filter(organisation=org, name='monthly_limit').first()
    if not config:
        return {'current': current, 'limit': None, 'remaining': None}

    limit = Decimal(config.value)
    return {
        'current': current,
        'limit': limit,
        'remaining': limit - current,
    }


def check_can_spend(org, units: int, usage_type: str) -> tuple:
    """
    Unified pre-spend gate for any usage type. Returns (allowed: bool, error: str | None).

    cost = units * get_rate(usage_type, org)

    Checks (in order):
    0. Past-due billing — blocks all spending when subscription payment is overdue
    1. Monthly spending limit (both modes) — Config(name='monthly_limit')
    2. Dollar balance (prepaid mode only)

    This is an unlocked pre-check — record_usage() holds the row lock and
    enforces the actual balance floor. Adding a new usage type requires no
    changes here — just pass the new usage_type string and ensure a rate
    resolves via get_rate().
    """
    if org.billing_mode == org.BILLING_PAST_DUE:
        return False, 'Subscription payment is past due. Please update your billing details.'

    cost = Decimal(units) * get_rate(usage_type, org)
    info = get_monthly_limit_info(org)

    if info['limit'] is not None and info['remaining'] < cost:
        return False, (
            f'Monthly spending limit reached '
            f'(${info["current"]:.2f} of ${info["limit"]:.2f})'
        )

    if org.billing_mode == org.BILLING_PREPAID:
        if get_balance(org) < cost:
            return False, 'Insufficient balance. Purchase more credits to continue.'

    return True, None


def record_usage(org, units: int, usage_type: str, description: str,
                 user=None, reference: str | None = None) -> CreditTransaction:
    """
    Record a billable action. Cost = units * get_rate(usage_type, org).
    Returns the created CreditTransaction.

    prepaid mode:    SELECT FOR UPDATE → deduct credit_balance → INSERT type=deduct
    subscribed mode: INSERT type=usage, balance unchanged (invoiced monthly)

    Raises InsufficientBalanceError (HTTP 402 via DRF) if the deduction would
    take a prepaid balance below zero. check_can_spend() is an unlocked
    pre-check, so concurrent spends near zero balance can all pass it — this
    locked floor is what actually prevents negative balances.

    user: the User who initiated the action (request.user); None for system/webhook actions.
    reference: free-form correlation key (e.g. 'order:1234') used by
    refund_usage() to reverse this charge.
    """
    rate = get_rate(usage_type, org)
    cost = Decimal(units) * rate

    if org.billing_mode == org.BILLING_PREPAID:
        with db_transaction.atomic():
            locked_org = org.__class__.objects.select_for_update().get(pk=org.pk)
            new_balance = locked_org.credit_balance - cost
            if new_balance < 0:
                raise InsufficientBalanceError()
            org.__class__.objects.filter(pk=org.pk).update(
                credit_balance=F('credit_balance') - cost
            )
            tx = CreditTransaction.objects.create(
                organisation=org,
                transaction_type=CreditTransaction.DEDUCT,
                amount=cost,
                balance_after=new_balance,
                description=description,
                usage_type=usage_type,
                reference=reference,
                created_by=user,
                unit_rate=rate,
            )
    else:
        # subscribed mode — track usage without touching balance
        current_balance = get_balance(org)
        tx = CreditTransaction.objects.create(
            organisation=org,
            transaction_type=CreditTransaction.USAGE,
            amount=cost,
            balance_after=current_balance,
            description=description,
            usage_type=usage_type,
            reference=reference,
            created_by=user,
            unit_rate=rate,
        )

    logger.debug(
        'Recorded %s usage: %s units × $%s = $%s for org %s',
        usage_type, units, rate, cost, org.clerk_org_id,
    )
    return tx


def refund_usage(org, reference: str, description: str | None = None) -> None:
    """Reverse the credit charge recorded under a reference.

    Idempotent per charge: each DEDUCT/USAGE transaction is refunded at most once
    (REFUND rows link to the charge they reverse via refunded_transaction, enforced
    by a one-to-one constraint). A reference that is charged again on retry can
    therefore be refunded again if the retry also fails.

    prepaid mode:    SELECT FOR UPDATE org → credit_balance += amount → INSERT type=refund
    subscribed mode: SELECT FOR UPDATE org → INSERT type=refund only (balance unchanged)

    No-op (logged at DEBUG) when there is no unrefunded charge for the reference.

    Raises ValueError for a falsy reference — reference=None/'' would otherwise
    match charges recorded without a reference and reverse an arbitrary one.
    """
    if not reference:
        raise ValueError('refund_usage requires a non-empty reference')
    try:
        with db_transaction.atomic():
            # Serialize concurrent refund attempts for the same org (two code
            # paths can both try to reverse the same charge at once). The
            # second caller blocks here until the first commits, then re-reads
            # and finds the charge already refunded.
            org.__class__.objects.select_for_update().get(pk=org.pk)

            # Find the most recent charge for this reference that has not been refunded yet
            original_tx = CreditTransaction.objects.filter(
                organisation=org,
                reference=reference,
                transaction_type__in=[CreditTransaction.DEDUCT, CreditTransaction.USAGE],
                refund__isnull=True,
            ).order_by('-created_at').first()

            if not original_tx:
                logger.debug(
                    'refund_usage: no unrefunded charge for reference %r — nothing to refund',
                    reference,
                )
                return

            amount = original_tx.amount
            original_rate = original_tx.unit_rate
            if description is None:
                description = f'Refund: {original_tx.description}'

            if org.billing_mode == org.BILLING_PREPAID:
                org.__class__.objects.filter(pk=org.pk).update(
                    credit_balance=F('credit_balance') + amount
                )
            new_balance = get_balance(org)
            CreditTransaction.objects.create(
                organisation=org,
                transaction_type=CreditTransaction.REFUND,
                amount=amount,
                balance_after=new_balance,
                description=description,
                usage_type=original_tx.usage_type,
                reference=reference,
                created_by=None,
                unit_rate=original_rate,
                refunded_transaction=original_tx,
            )
    except IntegrityError:
        # Backstop only: callers that already hold the org lock in an outer
        # transaction cannot race here, but if a refund for the same charge
        # slips through anyway the one-to-one constraint on refunded_transaction
        # rejects it and the atomic block rolls back the balance update.
        logger.warning(
            'refund_usage: charge for reference %r was refunded concurrently, skipping',
            reference,
        )
        return

    logger.info(
        'Refunded $%s to org %s for reference %r',
        amount, org.clerk_org_id, reference,
    )


def build_line_items(org, period_start: datetime, period_end: datetime) -> list[InvoiceLineItem]:
    """Aggregate CreditTransaction records into invoice line items.

    Groups by (usage_type, unit_rate), nets usage minus refunds. Returns a list
    of InvoiceLineItem dataclasses, or an empty list if net usage is zero.

    Transactions with unit_rate=NULL (legacy rows created before per-org rates)
    are grouped separately and fall back to get_rate(usage_type, org).
    """
    usage_qs = CreditTransaction.objects.filter(
        organisation=org,
        created_at__gte=period_start,
        created_at__lt=period_end,
        transaction_type__in=[CreditTransaction.USAGE, CreditTransaction.REFUND],
        usage_type__isnull=False,
    )

    groups = list(
        usage_qs.values_list('usage_type', 'unit_rate').distinct()
    )
    logger.info(
        'build_line_items: org=%s period=%s to %s groups=%s qs_count=%d',
        org.clerk_org_id, period_start, period_end, groups, usage_qs.count(),
    )
    line_items = []

    for usage_type, stored_rate in groups:
        group_qs = usage_qs.filter(usage_type=usage_type, unit_rate=stored_rate) if stored_rate is not None \
            else usage_qs.filter(usage_type=usage_type, unit_rate__isnull=True)

        usage_total = group_qs.filter(
            transaction_type=CreditTransaction.USAGE,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        refund_total = group_qs.filter(
            transaction_type=CreditTransaction.REFUND,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        net_amount = usage_total - refund_total
        logger.info(
            'build_line_items: usage_type=%s rate=%s usage=%s refund=%s net=%s',
            usage_type, stored_rate, usage_total, refund_total, net_amount,
        )
        if net_amount <= 0:
            continue

        rate = stored_rate.normalize() if stored_rate is not None else get_rate(usage_type, org)
        quantity = int(net_amount / rate) if rate > 0 else 0

        line_items.append(InvoiceLineItem(
            description=f'{usage_type} usage: {quantity} units @ ${rate}',
            amount=net_amount,
            quantity=quantity,
            unit_amount=rate,
            usage_type=usage_type,
        ))

    return line_items


def get_current_month_preview(org) -> dict:
    """Build a preview of what the current month's invoice would look like.

    Uses the same aggregation logic as monthly invoice generation but for the
    current month-to-date (1st of month → now in settings.BILLING_TIMEZONE).
    """
    period_start = _month_start()
    period_end = datetime.now(_billing_tz())

    line_items = build_line_items(org, period_start, period_end)

    total = sum(item.amount for item in line_items)

    return {
        'total': str(total),
        'period_start': period_start.isoformat(),
        'period_end': period_end.isoformat(),
        'line_items': [
            {
                'usage_type': item.usage_type,
                'quantity': item.quantity,
                'rate': str(item.unit_amount),
                'amount': str(item.amount),
            }
            for item in line_items
        ],
    }
