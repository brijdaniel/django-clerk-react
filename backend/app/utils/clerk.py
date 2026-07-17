import logging
from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from clerk_backend_api import Clerk
from clerk_backend_api.models.clerkbaseerror import ClerkBaseError
from rest_framework.exceptions import APIException

from app.utils.billing import grant_credits
from app.utils.metered_billing import get_billing_provider
from app.celery import link_billing_customer
from app.models import Organisation, OrganisationMembership, User

logger = logging.getLogger(__name__)


class WebhookProcessingError(APIException):
    """Raised when a webhook handler cannot process the event due to missing dependencies.

    Returns 422 so Svix retries the delivery later.
    """
    status_code = 422
    default_detail = 'Webhook processing deferred'


# Webhooks
def _handle_user_created(data):
    email = ''
    email_addresses = data.get('email_addresses', [])
    for addr in email_addresses:
        if addr.get('id') == data.get('primary_email_address_id'):
            email = addr.get('email_address', '')
            break

    User.objects.update_or_create(
        clerk_id=data['id'],
        defaults={
            'email': email,
            'first_name': data.get('first_name', ''),
            'last_name': data.get('last_name', ''),
            'is_active': True,
        },
    )


def _handle_user_updated(data):
    _handle_user_created(data)


def _handle_user_deleted(data):
    User.objects.filter(clerk_id=data['id']).update(is_active=False)


def _handle_organisation_created(data):
    org, created = Organisation.objects.update_or_create(
        clerk_org_id=data['id'],
        defaults={
            'name': data.get('name', ''),
            'slug': data.get('slug', ''),
            'is_active': True
        },
    )

    if created:
        free_amount = settings.FREE_CREDIT_AMOUNT
        grant_credits(
            org,
            amount=free_amount,
            description=f'Free trial credits on signup',
        )
        logger.info('Granted $%s free credits to new org %s', free_amount, org.clerk_org_id)


def _handle_organisation_updated(data):
    _handle_organisation_created(data)


def _handle_organisation_deleted(data):
    # Soft-delete the organisation
    Organisation.objects.filter(clerk_org_id=data['id']).update(is_active=False)

    # Soft-delete memberships
    memberships = OrganisationMembership.objects.filter(organisation__clerk_org_id=data['id'], is_active=True)
    memberships.update(is_active=False)

    # Soft-delete users who have no other active memberships
    user_ids = list(memberships.values_list('user_id', flat=True))
    User.objects.filter(
        id__in=user_ids,
    ).exclude(
        organisationmembership__is_active=True,
    ).update(is_active=False)


def _handle_membership_created(data):
    user_id = data.get('public_user_data', {}).get('user_id')
    if not user_id:
        raise WebhookProcessingError('membership payload missing user_id')

    user = User.objects.filter(clerk_id=user_id).first()
    if not user:
        raise WebhookProcessingError(f'user {user_id} not found, deferring')

    org_data = data.get('organization', {})
    org_id = org_data.get('id')
    if not org_id:
        raise WebhookProcessingError('membership payload missing organization.id')

    org, created = Organisation.objects.get_or_create(
        clerk_org_id=org_id,
        defaults={'name': org_data.get('name', ''), 'slug': org_data.get('slug', '')},
    )
    if created:
        logger.warning('Organisation %s created by membership handler (out-of-order webhook)', org_id)
        free_amount = settings.FREE_CREDIT_AMOUNT
        grant_credits(org, amount=free_amount, description='Free trial credits on signup')
        logger.info('Granted $%s free credits to new org %s', free_amount, org_id)

    OrganisationMembership.objects.update_or_create(
        user=user,
        organisation=org,
        defaults={'role': data.get('role', 'member'), 'is_active': True},
    )
    # Ensure the user account is active (handles reactivation case)
    if not user.is_active:
        User.objects.filter(pk=user.pk).update(is_active=True)


def _handle_membership_updated(data):
    _handle_membership_created(data)


def _handle_membership_deleted(data):
    user_id = data.get('public_user_data', {}).get('user_id')
    org_id = data.get('organization', {}).get('id')

    if not user_id or not org_id:
        raise WebhookProcessingError('membership.deleted payload missing user_id or organization.id')

    OrganisationMembership.objects.filter(
        user__clerk_id=user_id,
        organisation__clerk_org_id=org_id,
    ).update(is_active=False)

    # Deactivate user if they have no other active memberships
    User.objects.filter(
        clerk_id=user_id,
    ).exclude(
        organisationmembership__is_active=True,
    ).update(is_active=False)


# ---------------------------------------------------------------------------
# Clerk Billing webhook handlers
#
# Clerk billing events: subscription.created, subscription.updated,
# subscription.active, subscription.pastDue
#
# Payload is a CommerceSubscription object with fields:
#   id, status, payer_id, instance_id, created_at, updated_at, active_at,
#   past_due_at, subscription_items, payer, items, latest_payment_id, etc.
#
# The org ID is in `payer_id` (e.g. "org_xxx").
# See: https://github.com/clerk/clerk-sdk-python/blob/main/src/clerk_backend_api/models/commercesubscription.py
# ---------------------------------------------------------------------------

def _billing_event_timestamp(data):
    """Extract the subscription payload's updated_at as an aware datetime.

    Clerk sends epoch milliseconds; ISO strings are handled defensively.
    Returns None when the payload carries no usable timestamp.
    """
    raw = data.get('updated_at') or data.get('created_at')
    if raw in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        pass
    try:
        parsed = datetime.fromisoformat(str(raw))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)
    except (TypeError, ValueError):
        return None


def _is_stale_billing_event(org, data, event_label):
    """True when this event is older than the last applied billing event.

    Svix delivers unordered: a delayed subscription.updated(active) must not
    overwrite a newer past_due state. Events without a timestamp apply as
    before (no ordering information).
    """
    ts = _billing_event_timestamp(data)
    if ts is None or org.billing_event_at is None:
        return False
    if ts < org.billing_event_at:
        logger.warning(
            '%s: stale event for org %s (event %s < last applied %s) — skipping',
            event_label, org.clerk_org_id, ts.isoformat(), org.billing_event_at.isoformat(),
        )
        return True
    return False


def _extract_billing_org_id(data, event_label='billing'):
    """Extract the organisation Clerk ID from a billing webhook payload.

    The org ID is in ``data.payer.organization_id`` (CommercePayerResponse).
    ``payer_id`` is a commerce payer ID (cpayer_xxx), NOT the org ID.
    See: https://github.com/clerk/clerk-sdk-python/blob/main/src/clerk_backend_api/models/commercepayerresponse.py
    """
    payer = data.get('payer')
    org_id = payer.get('organization_id') if isinstance(payer, dict) else None
    if not org_id:
        raise WebhookProcessingError(
            f'{event_label}: no org id found. payer={repr(payer)[:300]} data_keys={list(data.keys())}'
        )
    return org_id


def _handle_subscription_active(data):
    """Transition org to subscribed mode when a Clerk Billing subscription becomes active."""
    org_id = _extract_billing_org_id(data, 'subscription.active')
    org = Organisation.objects.filter(clerk_org_id=org_id).first()
    if not org:
        raise WebhookProcessingError(f'subscription.active: org {org_id} not found')

    if _is_stale_billing_event(org, data, 'subscription.active'):
        return

    # A Clerk subscription becoming active only clears Clerk-set past_due.
    # If a Stripe metered invoice is still unpaid, the org stays blocked until
    # invoice.paid clears it.
    if (org.billing_mode == Organisation.BILLING_PAST_DUE
            and org.past_due_source == Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE):
        logger.warning(
            'subscription.active: org %s stays past_due — Stripe invoice still unpaid', org_id,
        )
        return

    Organisation.objects.filter(pk=org.pk).update(
        billing_mode=Organisation.BILLING_SUBSCRIBED,
        past_due_source=None,
        billing_event_at=_billing_event_timestamp(data) or org.billing_event_at,
    )

    logger.info('Org %s transitioned to subscribed billing mode', org_id)
    try:
        clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)
        clerk_client.organizations.update(
            organization_id=org_id,
            private_metadata={'billing_suspended': False},
        )
        logger.info('Clerk org %s billing_suspended cleared', org_id)
    except ClerkBaseError:
        logger.error(
            'Failed to clear Clerk billing_suspended for org %s', org_id, exc_info=True
        )

    # Link the Stripe customer that Clerk created during subscription signup
    org = Organisation.objects.get(clerk_org_id=org_id)
    if not org.billing_customer_id:
        provider = get_billing_provider()
        result = provider.find_customer_by_org(org.clerk_org_id)
        if result.success:
            Organisation.objects.filter(pk=org.pk).update(
                billing_customer_id=result.customer_id,
            )
            logger.info(
                'Linked Stripe customer %s for org %s',
                result.customer_id, org_id,
            )
        else:
            # Clerk may not have created the Stripe customer yet — retry later
            link_billing_customer.apply_async(args=[org.pk], countdown=60)
            logger.warning(
                'Could not find Stripe customer for org %s, queued retry: %s',
                org_id, result.error,
            )


def _handle_subscription_canceled(data):
    """Revert org to prepaid mode when a Clerk Billing subscription is cancelled or ended."""
    org_id = _extract_billing_org_id(data, 'subscription.canceled')
    org = Organisation.objects.filter(clerk_org_id=org_id).first()
    if not org:
        raise WebhookProcessingError(f'subscription.canceled: org {org_id} not found')

    if _is_stale_billing_event(org, data, 'subscription.canceled'):
        return

    Organisation.objects.filter(pk=org.pk).update(
        billing_mode=Organisation.BILLING_PREPAID,
        past_due_source=None,
        billing_event_at=_billing_event_timestamp(data) or org.billing_event_at,
    )
    logger.info('Org %s reverted to prepaid billing mode (subscription cancelled)', org_id)


def _handle_subscription_past_due(data):
    """Set billing_mode=past_due and disable the org in Clerk when subscription is past due."""
    org_id = _extract_billing_org_id(data, 'subscription.pastDue')
    org = Organisation.objects.filter(clerk_org_id=org_id).first()
    if not org:
        raise WebhookProcessingError(f'subscription.pastDue: org {org_id} not found')

    if _is_stale_billing_event(org, data, 'subscription.pastDue'):
        return

    # Only the obligation that blocks first "owns" past_due_source, and only that
    # source's paid signal clears it. Don't relabel an org that is already
    # past_due (mirrors _handle_invoice_payment_failed): otherwise a later
    # subscription.active could clear past_due while a Stripe invoice that blocked
    # first is still unpaid. If both are unpaid, the still-unpaid obligation
    # re-blocks on its next dunning event.
    was_past_due = org.billing_mode == Organisation.BILLING_PAST_DUE
    org.billing_mode = Organisation.BILLING_PAST_DUE
    update_fields = ['billing_mode', 'billing_event_at']
    if not was_past_due:
        org.past_due_source = Organisation.PAST_DUE_SOURCE_CLERK
        update_fields.append('past_due_source')
    org.billing_event_at = _billing_event_timestamp(data) or org.billing_event_at
    org.save(update_fields=update_fields)
    logger.warning('subscription.pastDue: org %s set to past_due', org_id)

    try:
        clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)
        clerk_client.organizations.update(
            organization_id=org_id,
            private_metadata={'billing_suspended': True},
        )
        logger.info('Clerk org %s marked billing_suspended=True', org_id)
    except ClerkBaseError:
        logger.error(
            'Failed to set Clerk billing_suspended for org %s', org_id, exc_info=True
        )


def _has_active_paid_plan(data) -> bool:
    """Check whether the subscription has an active paid plan.

    Clerk subscriptions can be 'active' with only a free plan (e.g. after
    downgrading). We only set billing_mode='subscribed' when there's at
    least one item with status='active' and plan.amount > 0.
    """
    items = data.get('items') or []
    return any(
        item.get('status') == 'active'
        and (item.get('plan', {}).get('amount') or 0) > 0
        for item in items
    )


def _handle_subscription_updated(data):
    """Route subscription.created/updated events based on the status field.

    When status is 'active', we also check the items to see if there's a
    paid plan — a subscription with only a free plan means the org should
    be on trial, not subscribed.
    """
    status = data.get('status')
    has_paid = _has_active_paid_plan(data)
    logger.info('subscription.updated: status=%s has_paid_plan=%s', status, has_paid)

    if status == 'active' and has_paid:
        _handle_subscription_active(data)
    elif status == 'active' and not has_paid:
        # Downgraded to free-only or no active paid items — revert to trial
        _handle_subscription_canceled(data)
    elif status == 'past_due':
        _handle_subscription_past_due(data)
    elif status in ('canceled', 'ended'):
        _handle_subscription_canceled(data)
    else:
        logger.info('subscription.updated: no action for status=%s', status)


WEBHOOK_HANDLERS = {
    'user.created': _handle_user_created,
    'user.updated': _handle_user_updated,
    'user.deleted': _handle_user_deleted,
    'organization.created': _handle_organisation_created,
    'organization.updated': _handle_organisation_updated,
    'organization.deleted': _handle_organisation_deleted,
    'organizationMembership.created': _handle_membership_created,
    'organizationMembership.updated': _handle_membership_updated,
    'organizationMembership.deleted': _handle_membership_deleted,
    # Clerk Billing events
    'subscription.created': _handle_subscription_updated,
    'subscription.updated': _handle_subscription_updated,
    'subscription.active': _handle_subscription_active,
    'subscription.pastDue': _handle_subscription_past_due,
}
