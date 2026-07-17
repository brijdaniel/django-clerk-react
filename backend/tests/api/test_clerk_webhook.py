"""
Tests for Clerk webhook endpoint.

Tests:
- POST /api/webhooks/clerk/ handles all event types
- Signature verification
- Event processing (user, organization, membership events)
"""

import json
import threading
from datetime import datetime, timezone as dt_timezone

import pytest
from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient
from svix.webhooks import Webhook, WebhookVerificationError
from unittest.mock import Mock, patch
from rest_framework import status

from app.models import (
    Config,
    CreditTransaction,
    Organisation,
    OrganisationMembership,
    User,
    WebhookEvent,
)
from tests.factories import (
    ConfigFactory,
    OrganisationFactory,
    OrganisationMembershipFactory,
    UserFactory,
)


# A valid base64 whsec secret ("test" base64-encoded). svix strips the
# ``whsec_`` prefix and base64-decodes the remainder.
_VALID_SIGNING_SECRET = 'whsec_dGVzdA=='


def _sign_payload(payload, secret=_VALID_SIGNING_SECRET, svix_id='msg_signed', timestamp=None):
    """Sign a payload with a real svix Webhook so the verify branch passes.

    Returns ``(body, headers)`` where ``body`` is the exact string that must be
    POSTed (the signature covers the literal request body bytes) and ``headers``
    are the svix-* headers Django expects (HTTP_ prefixed).

    The timestamp defaults to *now* so the signature falls inside svix's
    ~5-minute tolerance window.
    """
    body = json.dumps(payload)
    ts = timestamp or datetime.now(tz=dt_timezone.utc)
    signature = Webhook(secret).sign(msg_id=svix_id, timestamp=ts, data=body)
    headers = {
        'HTTP_SVIX_ID': svix_id,
        'HTTP_SVIX_TIMESTAMP': str(int(ts.timestamp())),
        'HTTP_SVIX_SIGNATURE': signature,
    }
    return body, headers


# Helper to mock webhook signature verification
def mock_webhook_verify(body, headers):
    """Mock svix.Webhook.verify() - parses and returns the JSON payload."""
    return json.loads(body)


@pytest.mark.django_db
class TestClerkWebhookSignature:
    """Signature verification outside TEST mode — previously untested.

    The endpoint must reject forged payloads: a signature failure returns 400
    and produces no side effects.
    """

    _payload = {
        'type': 'organization.created',
        'data': {'id': 'org_forged', 'name': 'Forged Org', 'slug': 'forged'},
    }

    @override_settings(TEST=False, CLERK_WEBHOOK_SIGNING_SECRET='whsec_dGVzdA==')
    @patch('svix.Webhook.verify')
    def test_invalid_signature_rejected_with_no_side_effects(self, mock_verify, api_client):
        mock_verify.side_effect = WebhookVerificationError('bad signature')

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(self._payload),
            content_type='application/json',
            HTTP_SVIX_ID='msg_forged',
            HTTP_SVIX_TIMESTAMP='1700000000',
            HTTP_SVIX_SIGNATURE='v1,forged',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Organisation.objects.filter(clerk_org_id='org_forged').exists()

    @override_settings(TEST=False, CLERK_WEBHOOK_SIGNING_SECRET='whsec_dGVzdA==')
    def test_missing_signature_headers_rejected(self, api_client):
        """Absent svix headers must fail verification, not be processed."""
        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(self._payload),
            content_type='application/json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Organisation.objects.filter(clerk_org_id='org_forged').exists()

    @override_settings(TEST=False, CLERK_WEBHOOK_SIGNING_SECRET='')
    def test_missing_signing_secret_returns_500(self, api_client):
        """An unconfigured secret must fail closed, never skip verification."""
        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(self._payload),
            content_type='application/json',
        )

        assert response.status_code == 500
        assert not Organisation.objects.filter(clerk_org_id='org_forged').exists()


@pytest.mark.django_db
class TestClerkWebhookDedup:
    """Replay/duplicate suppression on the svix message id."""

    def _post(self, api_client, payload, svix_id):
        return api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_SVIX_ID=svix_id,
        )

    @patch('svix.Webhook.verify')
    def test_duplicate_delivery_processed_once(self, mock_verify, api_client):
        """Svix retries (same svix-id) must not re-run side effects like credit grants."""
        mock_verify.side_effect = mock_webhook_verify
        payload = {
            'type': 'organization.created',
            'data': {'id': 'org_dedup_1', 'name': 'Dedup Org', 'slug': 'dedup-org'},
        }

        first = self._post(api_client, payload, 'msg_dedup_1')
        second = self._post(api_client, payload, 'msg_dedup_1')

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert second.data.get('duplicate') is True
        org = Organisation.objects.get(clerk_org_id='org_dedup_1')
        # Free signup credits granted exactly once
        grant = org.credittransaction_set.get(transaction_type='grant')
        assert org.credit_balance == grant.amount

    @patch('svix.Webhook.verify')
    def test_failed_handler_rolls_back_dedup_so_retry_reprocesses(self, mock_verify, api_client):
        """A 422 (deferred) delivery must remain retryable — the dedup row rolls back."""
        mock_verify.side_effect = mock_webhook_verify
        # membership for an unknown user → handler raises WebhookProcessingError (422)
        payload = {
            'type': 'organizationMembership.created',
            'data': {
                'public_user_data': {'user_id': 'user_not_synced_yet'},
                'organization': {'id': 'org_dedup_2', 'name': 'Org', 'slug': 'org'},
                'role': 'member',
            },
        }

        first = self._post(api_client, payload, 'msg_dedup_2')
        assert first.status_code == 422

        # User arrives, Svix redelivers the same message id — must be processed
        UserFactory(clerk_id='user_not_synced_yet')
        retry = self._post(api_client, payload, 'msg_dedup_2')

        assert retry.status_code == status.HTTP_200_OK
        assert retry.data.get('duplicate') is None
        assert OrganisationMembership.objects.filter(
            user__clerk_id='user_not_synced_yet',
            organisation__clerk_org_id='org_dedup_2',
        ).exists()


@pytest.mark.django_db
class TestClerkWebhookHandlerRollback:
    """A handler raising mid-processing must leave no dedup marker behind.

    The marker row commits atomically with the handler's side effects (see
    ClerkWebhookView.post): when the handler raises, the whole transaction —
    including the WebhookEvent row — rolls back, so a Svix retry of the same
    svix-id reprocesses rather than being dropped as a duplicate.
    """

    def _post(self, api_client, payload, svix_id):
        return api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_SVIX_ID=svix_id,
        )

    @patch('svix.Webhook.verify')
    def test_handler_raise_returns_422_and_rolls_back_dedup_row(self, mock_verify, api_client):
        """Deferred handler (422) → no WebhookEvent row persists for that svix-id."""
        mock_verify.side_effect = mock_webhook_verify
        # membership before the user exists → _handle_membership_created raises
        # WebhookProcessingError (422) after the dedup row was created.
        payload = {
            'type': 'organizationMembership.created',
            'data': {
                'public_user_data': {'user_id': 'user_rollback'},
                'organization': {'id': 'org_rollback', 'name': 'RB', 'slug': 'rb'},
                'role': 'member',
            },
        }

        response = self._post(api_client, payload, 'msg_rollback_1')

        assert response.status_code == 422
        # The dedup marker rolled back with the failed handler.
        assert not WebhookEvent.objects.filter(
            provider=WebhookEvent.PROVIDER_CLERK, event_id='msg_rollback_1',
        ).exists()
        # No partial side effects either.
        assert not OrganisationMembership.objects.filter(
            organisation__clerk_org_id='org_rollback',
        ).exists()

    @patch('svix.Webhook.verify')
    def test_unexpected_handler_error_rolls_back_dedup_row(self, mock_verify, api_client):
        """A non-deferral handler exception also rolls back the dedup marker.

        Patches the resolved handler to raise a bare RuntimeError mid-processing;
        the transaction must unwind the WebhookEvent row so the event is not
        wrongly marked processed.
        """
        mock_verify.side_effect = mock_webhook_verify
        payload = {
            'type': 'organization.created',
            'data': {'id': 'org_boom', 'name': 'Boom', 'slug': 'boom'},
        }

        boom = patch.dict(
            'app.utils.clerk.WEBHOOK_HANDLERS',
            {'organization.created': Mock(side_effect=RuntimeError('boom'))},
        )
        with boom, pytest.raises(RuntimeError):
            self._post(api_client, payload, 'msg_boom_1')

        # Marker rolled back → a retry (handler now healthy) will reprocess.
        assert not WebhookEvent.objects.filter(
            provider=WebhookEvent.PROVIDER_CLERK, event_id='msg_boom_1',
        ).exists()
        assert not Organisation.objects.filter(clerk_org_id='org_boom').exists()


@pytest.mark.django_db
class TestClerkWebhookIdempotentReapplication:
    """Re-applying the SAME event yields identical final state (sequential).

    organization.created grants free signup credits exactly once: a duplicate
    delivery (same svix-id) is short-circuited by the dedup row, so the balance
    and the grant transaction count never double.
    """

    def _post(self, api_client, payload, svix_id):
        return api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_SVIX_ID=svix_id,
        )

    @patch('svix.Webhook.verify')
    def test_same_event_twice_grants_credits_once(self, mock_verify, api_client):
        mock_verify.side_effect = mock_webhook_verify
        payload = {
            'type': 'organization.created',
            'data': {'id': 'org_reapply', 'name': 'Reapply', 'slug': 'reapply'},
        }

        first = self._post(api_client, payload, 'msg_reapply_1')
        second = self._post(api_client, payload, 'msg_reapply_1')

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert second.data.get('duplicate') is True

        org = Organisation.objects.get(clerk_org_id='org_reapply')
        grants = CreditTransaction.objects.filter(
            organisation=org, transaction_type=CreditTransaction.GRANT,
        )
        # Granted exactly once; balance reflects a single grant.
        assert grants.count() == 1
        assert org.credit_balance == grants.first().amount


@pytest.mark.django_db(transaction=True)
class TestClerkWebhookConcurrentDelivery:
    """Concurrency variant: Svix delivers the same svix-id from several workers
    at once. The unique constraint on (provider, event_id) plus the atomic
    marker means the handler's side effect (free-credit grant) runs exactly once.
    """

    def test_concurrent_same_event_grants_credits_exactly_once(self):
        payload = {
            'type': 'organization.created',
            'data': {'id': 'org_concurrent', 'name': 'Concurrent', 'slug': 'concurrent'},
        }
        body = json.dumps(payload)

        statuses = []
        lock = threading.Lock()

        def deliver():
            client = APIClient()
            try:
                resp = client.post(
                    '/api/webhooks/clerk/',
                    data=body,
                    content_type='application/json',
                    HTTP_SVIX_ID='msg_concurrent',
                )
                with lock:
                    statuses.append(resp.status_code)
            finally:
                connection.close()

        # Patch once around the whole thread lifecycle — all threads share the
        # same verify stub, so the side effect remains active for every request.
        with patch('svix.Webhook.verify', side_effect=mock_webhook_verify):
            threads = [threading.Thread(target=deliver) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Every delivery is acknowledged 200; the side effect runs once.
        assert statuses == [200] * 6
        org = Organisation.objects.get(clerk_org_id='org_concurrent')
        assert CreditTransaction.objects.filter(
            organisation=org, transaction_type=CreditTransaction.GRANT,
        ).count() == 1
        # Exactly one dedup marker exists for the racing deliveries.
        assert WebhookEvent.objects.filter(
            provider=WebhookEvent.PROVIDER_CLERK, event_id='msg_concurrent',
        ).count() == 1


@pytest.mark.django_db
class TestClerkWebhook:
    """Tests for POST /api/webhooks/clerk/ endpoint."""

    @patch('svix.Webhook.verify')
    def test_user_created_event(self, mock_verify, api_client):
        """user.created webhook creates User."""
        mock_verify.side_effect = mock_webhook_verify

        payload = {
            'type': 'user.created',
            'data': {
                'id': 'user_123',
                'first_name': 'John',
                'last_name': 'Doe',
                'email_addresses': [{'email_address': 'john@example.com'}]
            }
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        user = User.objects.get(clerk_id='user_123')
        assert user.first_name == 'John'
        assert user.email == 'john@example.com'

    @patch('svix.Webhook.verify')
    def test_user_updated_event(self, mock_verify, api_client):
        """user.updated webhook updates User."""
        mock_verify.side_effect = mock_webhook_verify

        user = UserFactory(clerk_id='user_123', first_name='Old')

        payload = {
            'type': 'user.updated',
            'data': {
                'id': 'user_123',
                'first_name': 'New',
                'last_name': 'Name',
                'email_addresses': [{'email_address': 'updated@example.com'}]
            }
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        user.refresh_from_db()
        assert user.first_name == 'New'
        assert user.email == 'updated@example.com'

    @patch('svix.Webhook.verify')
    def test_user_deleted_event(self, mock_verify, api_client):
        """user.deleted webhook soft-deletes User."""
        mock_verify.side_effect = mock_webhook_verify

        user = UserFactory(clerk_id='user_123')

        payload = {
            'type': 'user.deleted',
            'data': {'id': 'user_123'}
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        user.refresh_from_db()
        assert user.is_active is False

    @patch('svix.Webhook.verify')
    def test_organization_created_event(self, mock_verify, api_client):
        """organization.created webhook creates Organisation."""
        mock_verify.side_effect = mock_webhook_verify

        payload = {
            'type': 'organization.created',
            'data': {
                'id': 'org_123',
                'name': 'Acme Corp',
                'slug': 'acme-corp'
            }
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        org = Organisation.objects.get(clerk_org_id='org_123')
        assert org.name == 'Acme Corp'
        assert org.slug == 'acme-corp'

    @patch('svix.Webhook.verify')
    def test_organization_updated_event(self, mock_verify, api_client):
        """organization.updated webhook updates Organisation."""
        mock_verify.side_effect = mock_webhook_verify

        org = OrganisationFactory(clerk_org_id='org_123', name='Old')

        payload = {
            'type': 'organization.updated',
            'data': {
                'id': 'org_123',
                'name': 'New Name',
                'slug': 'new-slug'
            }
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        org.refresh_from_db()
        assert org.name == 'New Name'

    @patch('svix.Webhook.verify')
    def test_organization_deleted_event(self, mock_verify, api_client):
        """organization.deleted webhook soft-deletes Organisation."""
        mock_verify.side_effect = mock_webhook_verify

        org = OrganisationFactory(clerk_org_id='org_123')

        payload = {
            'type': 'organization.deleted',
            'data': {'id': 'org_123'}
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        org.refresh_from_db()
        assert org.is_active is False

    @patch('svix.Webhook.verify')
    def test_organization_membership_created_event(self, mock_verify, api_client):
        """organizationMembership.created webhook creates membership."""
        mock_verify.side_effect = mock_webhook_verify

        user = UserFactory(clerk_id='user_123')
        org = OrganisationFactory(clerk_org_id='org_123')

        payload = {
            'type': 'organizationMembership.created',
            'data': {
                'organization': {'id': 'org_123'},
                'public_user_data': {'user_id': 'user_123'},
                'role': 'admin'
            }
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        membership = OrganisationMembership.objects.get(user=user, organisation=org)
        assert membership.role == 'admin'

    @patch('svix.Webhook.verify')
    def test_organization_membership_updated_event(self, mock_verify, api_client):
        """organizationMembership.updated webhook updates membership."""
        mock_verify.side_effect = mock_webhook_verify

        user = UserFactory(clerk_id='user_123')
        org = OrganisationFactory(clerk_org_id='org_123')
        OrganisationMembershipFactory(user=user, organisation=org, role='member')

        payload = {
            'type': 'organizationMembership.updated',
            'data': {
                'organization': {'id': 'org_123'},
                'public_user_data': {'user_id': 'user_123'},
                'role': 'admin'
            }
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        membership = OrganisationMembership.objects.get(user=user, organisation=org)
        assert membership.role == 'admin'

    @patch('svix.Webhook.verify')
    def test_organization_membership_deleted_event(self, mock_verify, api_client):
        """organizationMembership.deleted webhook soft-deletes membership."""
        mock_verify.side_effect = mock_webhook_verify

        user = UserFactory(clerk_id='user_123')
        org = OrganisationFactory(clerk_org_id='org_123')
        membership = OrganisationMembershipFactory(user=user, organisation=org)

        payload = {
            'type': 'organizationMembership.deleted',
            'data': {
                'organization': {'id': 'org_123'},
                'public_user_data': {'user_id': 'user_123'}
            }
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == status.HTTP_200_OK

        membership.refresh_from_db()
        assert membership.is_active is False

    @override_settings(TEST=False)
    def test_webhook_requires_valid_signature(self, api_client):
        """Webhook rejects requests with invalid signature."""
        payload = {
            'type': 'user.created',
            'data': {'id': 'user_123'}
        }

        # Without signature verification mock, should fail
        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        # Should either be 401/403 or 400 depending on implementation
        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN
        ]

    @patch('svix.Webhook.verify')
    def test_webhook_handles_unknown_event_type(self, mock_verify, api_client):
        """Unknown event types handled gracefully."""
        mock_verify.side_effect = mock_webhook_verify

        payload = {
            'type': 'unknown.event',
            'data': {}
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json'
        )

        # Should return 200 (idempotent) or 400
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_400_BAD_REQUEST
        ]

    @patch('svix.Webhook.verify')
    def test_subscription_active_transitions_org_to_subscribed(self, mock_verify, api_client):
        """subscription.active webhook sets org billing_mode to subscribed."""
        mock_verify.side_effect = mock_webhook_verify

        org = OrganisationFactory(clerk_org_id='org_billing_active', billing_mode=Organisation.BILLING_PREPAID)

        payload = {
            'type': 'subscription.active',
            'data': {'payer': {'organization_id': 'org_billing_active'}},
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_SUBSCRIBED

    @patch('svix.Webhook.verify')
    def test_subscription_updated_canceled_reverts_org_to_prepaid(self, mock_verify, api_client):
        """subscription.updated with status=canceled reverts org billing_mode to prepaid."""
        mock_verify.side_effect = mock_webhook_verify

        org = OrganisationFactory(clerk_org_id='org_billing_cancel', billing_mode=Organisation.BILLING_SUBSCRIBED)

        payload = {
            'type': 'subscription.updated',
            'data': {'payer': {'organization_id': 'org_billing_cancel'}, 'status': 'canceled'},
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PREPAID

    @patch('svix.Webhook.verify')
    def test_subscription_updated_ended_reverts_org_to_prepaid(self, mock_verify, api_client):
        """subscription.updated with status=ended reverts org billing_mode to prepaid."""
        mock_verify.side_effect = mock_webhook_verify

        org = OrganisationFactory(clerk_org_id='org_billing_ended', billing_mode=Organisation.BILLING_SUBSCRIBED)

        payload = {
            'type': 'subscription.updated',
            'data': {'payer': {'organization_id': 'org_billing_ended'}, 'status': 'ended'},
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PREPAID

    @patch('svix.Webhook.verify')
    def test_subscription_past_due_sets_past_due_billing_mode(self, mock_verify, api_client):
        """subscription.pastDue webhook sets billing_mode to past_due and blocks sends."""
        mock_verify.side_effect = mock_webhook_verify

        org = OrganisationFactory(clerk_org_id='org_billing_pastdue', billing_mode=Organisation.BILLING_SUBSCRIBED)

        payload = {
            'type': 'subscription.pastDue',
            'data': {'id': 'sub_123', 'payer': {'organization_id': 'org_billing_pastdue'}},
        }

        with patch('app.utils.clerk.Clerk'):
            response = api_client.post(
                '/api/webhooks/clerk/',
                data=json.dumps(payload),
                content_type='application/json',
            )

        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE


@pytest.mark.django_db
class TestClerkWebhookRealSignature:
    """Real Svix signature verification under TEST=False.

    The previous signature tests mock ``svix.Webhook.verify``; these exercise the
    genuine HMAC path. A payload signed with the configured secret + a current
    timestamp must be ACCEPTED and processed, while a tampered body, wrong
    secret, or missing header is rejected (400) with zero side effects.
    """

    _payload = {
        'type': 'organization.created',
        'data': {'id': 'org_signed', 'name': 'Signed Org', 'slug': 'signed-org'},
    }

    @override_settings(TEST=False, CLERK_WEBHOOK_SIGNING_SECRET=_VALID_SIGNING_SECRET)
    def test_valid_signature_is_accepted_and_processed(self, api_client):
        body, headers = _sign_payload(self._payload, svix_id='msg_real_ok')

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=body,
            content_type='application/json',
            **headers,
        )

        assert response.status_code == status.HTTP_200_OK
        org = Organisation.objects.get(clerk_org_id='org_signed')
        assert org.name == 'Signed Org'
        # The signed delivery's svix-id is recorded for dedup.
        assert WebhookEvent.objects.filter(
            provider=WebhookEvent.PROVIDER_CLERK, event_id='msg_real_ok',
        ).exists()

    @override_settings(TEST=False, CLERK_WEBHOOK_SIGNING_SECRET=_VALID_SIGNING_SECRET)
    def test_tampered_body_rejected_with_no_side_effects(self, api_client):
        """A body that differs from the signed bytes fails the HMAC check."""
        body, headers = _sign_payload(self._payload, svix_id='msg_tampered')
        # Mutate the body after signing — the signature no longer matches.
        tampered = body.replace('Signed Org', 'Tampered Org')
        assert tampered != body

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=tampered,
            content_type='application/json',
            **headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Organisation.objects.filter(clerk_org_id='org_signed').exists()
        assert not WebhookEvent.objects.filter(event_id='msg_tampered').exists()

    @override_settings(TEST=False, CLERK_WEBHOOK_SIGNING_SECRET=_VALID_SIGNING_SECRET)
    def test_wrong_secret_signature_rejected_with_no_side_effects(self, api_client):
        """A correctly-formed signature made with a different secret is rejected."""
        body, headers = _sign_payload(
            self._payload, secret='whsec_b3RoZXI=', svix_id='msg_wrong_secret',
        )

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=body,
            content_type='application/json',
            **headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Organisation.objects.filter(clerk_org_id='org_signed').exists()
        assert not WebhookEvent.objects.filter(event_id='msg_wrong_secret').exists()

    @override_settings(TEST=False, CLERK_WEBHOOK_SIGNING_SECRET=_VALID_SIGNING_SECRET)
    def test_missing_signature_header_rejected_with_no_side_effects(self, api_client):
        """Omitting the svix-signature header fails verification (missing headers)."""
        body, headers = _sign_payload(self._payload, svix_id='msg_no_sig')
        headers.pop('HTTP_SVIX_SIGNATURE')

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=body,
            content_type='application/json',
            **headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Organisation.objects.filter(clerk_org_id='org_signed').exists()
        assert not WebhookEvent.objects.filter(event_id='msg_no_sig').exists()


@pytest.mark.django_db
class TestClerkWebhookDeferralAndReplay:
    """Out-of-order delivery: membership before user is deferred (422) and the
    dedup row rolls back so a Svix replay reprocesses successfully."""

    _payload = {
        'type': 'organizationMembership.created',
        'data': {
            'public_user_data': {'user_id': 'user_late'},
            'organization': {'id': 'org_replay', 'name': 'Replay Org', 'slug': 'replay-org'},
            'role': 'admin',
        },
    }

    def _post(self, api_client, svix_id):
        return api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(self._payload),
            content_type='application/json',
            HTTP_SVIX_ID=svix_id,
        )

    @patch('svix.Webhook.verify')
    def test_membership_before_user_defers_then_replay_succeeds(self, mock_verify, api_client):
        mock_verify.side_effect = mock_webhook_verify

        # First delivery: the user has not synced yet → deferred (422).
        first = self._post(api_client, 'msg_replay_1')
        assert first.status_code == 422
        assert not OrganisationMembership.objects.filter(
            organisation__clerk_org_id='org_replay',
        ).exists()
        # The dedup marker must have rolled back with the failed handler so the
        # redelivery is not silently skipped as a duplicate.
        assert not WebhookEvent.objects.filter(event_id='msg_replay_1').exists()

        # The user.created webhook lands, then Svix replays the same message id.
        UserFactory(clerk_id='user_late')
        retry = self._post(api_client, 'msg_replay_1')

        assert retry.status_code == status.HTTP_200_OK
        assert retry.data.get('duplicate') is None
        membership = OrganisationMembership.objects.get(
            user__clerk_id='user_late', organisation__clerk_org_id='org_replay',
        )
        assert membership.role == 'admin'
        # Now the marker is committed alongside the successful side effects.
        assert WebhookEvent.objects.filter(event_id='msg_replay_1').exists()


@pytest.mark.django_db
class TestClerkWebhookBillingTransitionsViaEndpoint:
    """Billing transitions through the endpoint with the live Clerk SDK and the
    metered-billing provider fully MOCKED — assert the SDK is called with the
    right args and no live call is attempted."""

    @patch('app.utils.clerk.link_billing_customer')
    @patch('app.utils.clerk.get_billing_provider')
    @patch('app.utils.clerk.Clerk')
    def test_active_transitions_to_subscribed_and_clears_suspension(
        self, MockClerk, mock_get_provider, mock_link, api_client,
    ):
        mock_get_provider.return_value.find_customer_by_org.return_value.success = False
        org = OrganisationFactory(
            clerk_org_id='org_ep_active', billing_mode=Organisation.BILLING_PREPAID,
        )

        payload = {
            'type': 'subscription.active',
            'data': {'payer': {'organization_id': 'org_ep_active'}},
        }

        with patch('svix.Webhook.verify', side_effect=mock_webhook_verify):
            response = api_client.post(
                '/api/webhooks/clerk/',
                data=json.dumps(payload),
                content_type='application/json',
            )

        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_SUBSCRIBED
        # The Clerk SDK was called to clear the suspension flag (no live call).
        MockClerk.return_value.organizations.update.assert_called_once_with(
            organization_id='org_ep_active',
            private_metadata={'billing_suspended': False},
        )

    @patch('app.utils.clerk.Clerk')
    def test_canceled_reverts_to_prepaid(self, MockClerk, api_client):
        org = OrganisationFactory(
            clerk_org_id='org_ep_cancel', billing_mode=Organisation.BILLING_SUBSCRIBED,
        )

        payload = {
            'type': 'subscription.updated',
            'data': {'payer': {'organization_id': 'org_ep_cancel'}, 'status': 'canceled'},
        }

        with patch('svix.Webhook.verify', side_effect=mock_webhook_verify):
            response = api_client.post(
                '/api/webhooks/clerk/',
                data=json.dumps(payload),
                content_type='application/json',
            )

        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PREPAID
        # Cancellation does not touch the Clerk SDK.
        MockClerk.return_value.organizations.update.assert_not_called()

    @patch('app.utils.clerk.Clerk')
    def test_past_due_sets_past_due_and_suspends(self, MockClerk, api_client):
        org = OrganisationFactory(
            clerk_org_id='org_ep_pastdue', billing_mode=Organisation.BILLING_SUBSCRIBED,
        )

        payload = {
            'type': 'subscription.pastDue',
            'data': {'id': 'sub_ep', 'payer': {'organization_id': 'org_ep_pastdue'}},
        }

        with patch('svix.Webhook.verify', side_effect=mock_webhook_verify):
            response = api_client.post(
                '/api/webhooks/clerk/',
                data=json.dumps(payload),
                content_type='application/json',
            )

        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_CLERK
        MockClerk.return_value.organizations.update.assert_called_once_with(
            organization_id='org_ep_pastdue',
            private_metadata={'billing_suspended': True},
        )


@pytest.mark.django_db
class TestClerkWebhookMembershipUpdatedIdempotency:
    """organizationMembership.updated re-applies cleanly (update_or_create)."""

    @patch('svix.Webhook.verify')
    def test_repeated_membership_updated_is_idempotent(self, mock_verify, api_client):
        mock_verify.side_effect = mock_webhook_verify

        user = UserFactory(clerk_id='user_idem')
        org = OrganisationFactory(clerk_org_id='org_idem')
        OrganisationMembershipFactory(user=user, organisation=org, role='member')

        payload = {
            'type': 'organizationMembership.updated',
            'data': {
                'organization': {'id': 'org_idem'},
                'public_user_data': {'user_id': 'user_idem'},
                'role': 'admin',
            },
        }

        def _post(svix_id):
            return api_client.post(
                '/api/webhooks/clerk/',
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_SVIX_ID=svix_id,
            )

        # Two distinct deliveries (different svix-id) must converge on one row.
        first = _post('msg_idem_1')
        second = _post('msg_idem_2')

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        memberships = OrganisationMembership.objects.filter(user=user, organisation=org)
        assert memberships.count() == 1
        assert memberships.first().role == 'admin'


@pytest.mark.django_db
class TestClerkWebhookOrganizationDeletedCascade:
    """organization.deleted soft-deletes the org and cascades to memberships.
    Other tenant rows (e.g. Config) have no is_active column and must be left
    intact (not orphaned/crashed)."""

    @patch('svix.Webhook.verify')
    def test_deleted_event_cascades_soft_delete(self, mock_verify, api_client):
        mock_verify.side_effect = mock_webhook_verify

        user = UserFactory(clerk_id='user_cascade')
        org = OrganisationFactory(clerk_org_id='org_cascade')
        membership = OrganisationMembershipFactory(user=user, organisation=org)
        config = ConfigFactory(organisation=org)

        payload = {
            'type': 'organization.deleted',
            'data': {'id': 'org_cascade'},
        }

        response = api_client.post(
            '/api/webhooks/clerk/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        assert response.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        membership.refresh_from_db()

        assert org.is_active is False
        assert membership.is_active is False
        # Config has no is_active — the cascade must not have deleted it.
        assert Config.objects.filter(pk=config.pk).exists()
