"""
Stripe implementation of the MeteredBillingProvider.

Also includes StripeWebhookView for handling Stripe webhook events
(invoice.paid, invoice.payment_failed, invoice.voided).
"""

import logging
from datetime import datetime
from decimal import Decimal

import requests as http_requests
import stripe
from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from django.db import IntegrityError
from django.db import transaction as db_transaction


from app.models import CreditPurchase, Invoice, Organisation, WebhookEvent
from app.utils.billing import grant_credits
from app.utils.metered_billing import (
    CheckoutResult,
    CustomerResult,
    InvoiceLineItem,
    InvoiceResult,
    MeteredBillingProvider,
    PdfResult,
    get_billing_provider,
)

logger = logging.getLogger(__name__)


class StripeMeteredBillingProvider(MeteredBillingProvider):
    """Stripe implementation of the metered billing provider."""

    # Pin the Stripe API version to prevent breaking changes from new versions.
    # Update this deliberately when upgrading, after verifying compatibility.
    STRIPE_API_VERSION = '2026-03-25.dahlia'

    def __init__(self, secret_key: str, webhook_secret: str = ''):
        if not secret_key:
            raise ValueError('STRIPE_SECRET_KEY is required for StripeMeteredBillingProvider')
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        stripe.api_key = secret_key
        stripe.api_version = self.STRIPE_API_VERSION

    def find_customer_by_org(self, org_id: str) -> CustomerResult:
        """Search Stripe for a customer with metadata.organization_id matching the Clerk org ID."""
        try:
            result = stripe.Customer.search(
                query=f"metadata['organization_id']:'{org_id}'",
            )
            if result.data:
                customer = result.data[0]
                return CustomerResult(success=True, customer_id=customer.id)
            return CustomerResult(
                success=False,
                error=f'No Stripe customer found for org {org_id}',
            )
        except stripe.StripeError as e:
            logger.warning(
                'Stripe customer search failed for org %s: %s',
                org_id, str(e), exc_info=True,
            )
            return CustomerResult(success=False, error=str(e))

    def create_invoice(
        self,
        customer_id: str,
        line_items: list[InvoiceLineItem],
        period_start: datetime,
        period_end: datetime,
        auto_send: bool = True,
    ) -> InvoiceResult:
        """Create a Stripe invoice with calculated line items."""
        try:
            # Create the invoice
            invoice = stripe.Invoice.create(
                customer=customer_id,
                auto_advance=auto_send,
                collection_method='charge_automatically',
                metadata={
                    'period_start': period_start.isoformat(),
                    'period_end': period_end.isoformat(),
                },
            )

            # Add line items
            for item in line_items:
                stripe.InvoiceItem.create(
                    customer=customer_id,
                    invoice=invoice.id,
                    amount=int(item.amount * 100),  # Stripe uses cents
                    currency=settings.STRIPE_CURRENCY,
                    description=item.description,
                    metadata={
                        'quantity': str(item.quantity),
                        'unit_amount': str(item.unit_amount),
                    },
                )

            # Finalise the invoice
            finalised = stripe.Invoice.finalize_invoice(invoice.id)

            return InvoiceResult(
                success=True,
                invoice_id=finalised.id,
                invoice_url=finalised.hosted_invoice_url,
                status=finalised.status,
            )
        except stripe.StripeError as e:
            logger.error(
                'Failed to create Stripe invoice for customer %s: %s',
                customer_id, str(e), exc_info=True,
            )
            return InvoiceResult(success=False, error=str(e))

    def get_invoice(self, invoice_id: str) -> InvoiceResult:
        """Fetch current status of a Stripe invoice."""
        try:
            invoice = stripe.Invoice.retrieve(invoice_id)
            return InvoiceResult(
                success=True,
                invoice_id=invoice.id,
                invoice_url=invoice.hosted_invoice_url,
                status=invoice.status,
            )
        except stripe.StripeError as e:
            logger.warning(
                'Failed to retrieve Stripe invoice %s: %s',
                invoice_id, str(e), exc_info=True,
            )
            return InvoiceResult(success=False, error=str(e))

    def void_invoice(self, invoice_id: str) -> InvoiceResult:
        """Void a Stripe invoice."""
        try:
            invoice = stripe.Invoice.void_invoice(invoice_id)
            return InvoiceResult(
                success=True,
                invoice_id=invoice.id,
                status=invoice.status,
            )
        except stripe.StripeError as e:
            logger.warning(
                'Failed to void Stripe invoice %s: %s',
                invoice_id, str(e), exc_info=True,
            )
            return InvoiceResult(success=False, error=str(e))

    def get_invoice_pdf(self, invoice_id: str) -> PdfResult:
        """Fetch a fresh PDF URL from Stripe and download the PDF bytes."""
        try:
            invoice = stripe.Invoice.retrieve(invoice_id)
            pdf_url = invoice.invoice_pdf
            if not pdf_url:
                return PdfResult(success=False, error=f'No PDF available for invoice {invoice_id}')

            response = http_requests.get(pdf_url, timeout=30)
            response.raise_for_status()

            return PdfResult(
                success=True,
                content=response.content,
                filename=f'invoice-{invoice_id}.pdf',
            )
        except stripe.StripeError as e:
            logger.warning(
                'Failed to retrieve Stripe invoice %s for PDF: %s',
                invoice_id, str(e), exc_info=True,
            )
            return PdfResult(success=False, error=str(e))
        except http_requests.RequestException as e:
            logger.warning(
                'Failed to download PDF for Stripe invoice %s: %s',
                invoice_id, str(e), exc_info=True,
            )
            return PdfResult(success=False, error=str(e))

    def create_checkout_session(
        self,
        customer_id: str | None,
        amount: Decimal,
        org_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        """Create a Stripe Checkout Session for a one-time credit purchase."""
        try:
            params: dict = {
                'mode': 'payment',
                'currency': settings.STRIPE_CURRENCY,
                'line_items': [{
                    'price_data': {
                        'currency': settings.STRIPE_CURRENCY,
                        'unit_amount': int(amount * 100),
                        'product_data': {
                            'name': f'${amount:.0f} Credit Top-Up',
                        },
                    },
                    'quantity': 1,
                }],
                'success_url': success_url,
                'cancel_url': cancel_url,
                'metadata': {
                    'purchase_type': 'credit_purchase',
                    'org_id': org_id,
                },
            }
            if customer_id:
                params['customer'] = customer_id
            else:
                params['customer_creation'] = 'always'

            session = stripe.checkout.Session.create(**params)
            return CheckoutResult(
                success=True,
                session_id=session.id,
                checkout_url=session.url,
            )
        except stripe.StripeError as e:
            logger.error(
                'Failed to create checkout session for org %s: %s',
                org_id, str(e), exc_info=True,
            )
            return CheckoutResult(success=False, error=str(e))

    def parse_webhook(self, payload: bytes, signature: str) -> dict:
        """Parse and verify a Stripe webhook payload."""
        event = stripe.Webhook.construct_event(
            payload, signature, self._webhook_secret,
        )
        data_obj = event.data.object
        return {
            'id': event.id,
            'type': event.type,
            'data': data_obj.to_dict() if isinstance(data_obj, stripe.StripeObject) else data_obj,
        }


# ---------------------------------------------------------------------------
# Webhook view
# ---------------------------------------------------------------------------

class StripeWebhookView(APIView):
    """Handle Stripe webhook events for invoice and checkout session updates.

    Events handled:
      - invoice.paid → Invoice.status = 'paid'; restore org to subscribed if no other unpaid invoices
      - invoice.payment_failed → Invoice.status = 'uncollectable'; Organisation.billing_mode = 'past_due'
      - invoice.overdue → same as payment_failed (blocks sends before Stripe exhausts charge retries)
      - invoice.voided → Invoice.status = 'void'
      - checkout.session.completed → grant purchased credits to org
      - checkout.session.expired → mark CreditPurchase as expired
    """
    authentication_classes = []
    permission_classes = []
    throttle_classes = []  # Stripe retries must never be rate limited

    def post(self, request: Request) -> Response:
        payload = request.body
        signature = request.META.get('HTTP_STRIPE_SIGNATURE', '')

        provider = get_billing_provider()
        try:
            event = provider.parse_webhook(payload, signature)
        except (ValueError, stripe.SignatureVerificationError) as e:
            logger.warning('Stripe webhook signature verification failed: %s', e)
            return Response({'error': 'Invalid signature'}, status=400)

        event_type = event['type']
        event_id = event.get('id', '')
        invoice_data = event['data']
        invoice_id = invoice_data.get('id', '')

        # Dedup on the Stripe event id (stable across Stripe's at-least-once
        # retries). The marker commits atomically with the handler's side
        # effects: a failed handler rolls it back so the retry reprocesses,
        # while a duplicate delivery hits the unique constraint and is skipped.
        with db_transaction.atomic():
            if event_id:
                try:
                    with db_transaction.atomic():
                        WebhookEvent.objects.create(
                            provider=WebhookEvent.PROVIDER_STRIPE,
                            event_id=event_id,
                            event_type=event_type,
                        )
                except IntegrityError:
                    logger.info('Stripe event %s already processed — skipping duplicate', event_id)
                    return Response({'status': 'ok', 'duplicate': True})

            if event_type == 'invoice.paid':
                self._handle_invoice_paid(invoice_id)
            elif event_type in ('invoice.payment_failed', 'invoice.overdue'):
                self._handle_invoice_payment_failed(invoice_id)
            elif event_type == 'invoice.voided':
                self._handle_invoice_voided(invoice_id)
            elif event_type == 'checkout.session.completed':
                self._handle_checkout_completed(invoice_data)
            elif event_type == 'checkout.session.expired':
                self._handle_checkout_expired(invoice_data)
            else:
                logger.debug('Ignoring Stripe event: %s', event_type)

        return Response({'status': 'ok'})

    def _handle_invoice_paid(self, invoice_id: str) -> None:
        updated = Invoice.objects.filter(
            provider_invoice_id=invoice_id,
        ).update(status=Invoice.STATUS_PAID)

        if updated:
            invoice = Invoice.objects.select_related('organisation').get(
                provider_invoice_id=invoice_id,
            )
            org = invoice.organisation
            if org.billing_mode == Organisation.BILLING_PAST_DUE:
                # A paid metered invoice only clears Stripe-set past_due. If Clerk
                # set past_due (subscription fee unpaid — no Stripe invoice row of
                # ours), only subscription.active may restore the org.
                if org.past_due_source == Organisation.PAST_DUE_SOURCE_CLERK:
                    logger.info(
                        'Invoice %s paid for org %s but past_due was set by Clerk — keeping past_due',
                        invoice_id, org.clerk_org_id,
                    )
                    return
                # Only restore to subscribed if no other uncollectable invoices remain
                has_other_unpaid = Invoice.objects.filter(
                    organisation=org,
                    status=Invoice.STATUS_UNCOLLECTABLE,
                ).exclude(provider_invoice_id=invoice_id).exists()
                if not has_other_unpaid:
                    Organisation.objects.filter(pk=org.pk).update(
                        billing_mode=Organisation.BILLING_SUBSCRIBED,
                        past_due_source=None,
                    )
                    logger.info(
                        'Restored org %s to subscribed after invoice %s paid',
                        org.clerk_org_id, invoice_id,
                    )
                else:
                    logger.info(
                        'Invoice %s paid for org %s but other unpaid invoices remain — keeping past_due',
                        invoice_id, org.clerk_org_id,
                    )
        else:
            logger.warning('invoice.paid: no matching invoice for %s', invoice_id)

    def _handle_invoice_payment_failed(self, invoice_id: str) -> None:
        updated = Invoice.objects.filter(
            provider_invoice_id=invoice_id,
        ).update(status=Invoice.STATUS_UNCOLLECTABLE)

        if updated:
            invoice = Invoice.objects.select_related('organisation').get(
                provider_invoice_id=invoice_id,
            )
            org = invoice.organisation
            updates = {'billing_mode': Organisation.BILLING_PAST_DUE}
            # Clerk-set past_due is stickier: don't relabel it, or invoice.paid
            # would clear it while the subscription fee is still unpaid.
            if org.billing_mode != Organisation.BILLING_PAST_DUE:
                updates['past_due_source'] = Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE
            Organisation.objects.filter(pk=org.pk).update(**updates)
            logger.warning(
                'Invoice payment failed for org %s (invoice %s) — set to past_due',
                org.clerk_org_id, invoice_id,
            )
        else:
            logger.warning('invoice.payment_failed: no matching invoice for %s', invoice_id)

    def _handle_invoice_voided(self, invoice_id: str) -> None:
        updated = Invoice.objects.filter(
            provider_invoice_id=invoice_id,
        ).update(status=Invoice.STATUS_VOID)
        if not updated:
            logger.warning('invoice.voided: no matching invoice for %s', invoice_id)

    def _handle_checkout_completed(self, session_data: dict) -> None:
        """Grant purchased credits when a Stripe Checkout Session is completed."""
        session_id = session_data.get('id', '')
        metadata = session_data.get('metadata', {})

        if metadata.get('purchase_type') != 'credit_purchase':
            logger.debug('checkout.session.completed: not a credit purchase, ignoring')
            return

        payment_status = session_data.get('payment_status', '')
        if payment_status != 'paid':
            logger.info('checkout.session.completed: payment_status=%s, skipping', payment_status)
            return

        with db_transaction.atomic():
            try:
                purchase = CreditPurchase.objects.select_for_update().get(
                    stripe_checkout_session_id=session_id,
                )
            except CreditPurchase.DoesNotExist:
                logger.warning('checkout.session.completed: no CreditPurchase for session %s', session_id)
                return

            if purchase.status == CreditPurchase.STATUS_COMPLETED:
                logger.debug('checkout.session.completed: purchase %s already completed', session_id)
                return

            # Defense in depth: the granted amount comes from our own
            # CreditPurchase row, but the session's amount_total must agree —
            # a mismatch means a tampered/foreign payload or a data bug, and
            # granting on it would be minting credits.
            amount_total = session_data.get('amount_total')
            expected_cents = int(purchase.amount * 100)
            if amount_total is not None and int(amount_total) != expected_cents:
                logger.error(
                    'checkout.session.completed: amount_total %s does not match purchase '
                    '%s (%s cents) for session %s — NOT granting credits',
                    amount_total, purchase.pk, expected_cents, session_id,
                )
                return

            org = purchase.organisation
            grant_tx = grant_credits(
                org, purchase.amount, f'Credit purchase: ${purchase.amount}',
            )

            purchase.status = CreditPurchase.STATUS_COMPLETED
            purchase.completed_at = timezone.now()
            purchase.credit_transaction = grant_tx
            purchase.save()

            # Link Stripe customer if org doesn't have one yet
            customer_id = session_data.get('customer')
            if customer_id and not org.billing_customer_id:
                org.billing_customer_id = customer_id
                org.save(update_fields=['billing_customer_id'])
                logger.info('Linked Stripe customer %s to org %s from checkout', customer_id, org.clerk_org_id)

        logger.info(
            'Credit purchase completed: $%s for org %s (session %s)',
            purchase.amount, org.clerk_org_id, session_id,
        )

    def _handle_checkout_expired(self, session_data: dict) -> None:
        """Mark CreditPurchase as expired when the checkout session expires."""
        session_id = session_data.get('id', '')
        metadata = session_data.get('metadata', {})

        if metadata.get('purchase_type') != 'credit_purchase':
            return

        updated = CreditPurchase.objects.filter(
            stripe_checkout_session_id=session_id,
            status=CreditPurchase.STATUS_PENDING,
        ).update(status=CreditPurchase.STATUS_EXPIRED)

        if updated:
            logger.info('Credit purchase expired: session %s', session_id)
        else:
            logger.debug('checkout.session.expired: no pending CreditPurchase for session %s', session_id)
