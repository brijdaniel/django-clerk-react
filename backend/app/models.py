from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """AbstractUser inherits some fields that are not required when using Clerk.
    
    However using AbstractUser is simple and allows for django admin panel, etc
    """
    clerk_id = models.CharField(max_length=255, unique=True, db_index=True)
    username = models.CharField(max_length=150, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    USERNAME_FIELD = 'clerk_id'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.clerk_id


class Organisation(models.Model):
    BILLING_PREPAID = 'prepaid'
    BILLING_SUBSCRIBED = 'subscribed'
    BILLING_PAST_DUE = 'past_due'
    BILLING_MODE_CHOICES = [
        (BILLING_PREPAID, 'Prepaid'),
        (BILLING_SUBSCRIBED, 'Subscribed'),
        (BILLING_PAST_DUE, 'Past Due'),
    ]

    # Who put the org into past_due: the Clerk subscription fee or a Stripe
    # metered invoice. Each source may only be cleared by its own "paid" signal —
    # an invoice.paid webhook must not un-block an org whose Clerk subscription
    # fee is still unpaid, and vice versa.
    PAST_DUE_SOURCE_CLERK = 'clerk'
    PAST_DUE_SOURCE_STRIPE_INVOICE = 'stripe_invoice'
    PAST_DUE_SOURCE_CHOICES = [
        (PAST_DUE_SOURCE_CLERK, 'Clerk subscription'),
        (PAST_DUE_SOURCE_STRIPE_INVOICE, 'Stripe invoice'),
    ]

    clerk_org_id = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    credit_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    billing_mode = models.CharField(max_length=20, choices=BILLING_MODE_CHOICES, default=BILLING_PREPAID)
    past_due_source = models.CharField(
        max_length=20, choices=PAST_DUE_SOURCE_CHOICES, null=True, blank=True,
    )
    # updated_at of the last applied Clerk billing event. Svix delivers
    # unordered, so a delayed subscription.updated(active) could otherwise
    # overwrite a newer past_due state; events older than this are skipped.
    billing_event_at = models.DateTimeField(null=True, blank=True)
    billing_customer_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)

    class Meta:
        db_table = 'organisations'

    def __str__(self):
        return self.name


class AuditMixin(models.Model):
    """Automatically add these fields for audit traceability"""
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='%(class)s_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='%(class)s_updated')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OrganisationMembership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    role = models.CharField(max_length=50, default='member')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'organisation_memberships'
        unique_together = ('user', 'organisation')

    def __str__(self):
        return f'{self.user.clerk_id} - {self.organisation.name} ({self.role})'


class TenantModel(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)

    class Meta:
        abstract = True


class Config(TenantModel):
    name = models.CharField(max_length=255)
    value = models.TextField()

    class Meta:
        db_table = 'configs'
        unique_together = ('organisation', 'name')
        indexes = [models.Index(fields=['name']),]

    def __str__(self):
        return f'{self.name}: {self.value[:50]}'


class CreditTransaction(TenantModel, AuditMixin):
    GRANT = 'grant'
    DEDUCT = 'deduct'
    USAGE = 'usage'
    REFUND = 'refund'
    TYPE_CHOICES = [
        (GRANT, 'Grant'),
        (DEDUCT, 'Deduct'),
        (USAGE, 'Usage'),
        (REFUND, 'Refund'),
    ]

    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=255)
    # Free-form usage category ('api_call', 'report', ...) — new usage types
    # need no schema changes, only a rate in settings.USAGE_RATES or a per-org
    # Config('<usage_type>_rate') override.
    usage_type = models.CharField(max_length=50, null=True, blank=True)
    # Free-form correlation key linking a charge to the domain object it paid
    # for (e.g. 'order:1234'). refund_usage() reverses the most recent
    # unrefunded charge with a given reference.
    reference = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    unit_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    # For REFUND rows: the DEDUCT/USAGE charge this refund reverses. The one-to-one
    # constraint guarantees each charge is refunded at most once at the DB level,
    # while still allowing a reference that is re-charged on retry to be
    # refunded again if the retry also fails.
    refunded_transaction = models.OneToOneField(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='refund',
    )

    class Meta:
        db_table = 'credit_transactions'
        indexes = [models.Index(fields=['organisation', '-created_at'])]

    def __str__(self):
        return f'{self.transaction_type} ${self.amount} for {self.organisation}'


class WebhookEvent(models.Model):
    """Processed webhook event ids, for replay/duplicate suppression.

    Inserted in the same transaction as the event's side effects: a failed
    handler rolls the row back (so provider retries reprocess), while a
    concurrent or replayed delivery hits the unique constraint and is skipped.
    """
    PROVIDER_CLERK = 'clerk'
    PROVIDER_STRIPE = 'stripe'

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=100, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'webhook_events'
        constraints = [
            models.UniqueConstraint(fields=['provider', 'event_id'], name='uniq_webhook_provider_event'),
        ]

    def __str__(self):
        return f'{self.provider}:{self.event_id}'


class Invoice(TenantModel, AuditMixin):
    STATUS_DRAFT = 'draft'
    STATUS_OPEN = 'open'
    STATUS_PAID = 'paid'
    STATUS_VOID = 'void'
    STATUS_UNCOLLECTABLE = 'uncollectable'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_OPEN, 'Open'),
        (STATUS_PAID, 'Paid'),
        (STATUS_VOID, 'Void'),
        (STATUS_UNCOLLECTABLE, 'Uncollectable'),
    ]

    provider_invoice_id = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    invoice_url = models.URLField(max_length=500, blank=True, null=True)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()

    class Meta:
        db_table = 'invoices'
        indexes = [models.Index(fields=['organisation', '-period_start'])]
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'period_start'],
                condition=~models.Q(status__in=['void']),
                name='unique_org_period_active_invoice',
            )
        ]

    def __str__(self):
        return f'Invoice {self.provider_invoice_id} ({self.status}) for {self.organisation}'


class CreditPurchase(TenantModel, AuditMixin):
    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    stripe_checkout_session_id = models.CharField(max_length=255, unique=True, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    completed_at = models.DateTimeField(null=True, blank=True)
    credit_transaction = models.ForeignKey(
        CreditTransaction, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='credit_purchase',
    )

    class Meta:
        db_table = 'credit_purchases'
        indexes = [models.Index(fields=['organisation', '-created_at'])]

    def __str__(self):
        return f'CreditPurchase ${self.amount} ({self.status}) for {self.organisation}'
