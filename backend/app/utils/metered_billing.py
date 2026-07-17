"""
Metered billing provider abstraction.

Provides an ABC for metered billing providers (Stripe, etc.) and a factory
function to instantiate the configured provider. Follows the same pattern
as StorageProvider in storage.py.

The provider handles:
  - Looking up billing customers created by Clerk in the payment gateway
  - Creating invoices with calculated line items (amounts come from CreditTransaction)
  - Voiding invoices
  - Parsing payment gateway webhooks
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, cast

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InvoiceLineItem:
    """A single line item on an invoice."""
    description: str       # e.g. "api_call usage: 150 units @ $0.05"
    amount: Decimal        # Total dollar amount for this line
    quantity: int          # Number of units
    unit_amount: Decimal   # Per-unit rate
    usage_type: str | None = None  # Usage category this line aggregates (e.g. 'api_call')


@dataclass
class InvoiceResult:
    """Result of an invoice operation."""
    success: bool
    invoice_id: str | None = None
    invoice_url: str | None = None
    status: str | None = None
    error: str | None = None


@dataclass
class PdfResult:
    """Result of fetching an invoice PDF."""
    success: bool
    content: bytes | None = None
    filename: str | None = None
    error: str | None = None


@dataclass
class CustomerResult:
    """Result of a customer lookup or creation."""
    success: bool
    customer_id: str | None = None
    error: str | None = None


@dataclass
class CheckoutResult:
    """Result of creating a checkout session for credit purchase."""
    success: bool
    session_id: str | None = None
    checkout_url: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class MeteredBillingProvider(ABC):
    """Abstract base class for metered billing providers.

    Concrete implementations handle the specifics of interacting with a
    payment gateway (e.g. Stripe). The ABC defines the interface that the
    rest of the application uses, so swapping providers requires no changes
    outside the provider module.
    """

    @abstractmethod
    def find_customer_by_org(self, org_id: str) -> CustomerResult:
        """Find an existing billing customer by organisation ID.

        For Stripe, this searches by metadata.organization_id which Clerk
        sets when creating the Stripe Customer during subscription signup.
        """

    def create_customer(
        self,
        org_id: str,
        name: str,
        metadata: dict | None = None,
    ) -> CustomerResult:
        """Create a billing customer. Optional — not all providers need this.

        In the normal flow, Clerk creates the customer during subscription
        signup, so this method is a placeholder.
        """
        raise NotImplementedError

    @abstractmethod
    def create_invoice(
        self,
        customer_id: str,
        line_items: list[InvoiceLineItem],
        period_start: datetime,
        period_end: datetime,
        auto_send: bool = True,
    ) -> InvoiceResult:
        """Create an invoice with the given line items.

        If auto_send is True, finalise and send the invoice immediately.
        """

    @abstractmethod
    def get_invoice(self, invoice_id: str) -> InvoiceResult:
        """Fetch current status of an invoice."""

    @abstractmethod
    def void_invoice(self, invoice_id: str) -> InvoiceResult:
        """Void/cancel an unpaid invoice."""

    @abstractmethod
    def get_invoice_pdf(self, invoice_id: str) -> PdfResult:
        """Fetch the raw PDF bytes for an invoice.

        Returns PdfResult with content (bytes) and filename on success.
        Concrete implementations handle fetching from whatever backing store
        the provider uses (e.g. Stripe hosted PDF, Azure blob, etc.).
        """

    @abstractmethod
    def create_checkout_session(
        self,
        customer_id: str | None,
        amount: Decimal,
        org_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        """Create a checkout session for a one-time credit purchase."""

    def parse_webhook(self, payload: bytes, signature: str) -> dict:
        """Parse and verify a webhook payload. Override per provider."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Mock provider (development / testing)
# ---------------------------------------------------------------------------

class MockMeteredBillingProvider(MeteredBillingProvider):
    """Mock provider that logs calls and returns success stubs."""

    _counter: int = 0

    def __init__(self, **kwargs):
        pass  # Accept and ignore any config kwargs

    def find_customer_by_org(self, org_id: str) -> CustomerResult:
        logger.info('MockMeteredBillingProvider.find_customer_by_org(%s)', org_id)
        return CustomerResult(
            success=True,
            customer_id=f'mock_cus_{org_id}',
        )

    def create_invoice(
        self,
        customer_id: str,
        line_items: list[InvoiceLineItem],
        period_start: datetime,
        period_end: datetime,
        auto_send: bool = True,
    ) -> InvoiceResult:
        MockMeteredBillingProvider._counter += 1
        invoice_id = f'mock_inv_{MockMeteredBillingProvider._counter}'
        total = sum(item.amount for item in line_items)
        logger.info(
            'MockMeteredBillingProvider.create_invoice(customer=%s, total=$%s, items=%d)',
            customer_id, total, len(line_items),
        )
        return InvoiceResult(
            success=True,
            invoice_id=invoice_id,
            invoice_url=f'https://mock-billing.example.com/invoices/{invoice_id}',
            status='open',
        )

    def get_invoice(self, invoice_id: str) -> InvoiceResult:
        logger.info('MockMeteredBillingProvider.get_invoice(%s)', invoice_id)
        return InvoiceResult(
            success=True,
            invoice_id=invoice_id,
            status='open',
        )

    def void_invoice(self, invoice_id: str) -> InvoiceResult:
        logger.info('MockMeteredBillingProvider.void_invoice(%s)', invoice_id)
        return InvoiceResult(
            success=True,
            invoice_id=invoice_id,
            status='void',
        )

    def get_invoice_pdf(self, invoice_id: str) -> PdfResult:
        logger.info('MockMeteredBillingProvider.get_invoice_pdf(%s)', invoice_id)
        # Minimal valid PDF for testing
        pdf_content = (
            b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
            b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
            b'3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n'
            b'xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF'
        )
        return PdfResult(
            success=True,
            content=pdf_content,
            filename=f'invoice-{invoice_id}.pdf',
        )

    def create_checkout_session(
        self,
        customer_id: str | None,
        amount: Decimal,
        org_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        MockMeteredBillingProvider._counter += 1
        session_id = f'mock_cs_{MockMeteredBillingProvider._counter}'
        logger.info(
            'MockMeteredBillingProvider.create_checkout_session(customer=%s, amount=$%s, org=%s)',
            customer_id, amount, org_id,
        )
        return CheckoutResult(
            success=True,
            session_id=session_id,
            checkout_url=f'https://mock-checkout.example.com/sessions/{session_id}',
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class _BillingProviderCache:
    """Simple cache for the billing provider singleton."""
    instance: Optional[MeteredBillingProvider] = None


def get_billing_provider() -> MeteredBillingProvider:
    """Get the configured metered billing provider instance (singleton).

    Provider class is determined by settings.METERED_BILLING_PROVIDER_CLASS.
    Configuration is passed from settings.METERED_BILLING_PROVIDER_CONFIG.
    Instance is cached in _BillingProviderCache.
    """
    if _BillingProviderCache.instance is None:
        provider_path = getattr(
            settings,
            'METERED_BILLING_PROVIDER_CLASS',
            'app.utils.metered_billing.MockMeteredBillingProvider',
        )

        # Import the provider class
        module_path, class_name = provider_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)

        # Get provider configuration
        config = getattr(settings, 'METERED_BILLING_PROVIDER_CONFIG', {})

        # Instantiate with config
        _BillingProviderCache.instance = provider_class(**config)
        logger.info('Initialised metered billing provider: %s', provider_path)

    return cast(MeteredBillingProvider, _BillingProviderCache.instance)
