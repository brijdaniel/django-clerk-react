"""
Tests for Billing API endpoint (BillingViewSet).

Tests:
- GET /api/billing/summary/ requires admin role
- Returns correct billing_mode, balance, monthly_limit, total_monthly_spend
- monthly_usage_by_format populated from CreditTransactions
- Paginated transaction history
- Multi-tenancy isolation
"""

import pytest
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings

from rest_framework import status
from rest_framework.test import APIClient

from app.models import Invoice, Organisation, User, OrganisationMembership
from app.utils.billing import grant_credits, record_usage
from app.utils.metered_billing import PdfResult
from tests.factories import ConfigFactory, OrganisationFactory, UserFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_admin_client(user, organisation):
    """Return an APIClient authenticated as an org admin."""
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
    return client, original_dispatch


@pytest.mark.django_db
class TestBillingSummaryPermissions:
    """Access control for GET /api/billing/summary/."""

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests denied."""
        response = api_client.get('/api/billing/summary/')
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    def test_member_denied(self, authenticated_client):
        """Non-admin members receive 403."""
        # authenticated_client uses org_role='member'
        response = authenticated_client.get('/api/billing/summary/')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_allowed(self, user, organisation, org_membership):
        """Admin members can access billing summary."""
        from rest_framework.views import APIView
        client, original_dispatch = make_admin_client(user, organisation)
        try:
            response = client.get('/api/billing/summary/')
            assert response.status_code == status.HTTP_200_OK
        finally:
            APIView.dispatch = original_dispatch


@pytest.mark.django_db
class TestBillingSummaryFields:
    """Response structure for GET /api/billing/summary/."""

    def setup_method(self):
        self._original_dispatch = None

    def teardown_method(self):
        if self._original_dispatch:
            from rest_framework.views import APIView
            APIView.dispatch = self._original_dispatch

    def _get_admin_response(self, user, organisation):
        from rest_framework.views import APIView
        client, original_dispatch = make_admin_client(user, organisation)
        self._original_dispatch = original_dispatch
        return client.get('/api/billing/summary/')

    def test_returns_required_fields(self, user, organisation, org_membership):
        """Summary response contains all required fields."""
        response = self._get_admin_response(user, organisation)

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert 'billing_mode' in data
        assert 'balance' in data
        assert 'monthly_limit' in data
        assert 'total_monthly_spend' in data
        assert 'monthly_usage_by_format' in data
        assert 'results' in data
        assert 'pagination' in data

    def test_prepaid_billing_mode(self, user, organisation, org_membership):
        """Prepaid org shows billing_mode='prepaid' and current balance."""
        organisation.billing_mode = Organisation.BILLING_PREPAID
        organisation.credit_balance = Decimal('7.50')
        organisation.save()

        response = self._get_admin_response(user, organisation)

        assert response.data['billing_mode'] == 'prepaid'
        assert response.data['balance'] == '7.50'

    def test_subscribed_billing_mode(self, user, organisation, org_membership):
        """Subscribed org shows billing_mode='subscribed'."""
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()

        response = self._get_admin_response(user, organisation)

        assert response.data['billing_mode'] == 'subscribed'

    def test_monthly_limit_null_when_not_set(self, user, organisation, org_membership):
        """monthly_limit is null when no Config record exists."""
        response = self._get_admin_response(user, organisation)

        assert response.data['monthly_limit'] is None

    def test_monthly_limit_returned_when_set(self, user, organisation, org_membership):
        """monthly_limit matches Config value when set."""
        ConfigFactory(organisation=organisation, name='monthly_limit', value='25.00')

        response = self._get_admin_response(user, organisation)

        assert response.data['monthly_limit'] == '25.00'

    def test_total_monthly_spend_zero_with_no_usage(self, user, organisation, org_membership):
        """total_monthly_spend is '0.00' when no transactions exist."""
        response = self._get_admin_response(user, organisation)

        assert response.data['total_monthly_spend'] == '0.00'

    def test_total_monthly_spend_reflects_usage(self, user, organisation, org_membership):
        """total_monthly_spend sums usage transactions."""
        organisation.billing_mode = Organisation.BILLING_PREPAID
        organisation.credit_balance = Decimal('10.00')
        organisation.save()
        record_usage(organisation, 2, format='sms', description='SMS send', user=user)

        response = self._get_admin_response(user, organisation)

        expected_spend = str(2 * settings.SMS_RATE)
        assert response.data['total_monthly_spend'] == expected_spend

    def test_monthly_usage_by_format_populated(self, user, organisation, org_membership):
        """monthly_usage_by_format contains entries for each format used."""
        organisation.billing_mode = Organisation.BILLING_PREPAID
        organisation.credit_balance = Decimal('10.00')
        organisation.save()
        record_usage(organisation, 1, format='sms', description='SMS', user=user)
        record_usage(organisation, 1, format='mms', description='MMS', user=user)

        response = self._get_admin_response(user, organisation)

        usage = response.data['monthly_usage_by_format']
        assert 'sms' in usage
        assert 'mms' in usage
        assert usage['sms']['spend'] == str(settings.SMS_RATE)
        assert usage['sms']['rate'] == str(settings.SMS_RATE)
        assert usage['mms']['spend'] == str(settings.MMS_RATE)
        assert usage['mms']['rate'] == str(settings.MMS_RATE)

    def test_monthly_usage_shows_per_org_rate(self, user, organisation, org_membership):
        """When an org has a custom rate override, the summary returns that rate."""
        organisation.billing_mode = Organisation.BILLING_PREPAID
        organisation.credit_balance = Decimal('10.00')
        organisation.save()
        ConfigFactory(organisation=organisation, name='sms_rate', value='0.03')
        record_usage(organisation, 1, format='sms', description='SMS', user=user)

        response = self._get_admin_response(user, organisation)

        usage = response.data['monthly_usage_by_format']
        assert usage['sms']['rate'] == '0.03'
        assert usage['sms']['spend'] == '0.03'

    def test_empty_results_when_no_transactions(self, user, organisation, org_membership):
        """results list is empty when no transactions exist."""
        response = self._get_admin_response(user, organisation)

        assert response.data['results'] == []
        assert response.data['pagination']['total'] == 0

    def test_transaction_history_returned(self, user, organisation, org_membership):
        """Transaction history includes created transactions."""
        grant_credits(organisation, Decimal('5.00'), 'Test grant')

        response = self._get_admin_response(user, organisation)

        assert response.data['pagination']['total'] == 1
        tx = response.data['results'][0]
        assert tx['transaction_type'] == 'grant'
        assert tx['amount'] == '5.00'
        assert 'created_at' in tx

    def test_transaction_history_ordered_newest_first(self, user, organisation, org_membership):
        """Transactions ordered by newest first."""
        organisation.billing_mode = Organisation.BILLING_PREPAID
        organisation.credit_balance = Decimal('10.00')
        organisation.save()
        grant_credits(organisation, Decimal('1.00'), 'First')
        record_usage(organisation, 1, format='sms', description='Second', user=user)

        response = self._get_admin_response(user, organisation)

        results = response.data['results']
        assert len(results) == 2
        # Most recent (deduct) first
        assert results[0]['transaction_type'] == 'deduct'
        assert results[1]['transaction_type'] == 'grant'


@pytest.mark.django_db
class TestBillingSummaryMultiTenancy:
    """Billing summary only exposes data from the request org."""

    def teardown_method(self):
        from rest_framework.views import APIView
        if hasattr(self, '_original_dispatch'):
            APIView.dispatch = self._original_dispatch

    def test_other_org_transactions_excluded(self, user, organisation, org_membership):
        """Transactions from other orgs are not returned."""
        from rest_framework.views import APIView

        # Transactions in user's org
        grant_credits(organisation, Decimal('5.00'), 'My grant')

        # Transactions in another org
        other_org = OrganisationFactory()
        grant_credits(other_org, Decimal('100.00'), 'Other grant')

        client, original_dispatch = make_admin_client(user, organisation)
        self._original_dispatch = original_dispatch
        response = client.get('/api/billing/summary/')

        assert response.data['pagination']['total'] == 1
        assert response.data['results'][0]['amount'] == '5.00'


@pytest.mark.django_db
class TestInvoicesList:
    """Tests for GET /api/billing/invoices/."""

    def setup_method(self):
        self._original_dispatch = None

    def teardown_method(self):
        if self._original_dispatch:
            from rest_framework.views import APIView
            APIView.dispatch = self._original_dispatch

    def _get_admin_response(self, user, organisation, path='/api/billing/invoices/'):
        from rest_framework.views import APIView
        client, original_dispatch = make_admin_client(user, organisation)
        self._original_dispatch = original_dispatch
        return client.get(path)

    def test_empty_list(self, user, organisation, org_membership):
        response = self._get_admin_response(user, organisation)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['results'] == []
        assert response.data['pagination']['total'] == 0

    def test_returns_invoices(self, user, organisation, org_membership):
        Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_test1',
            status=Invoice.STATUS_PAID,
            amount=Decimal('5.00'),
            invoice_url='https://example.com/inv1',
            period_start='2026-03-01T00:00:00+10:30',
            period_end='2026-04-01T00:00:00+10:30',
        )
        Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_test2',
            status=Invoice.STATUS_OPEN,
            amount=Decimal('3.00'),
            period_start='2026-04-01T00:00:00+10:30',
            period_end='2026-05-01T00:00:00+10:30',
        )

        response = self._get_admin_response(user, organisation)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pagination']['total'] == 2
        # Ordered by -period_start, so April invoice first
        assert response.data['results'][0]['provider_invoice_id'] == 'inv_test2'
        assert response.data['results'][1]['provider_invoice_id'] == 'inv_test1'

    def test_excludes_other_org_invoices(self, user, organisation, org_membership):
        other_org = OrganisationFactory()
        Invoice.objects.create(
            organisation=other_org,
            provider_invoice_id='inv_other',
            status=Invoice.STATUS_PAID,
            amount=Decimal('10.00'),
            period_start='2026-03-01T00:00:00+10:30',
            period_end='2026-04-01T00:00:00+10:30',
        )

        response = self._get_admin_response(user, organisation)

        assert response.data['pagination']['total'] == 0


@pytest.mark.django_db
class TestInvoicePreview:
    """Tests for GET /api/billing/invoice-preview/."""

    def setup_method(self):
        self._original_dispatch = None

    def teardown_method(self):
        if self._original_dispatch:
            from rest_framework.views import APIView
            APIView.dispatch = self._original_dispatch

    def test_empty_preview(self, user, organisation, org_membership):
        from rest_framework.views import APIView
        client, original_dispatch = make_admin_client(user, organisation)
        self._original_dispatch = original_dispatch

        response = client.get('/api/billing/invoice-preview/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['total'] == '0'
        assert response.data['line_items'] == []

    def test_preview_with_usage(self, user, organisation, org_membership):
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()
        record_usage(organisation, 2, 'sms', 'test SMS', user)

        from rest_framework.views import APIView
        client, original_dispatch = make_admin_client(user, organisation)
        self._original_dispatch = original_dispatch

        response = client.get('/api/billing/invoice-preview/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['total'] == str(2 * settings.SMS_RATE)
        assert len(response.data['line_items']) == 1
        assert response.data['line_items'][0]['quantity'] == 2

    def test_preview_with_multiple_formats(self, user, organisation, org_membership):
        """Preview shows both SMS and MMS usage."""
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()
        record_usage(organisation, 2, 'sms', 'SMS test', user)
        record_usage(organisation, 1, 'mms', 'MMS test', user)

        from rest_framework.views import APIView
        client, original_dispatch = make_admin_client(user, organisation)
        self._original_dispatch = original_dispatch

        response = client.get('/api/billing/invoice-preview/')

        assert response.status_code == status.HTTP_200_OK
        formats = {item['format'] for item in response.data['line_items']}
        assert 'sms' in formats
        assert 'mms' in formats
        assert len(response.data['line_items']) == 2


@pytest.mark.django_db
class TestInvoiceDownload:
    """Tests for POST /api/billing/invoice-download/."""

    def setup_method(self):
        self._original_dispatch = None

    def teardown_method(self):
        if self._original_dispatch:
            from rest_framework.views import APIView
            APIView.dispatch = self._original_dispatch

    def _post_admin(self, user, organisation, data):
        from rest_framework.views import APIView
        client, original_dispatch = make_admin_client(user, organisation)
        self._original_dispatch = original_dispatch
        return client.post('/api/billing/invoice-download/', data, format='json')

    def test_empty_ids_returns_400(self, user, organisation, org_membership):
        response = self._post_admin(user, organisation, {'invoice_ids': []})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_ids_returns_404(self, user, organisation, org_membership):
        response = self._post_admin(user, organisation, {'invoice_ids': [9999]})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch('app.views.get_billing_provider')
    def test_single_pdf_download(self, mock_get_provider, user, organisation, org_membership):
        invoice = Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_dl1',
            status=Invoice.STATUS_PAID,
            amount=Decimal('5.00'),
            period_start='2026-03-01T00:00:00+10:30',
            period_end='2026-04-01T00:00:00+10:30',
        )

        mock_provider = mock_get_provider.return_value
        mock_provider.get_invoice_pdf.return_value = PdfResult(
            success=True,
            content=b'%PDF-1.4 test',
            filename='invoice-inv_dl1.pdf',
        )

        response = self._post_admin(user, organisation, {'invoice_ids': [invoice.pk]})

        assert response.status_code == status.HTTP_200_OK
        assert response['Content-Type'] == 'application/pdf'
        assert 'attachment; filename=' in response['Content-Disposition']
        assert '_invoice_1reach.pdf"' in response['Content-Disposition']

    @patch('app.views.get_billing_provider')
    def test_multiple_pdf_download_returns_zip(self, mock_get_provider, user, organisation, org_membership):
        inv1 = Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_z1',
            status=Invoice.STATUS_PAID,
            amount=Decimal('5.00'),
            period_start='2026-03-01T00:00:00+10:30',
            period_end='2026-04-01T00:00:00+10:30',
        )
        inv2 = Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_z2',
            status=Invoice.STATUS_PAID,
            amount=Decimal('3.00'),
            period_start='2026-04-01T00:00:00+10:30',
            period_end='2026-05-01T00:00:00+10:30',
        )

        mock_provider = mock_get_provider.return_value
        mock_provider.get_invoice_pdf.return_value = PdfResult(
            success=True,
            content=b'%PDF-1.4 test',
            filename='invoice.pdf',
        )

        response = self._post_admin(user, organisation, {
            'invoice_ids': [inv1.pk, inv2.pk],
        })

        assert response.status_code == status.HTTP_200_OK
        assert response['Content-Type'] == 'application/zip'
        assert 'invoices.zip' in response['Content-Disposition']

    @patch('app.views.get_billing_provider')
    def test_all_pdfs_fail_returns_404(self, mock_get_provider, user, organisation, org_membership):
        invoice = Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_fail',
            status=Invoice.STATUS_PAID,
            amount=Decimal('5.00'),
            period_start='2026-03-01T00:00:00+10:30',
            period_end='2026-04-01T00:00:00+10:30',
        )

        mock_provider = mock_get_provider.return_value
        mock_provider.get_invoice_pdf.return_value = PdfResult(
            success=False, error='Stripe error',
        )

        response = self._post_admin(user, organisation, {'invoice_ids': [invoice.pk]})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_member_denied(self, authenticated_client, organisation, org_membership):
        """Non-admin members receive 403."""
        invoice = Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_member',
            status=Invoice.STATUS_PAID,
            amount=Decimal('5.00'),
            period_start='2026-03-01T00:00:00+10:30',
            period_end='2026-04-01T00:00:00+10:30',
        )
        response = authenticated_client.post(
            '/api/billing/invoice-download/',
            {'invoice_ids': [invoice.pk]},
            format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_org_invoice_excluded(self, user, organisation, org_membership):
        """Cannot download invoices belonging to another org."""
        other_org = OrganisationFactory()
        other_invoice = Invoice.objects.create(
            organisation=other_org,
            provider_invoice_id='inv_other_org',
            status=Invoice.STATUS_PAID,
            amount=Decimal('10.00'),
            period_start='2026-03-01T00:00:00+10:30',
            period_end='2026-04-01T00:00:00+10:30',
        )

        response = self._post_admin(user, organisation, {'invoice_ids': [other_invoice.pk]})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch('app.views.get_billing_provider')
    def test_partial_pdf_failure_returns_successful_ones(self, mock_get_provider, user, organisation, org_membership):
        """If one PDF fails but another succeeds, zip contains only the successful one."""
        inv_ok = Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_ok',
            status=Invoice.STATUS_PAID,
            amount=Decimal('5.00'),
            period_start='2026-03-01T00:00:00+10:30',
            period_end='2026-04-01T00:00:00+10:30',
        )
        inv_fail = Invoice.objects.create(
            organisation=organisation,
            provider_invoice_id='inv_bad',
            status=Invoice.STATUS_PAID,
            amount=Decimal('3.00'),
            period_start='2026-04-01T00:00:00+10:30',
            period_end='2026-05-01T00:00:00+10:30',
        )

        mock_provider = mock_get_provider.return_value
        mock_provider.get_invoice_pdf.side_effect = [
            PdfResult(success=True, content=b'%PDF-1.4 ok', filename='ok.pdf'),
            PdfResult(success=False, error='Stripe error'),
        ]

        response = self._post_admin(user, organisation, {
            'invoice_ids': [inv_ok.pk, inv_fail.pk],
        })

        # Only one succeeded, so returns a single PDF (not zip)
        assert response.status_code == status.HTTP_200_OK
        assert response['Content-Type'] == 'application/pdf'
