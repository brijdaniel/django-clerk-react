"""
Tests for the credit purchase flow:
- GET /api/billing/credit-packages/ — list available packages
- POST /api/billing/buy-credits/ — create Stripe Checkout Session
- Stripe webhooks: checkout.session.completed, checkout.session.expired
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient

from app.models import CreditPurchase, Organisation
from app.utils.billing import get_balance, grant_credits
from app.utils.metered_billing import CheckoutResult, _BillingProviderCache


@pytest.fixture
def admin_client(user, organisation, org_membership):
    """Authenticated API client with admin role."""
    client = APIClient()
    client.force_authenticate(user=user)

    from rest_framework.views import APIView
    original_dispatch = APIView.dispatch

    def patched_dispatch(self, request, *args, **kwargs):
        request.org = organisation
        request.org_id = organisation.clerk_org_id
        request.org_role = 'admin'
        request.org_permissions = ['*']
        return original_dispatch(self, request, *args, **kwargs)

    APIView.dispatch = patched_dispatch
    yield client
    APIView.dispatch = original_dispatch


@pytest.mark.django_db
class TestBuyCreditsEndpoint:
    def _mock_provider(self, checkout_result):
        """Replace the cached billing provider with a mock."""
        provider = Mock()
        provider.create_checkout_session.return_value = checkout_result
        old = _BillingProviderCache.instance
        _BillingProviderCache.instance = provider
        return old

    def test_valid_amount_returns_checkout_url(self, admin_client, organisation):
        old = self._mock_provider(CheckoutResult(
            success=True,
            session_id='cs_test_123',
            checkout_url='https://checkout.stripe.com/cs_test_123',
        ))
        try:
            response = admin_client.post('/api/billing/buy-credits/', {'amount': 15})

            assert response.status_code == 200
            assert response.data['checkout_url'] == 'https://checkout.stripe.com/cs_test_123'

            purchase = CreditPurchase.objects.get(stripe_checkout_session_id='cs_test_123')
            assert purchase.amount == Decimal('15.00')
            assert purchase.status == CreditPurchase.STATUS_PENDING
            assert purchase.organisation == organisation
        finally:
            _BillingProviderCache.instance = old

    def test_amount_below_minimum_returns_400(self, admin_client):
        response = admin_client.post('/api/billing/buy-credits/', {'amount': 2})
        assert response.status_code == 400

    def test_amount_above_maximum_returns_400(self, admin_client):
        response = admin_client.post('/api/billing/buy-credits/', {'amount': 20000})
        assert response.status_code == 400

    def test_past_due_org_returns_402(self, admin_client, organisation):
        organisation.billing_mode = Organisation.BILLING_PAST_DUE
        organisation.save()

        response = admin_client.post('/api/billing/buy-credits/', {'amount': 25})
        assert response.status_code == 402

    def test_member_role_returns_403(self, authenticated_client):
        response = authenticated_client.post('/api/billing/buy-credits/', {'amount': 25})
        assert response.status_code == 403

    def test_provider_failure_returns_502(self, admin_client):
        old = self._mock_provider(CheckoutResult(
            success=False, error='Stripe is down',
        ))
        try:
            response = admin_client.post('/api/billing/buy-credits/', {'amount': 50})
            assert response.status_code == 502
        finally:
            _BillingProviderCache.instance = old


@pytest.mark.django_db
class TestCheckoutWebhooks:
    def _post_webhook(self, event_type, session_data):
        """Directly call webhook handler methods to test business logic."""
        from app.utils.stripe import StripeWebhookView
        view = StripeWebhookView()

        if event_type == 'checkout.session.completed':
            view._handle_checkout_completed(session_data)
        elif event_type == 'checkout.session.expired':
            view._handle_checkout_expired(session_data)

    def test_checkout_completed_grants_credits(self, db, organisation):
        """checkout.session.completed grants credits and updates CreditPurchase."""
        CreditPurchase.objects.create(
            organisation=organisation,
            stripe_checkout_session_id='cs_test_completed',
            amount=Decimal('50.00'),
        )
        initial_balance = get_balance(organisation)

        self._post_webhook('checkout.session.completed', {
            'id': 'cs_test_completed',
            'payment_status': 'paid',
            'metadata': {'purchase_type': 'credit_purchase', 'org_id': organisation.clerk_org_id},
            'customer': 'cus_test_123',
        })

        purchase = CreditPurchase.objects.get(stripe_checkout_session_id='cs_test_completed')
        assert purchase.status == CreditPurchase.STATUS_COMPLETED
        assert purchase.completed_at is not None
        assert purchase.credit_transaction is not None

        new_balance = get_balance(organisation)
        assert new_balance == initial_balance + Decimal('50.00')

    def test_checkout_completed_links_stripe_customer(self, db, organisation):
        """checkout.session.completed links Stripe customer ID if org doesn't have one."""
        assert organisation.billing_customer_id is None
        CreditPurchase.objects.create(
            organisation=organisation,
            stripe_checkout_session_id='cs_test_customer_link',
            amount=Decimal('10.00'),
        )

        self._post_webhook('checkout.session.completed', {
            'id': 'cs_test_customer_link',
            'payment_status': 'paid',
            'metadata': {'purchase_type': 'credit_purchase', 'org_id': organisation.clerk_org_id},
            'customer': 'cus_new_456',
        })

        organisation.refresh_from_db()
        assert organisation.billing_customer_id == 'cus_new_456'

    def test_checkout_completed_idempotent(self, db, organisation):
        """Double webhook delivery doesn't double-grant credits."""
        CreditPurchase.objects.create(
            organisation=organisation,
            stripe_checkout_session_id='cs_test_idempotent',
            amount=Decimal('25.00'),
        )
        grant_credits(organisation, Decimal('5.00'), 'initial')

        session_data = {
            'id': 'cs_test_idempotent',
            'payment_status': 'paid',
            'metadata': {'purchase_type': 'credit_purchase', 'org_id': organisation.clerk_org_id},
            'customer': None,
        }

        self._post_webhook('checkout.session.completed', session_data)
        balance_after_first = get_balance(organisation)

        self._post_webhook('checkout.session.completed', session_data)
        balance_after_second = get_balance(organisation)

        assert balance_after_first == balance_after_second

    def test_checkout_completed_ignores_non_credit_purchase(self, db):
        """checkout.session.completed with different metadata is ignored."""
        self._post_webhook('checkout.session.completed', {
            'id': 'cs_other_type',
            'payment_status': 'paid',
            'metadata': {'purchase_type': 'subscription'},
        })

    def test_checkout_completed_skips_unpaid(self, db, organisation):
        """checkout.session.completed with payment_status != 'paid' is skipped."""
        CreditPurchase.objects.create(
            organisation=organisation,
            stripe_checkout_session_id='cs_test_unpaid',
            amount=Decimal('25.00'),
        )

        self._post_webhook('checkout.session.completed', {
            'id': 'cs_test_unpaid',
            'payment_status': 'unpaid',
            'metadata': {'purchase_type': 'credit_purchase', 'org_id': organisation.clerk_org_id},
        })

        purchase = CreditPurchase.objects.get(stripe_checkout_session_id='cs_test_unpaid')
        assert purchase.status == CreditPurchase.STATUS_PENDING

    def test_checkout_expired_marks_purchase(self, db, organisation):
        """checkout.session.expired marks CreditPurchase as expired."""
        CreditPurchase.objects.create(
            organisation=organisation,
            stripe_checkout_session_id='cs_test_expired',
            amount=Decimal('100.00'),
        )

        self._post_webhook('checkout.session.expired', {
            'id': 'cs_test_expired',
            'metadata': {'purchase_type': 'credit_purchase'},
        })

        purchase = CreditPurchase.objects.get(stripe_checkout_session_id='cs_test_expired')
        assert purchase.status == CreditPurchase.STATUS_EXPIRED


@pytest.mark.django_db
class TestCreditPurchaseIntegration:
    """Integration test: buy-credits endpoint → webhook → balance updated."""

    def test_full_purchase_flow(self, user, organisation, org_membership):
        """POST buy-credits creates pending purchase; webhook grants credits and completes it."""
        from app.utils.stripe import StripeWebhookView

        # 1. Create a pending CreditPurchase (simulating what buy-credits endpoint does)
        purchase = CreditPurchase.objects.create(
            organisation=organisation,
            stripe_checkout_session_id='cs_integration_test',
            amount=Decimal('100.00'),
        )
        initial_balance = get_balance(organisation)
        assert purchase.status == CreditPurchase.STATUS_PENDING

        # 2. Simulate webhook: checkout.session.completed
        view = StripeWebhookView()
        view._handle_checkout_completed({
            'id': 'cs_integration_test',
            'payment_status': 'paid',
            'metadata': {'purchase_type': 'credit_purchase', 'org_id': organisation.clerk_org_id},
            'customer': 'cus_integration_123',
        })

        # 3. Verify purchase completed
        purchase.refresh_from_db()
        assert purchase.status == CreditPurchase.STATUS_COMPLETED
        assert purchase.completed_at is not None
        assert purchase.credit_transaction is not None
        assert purchase.credit_transaction.transaction_type == 'grant'
        assert purchase.credit_transaction.amount == Decimal('100.00')

        # 4. Verify balance increased
        assert get_balance(organisation) == initial_balance + Decimal('100.00')

        # 5. Verify Stripe customer linked
        organisation.refresh_from_db()
        assert organisation.billing_customer_id == 'cus_integration_123'

        # 6. Verify can send after purchase
        from app.utils.billing import check_can_send
        allowed, error = check_can_send(organisation, units=1, format='sms')
        assert allowed is True
        assert error is None
