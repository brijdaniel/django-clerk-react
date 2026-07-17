"""Tests for the Stripe webhook endpoint (StripeWebhookView)."""

import json
import threading
import time
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch, Mock

import pytest
import stripe
from django.db import connection
from rest_framework.test import APIClient

from app.models import CreditPurchase, CreditTransaction, Invoice, Organisation, WebhookEvent
from app.utils.metered_billing import _BillingProviderCache
from app.utils.stripe import StripeMeteredBillingProvider
from tests.utils.stripe_signing import event_dict, signed_event


@pytest.fixture
def webhook_client():
    """Unauthenticated client (Stripe webhooks have no auth — signature verified)."""
    return APIClient()


@pytest.fixture
def org_with_invoice(db):
    org = Organisation.objects.create(
        clerk_org_id='org_wh_test',
        name='Webhook Test Org',
        billing_mode=Organisation.BILLING_SUBSCRIBED,
        billing_customer_id='cus_wh_test',
    )
    invoice = Invoice.objects.create(
        organisation=org,
        provider_invoice_id='inv_test_123',
        status=Invoice.STATUS_OPEN,
        amount=Decimal('5.00'),
        period_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    return org, invoice


@pytest.mark.django_db
class TestStripeWebhookView:
    @patch('app.utils.stripe.get_billing_provider')
    def test_invalid_signature_rejected_with_no_side_effects(self, mock_get_provider, webhook_client, org_with_invoice):
        """A signature verification failure returns 400 and processes nothing."""
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.side_effect = stripe.SignatureVerificationError(
            'bad signature', 'sig_forged',
        )
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{"type": "invoice.paid", "data": {"object": {"id": "inv_test_123"}}}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_forged',
        )

        assert response.status_code == 400
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_OPEN  # untouched

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_paid_updates_status(self, mock_get_provider, webhook_client, org_with_invoice):
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.paid',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_PAID

    @patch('app.utils.stripe.get_billing_provider')
    def test_duplicate_event_id_processed_once(self, mock_get_provider, webhook_client, org_with_invoice):
        """Stripe retries (same event.id) must not re-run handlers."""
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'id': 'evt_dedup_1',
            'type': 'invoice.paid',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        first = webhook_client.post(
            '/api/webhooks/stripe/', data=b'{}',
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig_test',
        )
        # Flip the invoice back to OPEN to detect any re-processing
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.STATUS_OPEN)
        second = webhook_client.post(
            '/api/webhooks/stripe/', data=b'{}',
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.data.get('duplicate') is True
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_OPEN  # duplicate did not re-run

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_paid_restores_subscribed_from_past_due(self, mock_get_provider, webhook_client, org_with_invoice):
        org, invoice = org_with_invoice
        # Set org to past_due
        Organisation.objects.filter(pk=org.pk).update(billing_mode=Organisation.BILLING_PAST_DUE)

        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.paid',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_SUBSCRIBED

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_paid_does_not_clear_clerk_set_past_due(self, mock_get_provider, webhook_client, org_with_invoice):
        """A paid metered invoice must not un-block past_due set by Clerk.

        Regression test: the restore logic only checked our Invoice table, so an
        org blocked for an unpaid Clerk subscription fee was wrongly restored
        when any unrelated metered invoice was paid.
        """
        org, invoice = org_with_invoice
        Organisation.objects.filter(pk=org.pk).update(
            billing_mode=Organisation.BILLING_PAST_DUE,
            past_due_source=Organisation.PAST_DUE_SOURCE_CLERK,
        )

        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.paid',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_PAID  # invoice itself is settled
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE  # still blocked
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_CLERK

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_payment_failed_records_stripe_source(self, mock_get_provider, webhook_client, org_with_invoice):
        """invoice.payment_failed marks past_due as Stripe-sourced so only invoice.paid clears it."""
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.payment_failed',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_paid_clears_stripe_set_past_due_and_source(self, mock_get_provider, webhook_client, org_with_invoice):
        """invoice.paid restores Stripe-sourced past_due and resets the source."""
        org, invoice = org_with_invoice
        Organisation.objects.filter(pk=org.pk).update(
            billing_mode=Organisation.BILLING_PAST_DUE,
            past_due_source=Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE,
        )

        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.paid',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_SUBSCRIBED
        assert org.past_due_source is None

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_paid_keeps_past_due_when_other_invoices_unpaid(self, mock_get_provider, webhook_client, org_with_invoice):
        org, invoice = org_with_invoice
        Organisation.objects.filter(pk=org.pk).update(billing_mode=Organisation.BILLING_PAST_DUE)

        # Create another uncollectable invoice for the same org
        Invoice.objects.create(
            organisation=org,
            provider_invoice_id='inv_other_unpaid',
            status=Invoice.STATUS_UNCOLLECTABLE,
            amount=Decimal('10.00'),
            period_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )

        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.paid',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_PAID
        # Should stay past_due because the other invoice is still uncollectable
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_payment_failed_sets_past_due(self, mock_get_provider, webhook_client, org_with_invoice):
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.payment_failed',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_UNCOLLECTABLE
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_overdue_sets_past_due(self, mock_get_provider, webhook_client, org_with_invoice):
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.overdue',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_UNCOLLECTABLE
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_voided_updates_status(self, mock_get_provider, webhook_client, org_with_invoice):
        _, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.voided',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_VOID

    @patch('app.utils.stripe.get_billing_provider')
    def test_invalid_signature_returns_400(self, mock_get_provider, webhook_client):
        mock_provider = Mock()
        mock_provider.parse_webhook.side_effect = stripe.SignatureVerificationError('bad', 'sig')
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='bad_sig',
        )

        assert response.status_code == 400

    @patch('app.utils.stripe.get_billing_provider')
    def test_unknown_event_returns_200(self, mock_get_provider, webhook_client):
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'customer.created',
            'data': {'id': 'cus_123'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200

    @patch('app.utils.stripe.get_billing_provider')
    def test_invoice_paid_unknown_invoice_logs_warning(self, mock_get_provider, webhook_client, db):
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'type': 'invoice.paid',
            'data': {'id': 'inv_nonexistent'},
        }
        mock_get_provider.return_value = mock_provider

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        # Should still return 200 (don't retry unknown invoices)
        assert response.status_code == 200

    @patch('app.utils.stripe.stripe.Webhook.construct_event')
    def test_webhook_handles_stripe_object_data(self, mock_construct, webhook_client, org_with_invoice):
        """Regression: parse_webhook converts StripeObject to plain dict."""
        org, invoice = org_with_invoice
        mock_event = Mock()
        mock_event.id = 'evt_stripe_obj_1'
        mock_event.type = 'invoice.paid'
        mock_event.data.object = stripe.StripeObject.construct_from(
            {'id': 'inv_test_123'}, key=None,
        )
        mock_construct.return_value = mock_event

        response = webhook_client.post(
            '/api/webhooks/stripe/',
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_PAID


@pytest.mark.django_db
class TestStripeWebhookHandlerRollback:
    """A handler raising mid-processing must leave no dedup marker behind.

    Mirrors StripeWebhookView.post: the WebhookEvent marker commits atomically
    with the handler, so when a handler raises the marker rolls back and a
    Stripe retry of the same event id reprocesses instead of being dropped.
    """

    @patch('app.utils.stripe.StripeWebhookView._handle_invoice_paid', side_effect=RuntimeError('boom'))
    @patch('app.utils.stripe.get_billing_provider')
    def test_handler_raise_rolls_back_dedup_row(
        self, mock_get_provider, mock_handler, webhook_client, org_with_invoice,
    ):
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'id': 'evt_rollback_1',
            'type': 'invoice.paid',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        # A bare exception is not a DRF APIException → 500, re-raised by the
        # test client. The atomic marker insert must roll back with it.
        with pytest.raises(RuntimeError):
            webhook_client.post(
                '/api/webhooks/stripe/', data=b'{}',
                content_type='application/json', HTTP_STRIPE_SIGNATURE='sig_test',
            )

        assert not WebhookEvent.objects.filter(
            provider=WebhookEvent.PROVIDER_STRIPE, event_id='evt_rollback_1',
        ).exists()
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_OPEN  # side effect rolled back

    @patch('app.utils.stripe.get_billing_provider')
    def test_retry_after_rolled_back_marker_reprocesses(
        self, mock_get_provider, webhook_client, org_with_invoice,
    ):
        """After a failed delivery rolls back the marker, a healthy retry of the
        same event id is NOT skipped as a duplicate — it processes for real."""
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'id': 'evt_retry_1',
            'type': 'invoice.paid',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        with patch(
            'app.utils.stripe.StripeWebhookView._handle_invoice_paid',
            side_effect=RuntimeError('boom'),
        ), pytest.raises(RuntimeError):
            webhook_client.post(
                '/api/webhooks/stripe/', data=b'{}',
                content_type='application/json', HTTP_STRIPE_SIGNATURE='sig_test',
            )

        # Retry: handler healthy now, same event id — must reprocess.
        retry = webhook_client.post(
            '/api/webhooks/stripe/', data=b'{}',
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert retry.status_code == 200
        assert retry.data.get('duplicate') is None
        invoice.refresh_from_db()
        assert invoice.status == Invoice.STATUS_PAID
        assert WebhookEvent.objects.filter(
            provider=WebhookEvent.PROVIDER_STRIPE, event_id='evt_retry_1',
        ).count() == 1


@pytest.mark.django_db
class TestStripeWebhookIdempotentReapplication:
    """Re-applying the SAME event leaves identical final state (sequential)."""

    @patch('app.utils.stripe.get_billing_provider')
    def test_same_payment_failed_event_sets_past_due_once(
        self, mock_get_provider, webhook_client, org_with_invoice,
    ):
        """invoice.payment_failed redelivered (same event id) → past_due set once,
        and past_due_source is not relabelled on the second (skipped) delivery."""
        org, invoice = org_with_invoice
        mock_provider = Mock()
        mock_provider.parse_webhook.return_value = {
            'id': 'evt_pastdue_idem',
            'type': 'invoice.payment_failed',
            'data': {'id': 'inv_test_123'},
        }
        mock_get_provider.return_value = mock_provider

        first = webhook_client.post(
            '/api/webhooks/stripe/', data=b'{}',
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig_test',
        )
        second = webhook_client.post(
            '/api/webhooks/stripe/', data=b'{}',
            content_type='application/json', HTTP_STRIPE_SIGNATURE='sig_test',
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.data.get('duplicate') is True
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE
        # Only one dedup marker exists for the duplicated deliveries.
        assert WebhookEvent.objects.filter(
            provider=WebhookEvent.PROVIDER_STRIPE, event_id='evt_pastdue_idem',
        ).count() == 1


@pytest.mark.django_db(transaction=True)
class TestStripeWebhookConcurrentDelivery:
    """Concurrency variant: Stripe delivers the same event id from several
    workers at once. The unique (provider, event_id) constraint + atomic marker
    means the grant runs exactly once across racing deliveries."""

    def test_concurrent_checkout_completed_grants_exactly_once(self):
        org = Organisation.objects.create(
            clerk_org_id='org_stripe_concurrent',
            name='Stripe Concurrent',
            billing_mode=Organisation.BILLING_PREPAID,
            credit_balance=Decimal('0.00'),
        )
        CreditPurchase.objects.create(
            organisation=org, stripe_checkout_session_id='cs_concurrent', amount=Decimal('25'),
        )
        parsed_event = {
            'id': 'evt_stripe_concurrent',
            'type': 'checkout.session.completed',
            'data': {
                'id': 'cs_concurrent', 'object': 'checkout.session',
                'payment_status': 'paid', 'amount_total': 2500, 'customer': 'cus_concurrent',
                'metadata': {'purchase_type': 'credit_purchase', 'org_id': org.clerk_org_id},
            },
        }

        provider = Mock()
        provider.parse_webhook.return_value = parsed_event

        statuses = []
        lock = threading.Lock()

        def deliver():
            client = APIClient()
            try:
                resp = client.post(
                    '/api/webhooks/stripe/', data=b'{}',
                    content_type='application/json', HTTP_STRIPE_SIGNATURE='sig_test',
                )
                with lock:
                    statuses.append(resp.status_code)
            finally:
                connection.close()

        # Patch once around the whole thread lifecycle — every request resolves
        # the same provider stub (parse_webhook returns the identical event).
        with patch('app.utils.stripe.get_billing_provider', return_value=provider):
            threads = [threading.Thread(target=deliver) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert statuses == [200] * 6
        org.refresh_from_db()
        assert org.credit_balance == Decimal('25.00')  # granted exactly once
        assert CreditTransaction.objects.filter(
            organisation=org, transaction_type=CreditTransaction.GRANT,
        ).count() == 1
        assert WebhookEvent.objects.filter(
            provider=WebhookEvent.PROVIDER_STRIPE, event_id='evt_stripe_concurrent',
        ).count() == 1


# ---------------------------------------------------------------------------
# Real-signature boundary tests — exercise stripe.Webhook.construct_event for
# real (no parse_webhook / construct_event mocking) by injecting a real
# StripeMeteredBillingProvider, so the signature branch AND the grant/invoice
# handlers it gates are genuinely verified. This is the gap the prior tests left:
# they all mocked the verifier, so a real signature-handling or grant regression
# (e.g. money taken, credits never granted) would ship undetected.
# ---------------------------------------------------------------------------

WHSEC = 'whsec_test_realsig_abc123'


@pytest.fixture
def real_stripe_provider():
    """Inject a real provider so the view's get_billing_provider().parse_webhook
    runs construct_event for real. Restored in teardown so the singleton doesn't
    leak the real provider into tests that expect the Mock."""
    prev = _BillingProviderCache.instance
    _BillingProviderCache.instance = StripeMeteredBillingProvider('sk_test_dummy', WHSEC)
    yield
    _BillingProviderCache.instance = prev


@pytest.mark.django_db
class TestStripeWebhookRealSignatureBoundary:
    def setup_method(self):
        self.client = APIClient()

    def _post(self, event, secret=WHSEC, timestamp=None, sig=None, body=None):
        signed_body, signed_sig = signed_event(event, secret, timestamp)
        kwargs = {'data': body if body is not None else signed_body,
                  'content_type': 'application/json'}
        header = signed_sig if sig is None else sig
        if header is not False:  # False => omit the header entirely
            kwargs['HTTP_STRIPE_SIGNATURE'] = header
        return self.client.post('/api/webhooks/stripe/', **kwargs)

    def _org(self, **kw):
        defaults = dict(clerk_org_id='org_rs', name='RS',
                        billing_mode=Organisation.BILLING_PREPAID, credit_balance=Decimal('0'))
        defaults.update(kw)
        return Organisation.objects.create(**defaults)

    def _completed_event(self, org, session_id='cs_rs', amount_total=2500,
                         event_id='evt_rs_grant', customer='cus_rs'):
        return event_dict(event_id, 'checkout.session.completed', {
            'id': session_id, 'object': 'checkout.session',
            'payment_status': 'paid', 'amount_total': amount_total, 'customer': customer,
            'metadata': {'purchase_type': 'credit_purchase', 'org_id': org.clerk_org_id},
        })

    def test_checkout_completed_grants_credits_end_to_end(self, real_stripe_provider):
        org = self._org()
        purchase = CreditPurchase.objects.create(
            organisation=org, stripe_checkout_session_id='cs_rs', amount=Decimal('25'))
        resp = self._post(self._completed_event(org))
        assert resp.status_code == 200
        org.refresh_from_db(); purchase.refresh_from_db()
        assert org.credit_balance == Decimal('25.00')
        assert org.billing_customer_id == 'cus_rs'
        assert purchase.status == CreditPurchase.STATUS_COMPLETED
        assert purchase.credit_transaction is not None
        assert CreditTransaction.objects.filter(
            organisation=org, transaction_type=CreditTransaction.GRANT).count() == 1

    def test_valid_signature_accepted(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_valid')
        CreditPurchase.objects.create(organisation=org, stripe_checkout_session_id='cs_v', amount=Decimal('10'))
        evt = self._completed_event(org, session_id='cs_v', amount_total=1000, event_id='evt_v')
        assert self._post(evt).status_code == 200

    def test_tampered_body_rejected_no_side_effects(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_tamper')
        CreditPurchase.objects.create(organisation=org, stripe_checkout_session_id='cs_t', amount=Decimal('25'))
        evt = self._completed_event(org, session_id='cs_t', event_id='evt_t')
        body, sig = signed_event(evt, WHSEC)
        tampered = body.replace(b'2500', b'9900')  # mutate amount_total AFTER signing
        resp = self.client.post('/api/webhooks/stripe/', data=tampered,
                                content_type='application/json', HTTP_STRIPE_SIGNATURE=sig)
        assert resp.status_code == 400
        org.refresh_from_db()
        assert org.credit_balance == Decimal('0')
        assert not CreditTransaction.objects.filter(organisation=org).exists()

    def test_wrong_secret_rejected_no_side_effects(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_wrong')
        CreditPurchase.objects.create(organisation=org, stripe_checkout_session_id='cs_w', amount=Decimal('25'))
        evt = self._completed_event(org, session_id='cs_w', event_id='evt_w')
        resp = self._post(evt, secret='whsec_a_different_secret')
        assert resp.status_code == 400
        org.refresh_from_db()
        assert org.credit_balance == Decimal('0')

    def test_replayed_signature_outside_tolerance_rejected(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_replay')
        CreditPurchase.objects.create(organisation=org, stripe_checkout_session_id='cs_r', amount=Decimal('25'))
        evt = self._completed_event(org, session_id='cs_r', event_id='evt_r')
        resp = self._post(evt, timestamp=int(time.time()) - 3600)  # 1h old > 5m tolerance
        assert resp.status_code == 400
        org.refresh_from_db()
        assert org.credit_balance == Decimal('0')

    def test_missing_signature_header_rejected(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_nosig')
        resp = self._post(self._completed_event(org, event_id='evt_n'), sig=False)
        assert resp.status_code == 400

    def test_amount_total_mismatch_does_not_grant(self, real_stripe_provider):
        """Defense-in-depth: a signed event whose amount_total != purchase amount grants nothing."""
        org = self._org(clerk_org_id='org_rs_mismatch')
        CreditPurchase.objects.create(organisation=org, stripe_checkout_session_id='cs_m', amount=Decimal('25'))
        evt = self._completed_event(org, session_id='cs_m', amount_total=9900, event_id='evt_m')  # $99 != $25
        resp = self._post(evt)
        assert resp.status_code == 200  # processed, but the guard skips the grant
        org.refresh_from_db()
        assert org.credit_balance == Decimal('0')

    def test_checkout_expired_marks_purchase_expired(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_exp')
        purchase = CreditPurchase.objects.create(
            organisation=org, stripe_checkout_session_id='cs_e', amount=Decimal('25'))
        evt = event_dict('evt_e', 'checkout.session.expired', {
            'id': 'cs_e', 'object': 'checkout.session',
            'metadata': {'purchase_type': 'credit_purchase', 'org_id': org.clerk_org_id},
        })
        assert self._post(evt).status_code == 200
        purchase.refresh_from_db()
        assert purchase.status == CreditPurchase.STATUS_EXPIRED

    def test_dedup_grants_exactly_once(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_dedup')
        CreditPurchase.objects.create(organisation=org, stripe_checkout_session_id='cs_d', amount=Decimal('25'))
        evt = self._completed_event(org, session_id='cs_d', event_id='evt_dedup_same')
        r1 = self._post(evt)
        r2 = self._post(evt)  # Stripe at-least-once retry: same event id
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.data.get('duplicate') is True
        org.refresh_from_db()
        assert org.credit_balance == Decimal('25.00')
        assert CreditTransaction.objects.filter(
            organisation=org, transaction_type=CreditTransaction.GRANT).count() == 1

    def test_invoice_payment_failed_sets_past_due(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_inv_fail',
                        billing_mode=Organisation.BILLING_SUBSCRIBED, billing_customer_id='cus_if')
        Invoice.objects.create(
            organisation=org, provider_invoice_id='in_fail', status=Invoice.STATUS_OPEN, amount=Decimal('5'),
            period_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 4, 1, tzinfo=timezone.utc))
        evt = event_dict('evt_if', 'invoice.payment_failed', {'id': 'in_fail', 'object': 'invoice'})
        assert self._post(evt).status_code == 200
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_PAST_DUE

    def test_invoice_paid_clears_stripe_set_past_due(self, real_stripe_provider):
        org = self._org(clerk_org_id='org_rs_inv_paid',
                        billing_mode=Organisation.BILLING_PAST_DUE, billing_customer_id='cus_ip',
                        past_due_source=Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE)
        Invoice.objects.create(
            organisation=org, provider_invoice_id='in_paid', status=Invoice.STATUS_UNCOLLECTABLE,
            amount=Decimal('5'), period_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 4, 1, tzinfo=timezone.utc))
        evt = event_dict('evt_ip', 'invoice.paid', {'id': 'in_paid', 'object': 'invoice'})
        assert self._post(evt).status_code == 200
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_SUBSCRIBED
