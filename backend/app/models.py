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

    clerk_org_id = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    credit_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    billing_mode = models.CharField(max_length=20, choices=BILLING_MODE_CHOICES, default=BILLING_PREPAID)
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


class Contact(TenantModel, AuditMixin):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='contacts')
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50)
    email = models.EmailField(blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    opt_out = models.BooleanField(default=False)

    class Meta:
        db_table = 'contacts'
        unique_together = ('organisation', 'phone')

    def __str__(self):
        return f'{self.first_name} {self.last_name}'


class ContactGroup(TenantModel, AuditMixin):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'contact_groups'

    def __str__(self):
        return self.name


class ContactGroupMember(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    group = models.ForeignKey(ContactGroup, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'contact_group_members'
        unique_together = ('contact', 'group')

    def __str__(self):
        return f'{self.contact} in {self.group}'


class Template(TenantModel, AuditMixin):
    name = models.CharField(max_length=255)
    text = models.TextField()
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'templates'

    def __str__(self):
        return f'{self.name} (v{self.version})'


class ScheduleStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    QUEUED = 'queued', 'Queued'
    PROCESSING = 'processing', 'Processing'
    SENT = 'sent', 'Sent'
    RETRYING = 'retrying', 'Retrying'
    DELIVERED = 'delivered', 'Delivered'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class FailureCategory(models.TextChoices):
    # Transient — worth retrying
    NETWORK_ERROR = 'network_error', 'Network Error'
    PROVIDER_TIMEOUT = 'provider_timeout', 'Provider Timeout'
    RATE_LIMITED = 'rate_limited', 'Rate Limited'
    SERVER_ERROR = 'server_error', 'Server Error'
    UNKNOWN_TRANSIENT = 'unknown_transient', 'Unknown Transient'
    # Permanent — terminal, always refund
    INVALID_NUMBER = 'invalid_number', 'Invalid Number'
    OPT_OUT = 'opt_out', 'Recipient Opted Out'
    BLACKLISTED = 'blacklisted', 'Number Blacklisted'
    UNROUTABLE = 'unroutable', 'Unroutable Number'
    CONTENT_REJECTED = 'content_rejected', 'Content Rejected'
    ACCOUNT_ERROR = 'account_error', 'Provider Account Error'
    UNKNOWN_PERMANENT = 'unknown_permanent', 'Unknown Permanent'


class MessageFormat(models.TextChoices):
    SMS = 'sms', 'SMS'
    MMS = 'mms', 'MMS'


class Schedule(TenantModel, AuditMixin):
    name = models.CharField(max_length=255, blank=True, null=True)
    template = models.ForeignKey(Template, on_delete=models.SET_NULL, null=True, blank=True)
    text = models.TextField(blank=True, null=True)
    message_parts = models.PositiveIntegerField(default=1)
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    group = models.ForeignKey(ContactGroup, on_delete=models.SET_NULL, null=True, blank=True)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    scheduled_time = models.DateTimeField()
    sent_time = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=ScheduleStatus.choices, default=ScheduleStatus.PENDING)
    error = models.TextField(blank=True, null=True)
    format = models.CharField(max_length=10, choices=MessageFormat.choices, blank=True, null=True)
    media_url = models.URLField(blank=True, null=True)
    subject = models.CharField(max_length=64, blank=True, null=True)
    alphanumeric_sender = models.CharField(max_length=11, blank=True, null=True)
    # Retry / delivery tracking fields
    provider_message_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    max_retries = models.PositiveSmallIntegerField(default=3)
    next_retry_at = models.DateTimeField(blank=True, null=True, db_index=True)
    failure_category = models.CharField(
        max_length=40, choices=FailureCategory.choices, blank=True, null=True
    )
    delivered_time = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'schedules'
        indexes = [
            models.Index(fields=['scheduled_time']),
            models.Index(fields=['contact']),
            models.Index(fields=['scheduled_time', 'status']),
            models.Index(fields=['contact', 'status', '-scheduled_time'], name='schedule_contact_status_desc'),
            models.Index(fields=['status', 'scheduled_time'], name='schedule_status_time_idx'),
        ]

    def __str__(self):
        return f'Schedule {self.pk} - {self.status}'


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
    format = models.CharField(max_length=50, null=True, blank=True)
    schedule = models.ForeignKey(
        Schedule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='credit_transactions'
    )
    unit_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = 'credit_transactions'
        indexes = [models.Index(fields=['organisation', '-created_at'])]

    def __str__(self):
        return f'{self.transaction_type} ${self.amount} for {self.organisation}'


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
