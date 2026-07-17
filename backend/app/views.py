import io
import logging
from datetime import timedelta
from decimal import Decimal
import json

from clerk_backend_api import Clerk
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from svix.webhooks import Webhook, WebhookVerificationError

from app.mixins import TenantScopedMixin
from app.models import (
    Config,
    CreditPurchase,
    CreditTransaction,
    Invoice,
    Organisation,
    OrganisationMembership,
    User,
    WebhookEvent,
)
from app.permissions import IsOrgAdmin, IsOrgMember
from app.serializers import (
    BuyCreditSerializer,
    ConfigSerializer,
    CreditTransactionSerializer,
    InvoiceSerializer,
    UserSerializer,
)
from app.utils import clerk
from app.utils.billing import (
    get_current_month_preview,
    get_monthly_limit_info,
    get_monthly_usage,
    get_rate,
)
from app.utils.metered_billing import get_billing_provider
from app.celery import generate_monthly_invoices

logger = logging.getLogger(__name__)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get_queryset(self):
        org = getattr(self.request, 'org', None)
        if not org:
            return User.objects.none()
        return User.objects.filter(
            organisationmembership__organisation=org,
        ).annotate(
            _membership_role=Subquery(
                OrganisationMembership.objects.filter(
                    user=OuterRef('pk'), organisation=org,
                ).values('role')[:1]
            ),
            _org_name=Subquery(
                OrganisationMembership.objects.filter(
                    user=OuterRef('pk'), organisation=org,
                ).values('organisation__name')[:1]
            ),
            _is_active=Subquery(
                OrganisationMembership.objects.filter(
                    user=OuterRef('pk'), organisation=org,
                ).values('is_active')[:1]
            ),
        ).order_by('first_name', 'last_name')

    @action(detail=False, methods=['get'])
    def me(self, request):
        """GET /api/users/me/ — authenticated user (read-only, managed by Clerk)."""
        serializer = UserSerializer(request.user)
        # Exclude clerk_id from response
        data = serializer.data
        data.pop('clerk_id', None)
        return Response(data)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsOrgAdmin])
    def role(self, request, pk=None):
        """PATCH /api/users/{id}/role/ — update a member's role (admin only)."""
        new_role = request.data.get('role')
        if new_role not in ('org:admin', 'org:member'):
            return Response({'detail': 'Role must be org:admin or org:member.'}, status=status.HTTP_400_BAD_REQUEST)

        user = self.get_object()
        if user == request.user:
            return Response({'detail': 'Cannot change your own role.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)
            result = clerk_client.organization_memberships.update(
                organization_id=request.org.clerk_org_id,
                user_id=user.clerk_id,
                role=new_role,
            )
            return Response({'status': 'updated', 'role': result.role})
        except Exception as e:
            logger.error('Failed to update role via Clerk: %s', e, exc_info=True)
            return Response({'detail': f'Failed to update role: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsOrgAdmin])
    def status(self, request, pk=None):
        """PATCH /api/users/{id}/status/ — deactivate/reactivate a member (admin only)."""
        is_active = request.data.get('is_active')
        if not isinstance(is_active, bool):
            return Response({'detail': 'is_active must be a boolean.'}, status=status.HTTP_400_BAD_REQUEST)

        user = self.get_object()
        if user == request.user:
            return Response({'detail': 'Cannot change your own status.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)

            if not is_active:
                # Deactivate: delete membership via Clerk → webhook will soft-delete locally
                clerk_client.organization_memberships.delete(
                    organization_id=request.org.clerk_org_id,
                    user_id=user.clerk_id,
                )
                return Response({'status': 'deactivated', 'is_active': False})
            else:
                # Reactivate: send a new invitation via Clerk
                clerk_client.organization_invitations.create(
                    organization_id=request.org.clerk_org_id,
                    email_address=user.email,
                    role='org:member',
                    inviter_user_id=request.user.clerk_id,
                )
                return Response({'status': 'invitation_sent', 'is_active': False})
        except Exception as e:
            logger.error('Failed to update member status via Clerk: %s', e, exc_info=True)
            return Response({'detail': f'Failed to update status: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated, IsOrgAdmin])
    def invite(self, request):
        """POST /api/users/invite/ — invite a new user by email (admin only)."""
        email = request.data.get('email', '').strip()
        role = request.data.get('role', 'org:member')

        if not email:
            return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if role not in ('org:admin', 'org:member'):
            return Response({'detail': 'Role must be org:admin or org:member.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)
            clerk_client.organization_invitations.create(
                organization_id=request.org.clerk_org_id,
                email_address=email,
                role=role,
                inviter_user_id=request.user.clerk_id,
            )
            return Response({'status': 'invitation_sent', 'email': email}, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error('Failed to invite user via Clerk: %s', e, exc_info=True)
            return Response({'detail': f'Failed to send invitation: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)


class ClerkWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []  # Svix retries must never be rate limited

    def post(self, request):
        if settings.TEST:
            payload = json.loads(request.body)
        else:
            signing_secret = settings.CLERK_WEBHOOK_SIGNING_SECRET
            if not signing_secret:
                logger.error('CLERK_WEBHOOK_SIGNING_SECRET not configured')
                return Response({'error': 'Webhook not configured'}, status=500)

            headers = {
                'svix-id': request.headers.get('svix-id', ''),
                'svix-timestamp': request.headers.get('svix-timestamp', ''),
                'svix-signature': request.headers.get('svix-signature', ''),
            }

            try:
                wh = Webhook(signing_secret)
                payload = wh.verify(request.body, headers)
            except WebhookVerificationError:
                logger.error('Clerk webhook signature verification failed')
                return Response({'error': 'Invalid signature'}, status=400)

        event_type = payload.get('type')
        data = payload.get('data', {})
        logger.info('Clerk webhook: type=%s data_keys=%s', event_type, list(data.keys()))

        handler = clerk.WEBHOOK_HANDLERS.get(event_type)
        if not handler:
            logger.warning('Unhandled Clerk webhook event: %s', event_type)
            return Response({'status': 'ok'})

        # Dedup on the svix message id (stable across Svix's at-least-once
        # retries). The marker row commits atomically with the handler's side
        # effects: a failed handler rolls it back so the retry reprocesses,
        # while a duplicate delivery hits the unique constraint and is skipped.
        svix_id = request.headers.get('svix-id', '')
        with transaction.atomic():
            if svix_id:
                try:
                    with transaction.atomic():
                        WebhookEvent.objects.create(
                            provider=WebhookEvent.PROVIDER_CLERK,
                            event_id=svix_id,
                            event_type=event_type or '',
                        )
                except IntegrityError:
                    logger.info('Clerk webhook %s already processed — skipping duplicate', svix_id)
                    return Response({'status': 'ok', 'duplicate': True})

            handler(data)
        logger.info('Processed Clerk webhook event: %s', event_type)

        return Response({'status': 'ok'})


class ConfigViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Config.objects.all()
    serializer_class = ConfigSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']


class BillingViewSet(TenantScopedMixin, viewsets.GenericViewSet):
    """GET /api/billing/summary/ — billing summary and transaction history (admin only)."""
    permission_classes = [IsAuthenticated, IsOrgAdmin]
    serializer_class = CreditTransactionSerializer
    queryset = CreditTransaction.objects.all()

    def get_queryset(self):
        return super().get_queryset().order_by('-created_at')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        org = request.org
        limit_info = get_monthly_limit_info(org)

        known_usage_types = (
            CreditTransaction.objects.filter(organisation=org, usage_type__isnull=False)
            .values_list('usage_type', flat=True)
            .distinct()
        )
        monthly_usage_by_type = {
            usage_type: {
                'spend': str(get_monthly_usage(org, usage_type)),
                'rate': str(get_rate(usage_type, org)),
            }
            for usage_type in known_usage_types
        }

        page = self.paginate_queryset(self.get_queryset())
        tx_data = self.get_serializer(page, many=True).data
        response = self.get_paginated_response(tx_data)

        # Latest invoice (for subscribed orgs)
        latest_invoice = None
        latest = (
            Invoice.objects.filter(organisation=org)
            .order_by('-period_start')
            .first()
        )
        if latest:
            latest_invoice = {
                'status': latest.status,
                'amount': str(latest.amount),
                'invoice_url': latest.invoice_url,
                'period_start': latest.period_start.isoformat(),
                'period_end': latest.period_end.isoformat(),
            }

        response.data.update({
            'billing_mode': org.billing_mode,
            'balance': str(org.credit_balance),
            'monthly_limit': str(limit_info['limit']) if limit_info['limit'] is not None else None,
            'total_monthly_spend': str(limit_info['current']),
            'monthly_usage_by_type': monthly_usage_by_type,
            'latest_invoice': latest_invoice,
        })
        return response

    @action(detail=False, methods=['post'], url_path='buy-credits')
    def buy_credits(self, request):
        """POST /api/billing/buy-credits/ — create a Stripe Checkout Session for credit purchase."""
        org = request.org

        if org.billing_mode == Organisation.BILLING_PAST_DUE:
            return Response(
                {'detail': 'Cannot purchase credits while subscription payment is past due.'},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        serializer = BuyCreditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = Decimal(serializer.validated_data['amount'])

        provider = get_billing_provider()
        base_url = f'{settings.FRONTEND_URL}/app/billing'
        result = provider.create_checkout_session(
            customer_id=org.billing_customer_id,
            amount=amount,
            org_id=org.clerk_org_id,
            success_url=f'{base_url}?purchase=success',
            cancel_url=f'{base_url}?purchase=cancelled',
        )

        if not result.success:
            return Response(
                {'detail': f'Failed to create checkout session: {result.error}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        CreditPurchase.objects.create(
            organisation=org,
            stripe_checkout_session_id=result.session_id,
            amount=amount,
        )

        return Response({'checkout_url': result.checkout_url})

    @action(detail=False, methods=['patch'], url_path='test-set-balance')
    def test_set_balance(self, request):
        """PATCH /api/billing/test-set-balance/ — set org credit balance (and optionally
        billing_customer_id) directly (TEST mode only)."""
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        update_fields = []
        if 'balance' in request.data:
            request.org.credit_balance = Decimal(str(request.data['balance']))
            update_fields.append('credit_balance')
        if 'billing_customer_id' in request.data:
            request.org.billing_customer_id = request.data['billing_customer_id']
            update_fields.append('billing_customer_id')
        if update_fields:
            request.org.save(update_fields=update_fields)
        return Response({'credit_balance': str(request.org.credit_balance)})

    @action(detail=False, methods=['post'], url_path='test-seed-usage')
    def test_seed_usage(self, request):
        """POST /api/billing/test-seed-usage/ — create CreditTransaction usage records (TEST mode only).

        Body: { "usage_type": "api_call", "amount": "2.50", "description": "Test usage",
                "reference": "order:1234", "backdate_days": 35 }
        Optional backdate_days shifts created_at into the past (for invoice generation testing).
        """
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        usage_type = request.data.get('usage_type', 'default')
        tx = CreditTransaction.objects.create(
            organisation=request.org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal(str(request.data['amount'])),
            balance_after=request.org.credit_balance,
            description=request.data.get('description', 'E2E test usage'),
            usage_type=usage_type,
            reference=request.data.get('reference'),
            unit_rate=get_rate(usage_type, request.org),
        )
        backdate_days = request.data.get('backdate_days')
        if backdate_days:
            backdated = timezone.now() - timedelta(days=int(backdate_days))
            CreditTransaction.objects.filter(pk=tx.pk).update(created_at=backdated)
        return Response({'status': 'ok'})

    @action(detail=False, methods=['post'], url_path='test-generate-invoices')
    def test_generate_invoices(self, request):
        """POST /api/billing/test-generate-invoices/ — trigger invoice generation (TEST mode only)."""
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        result = generate_monthly_invoices()
        return Response(result)

    @action(detail=False, methods=['post'], url_path='test-create-invoice')
    def test_create_invoice(self, request):
        """POST /api/billing/test-create-invoice/ — create an Invoice record directly (TEST mode only).

        Bypasses the billing provider entirely. Used in E2E tests when the real
        Stripe provider would reject a mock customer ID.

        Body: { "amount": "3.50", "period_start": "2026-03-01T00:00:00+10:30",
                "period_end": "2026-04-01T00:00:00+10:30" }
        """
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        inv = Invoice.objects.create(
            organisation=request.org,
            provider_invoice_id=f'mock_inv_{request.org.pk}_{Invoice.objects.filter(organisation=request.org).count() + 1}',
            status=Invoice.STATUS_OPEN,
            amount=Decimal(str(request.data.get('amount', '3.50'))),
            invoice_url=f'https://mock-billing.example.com/invoices/mock_inv_{request.org.pk}',
            period_start=request.data['period_start'],
            period_end=request.data['period_end'],
        )
        return Response(InvoiceSerializer(inv).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='test-link-billing-customer')
    def test_link_billing_customer(self, request):
        """POST /api/billing/test-link-billing-customer/ — trigger Stripe customer lookup (TEST mode only).

        Searches Stripe for a customer matching the org's clerk_org_id and saves
        the billing_customer_id. Used in E2E tests where the async retry task
        may not have run yet.
        """
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        org = request.org
        if org.billing_customer_id:
            return Response({'billing_customer_id': org.billing_customer_id, 'already_linked': True})
        provider = get_billing_provider()
        result = provider.find_customer_by_org(org.clerk_org_id)
        if result.success:
            Organisation.objects.filter(pk=org.pk).update(billing_customer_id=result.customer_id)
            return Response({'billing_customer_id': result.customer_id, 'already_linked': False})
        return Response({'error': result.error}, status=404)

    @action(detail=False, methods=['get'])
    def invoices(self, request):
        """GET /api/billing/invoices/ — paginated list of all invoices for this org."""
        qs = Invoice.objects.filter(
            organisation=request.org,
        ).order_by('-period_start')
        page = self.paginate_queryset(qs)
        data = InvoiceSerializer(page, many=True).data
        return self.get_paginated_response(data)

    @action(detail=False, methods=['get'], url_path='invoice-preview')
    def invoice_preview(self, request):
        """GET /api/billing/invoice-preview/ — current month usage preview."""
        return Response(get_current_month_preview(request.org))

    @action(detail=False, methods=['post'], url_path='invoice-download')
    def invoice_download(self, request):
        """POST /api/billing/invoice-download/ — download invoice PDFs.

        Body: { "invoice_ids": [1, 2, 3] }
        Single invoice returns application/pdf; multiple returns application/zip.
        """
        import zipfile

        invoice_ids = request.data.get('invoice_ids', [])
        if not invoice_ids:
            return Response({'detail': 'invoice_ids is required.'}, status=status.HTTP_400_BAD_REQUEST)

        invoices = Invoice.objects.filter(
            organisation=request.org,
            pk__in=invoice_ids,
        )
        if not invoices.exists():
            return Response({'detail': 'No invoices found.'}, status=status.HTTP_404_NOT_FOUND)

        provider = get_billing_provider()
        results = []
        for inv in invoices:
            result = provider.get_invoice_pdf(inv.provider_invoice_id)
            if result.success and result.content:
                month_label = inv.period_start.strftime('%B_%Y').lower()
                results.append((f'{month_label}_invoice.pdf', result.content))

        if not results:
            return Response(
                {'detail': 'Could not fetch any invoice PDFs.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if len(results) == 1:
            filename, content = results[0]
            response = HttpResponse(content, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        # Multiple invoices — bundle into a zip
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filename, content in results:
                zf.writestr(filename, content)
        buffer.seek(0)

        response = HttpResponse(buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="invoices.zip"'
        return response
