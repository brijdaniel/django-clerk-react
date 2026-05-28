import re

from django.utils import timezone
from rest_framework import serializers

from app.models import *


# Reusable validators
def validate_phone_number(value):
    """Validate and normalize Australian mobile number (04XXXXXXXX or +614XXXXXXXX)."""
    cleaned = re.sub(r'\s+', '', value)
    if cleaned.startswith('+614'):
        cleaned = '0' + cleaned[3:]
    if not re.match(r'^04\d{8}$', cleaned):
        raise serializers.ValidationError(
            'Phone must be an Australian mobile number (04XXXXXXXX or +614XXXXXXXX).'
        )
    return cleaned


ALPHANUMERIC_SENDER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ]{1,9}[A-Za-z0-9]$')


def validate_alphanumeric_sender(value):
    """Validate alphanumeric sender ID: 3-11 chars, alphanumeric + interior spaces."""
    if not value:
        return value
    value = value.strip()
    if not ALPHANUMERIC_SENDER_RE.match(value):
        raise serializers.ValidationError(
            'Alphanumeric sender must be 3-11 characters, alphanumeric and spaces only, '
            'cannot start or end with a space.'
        )
    return value


def validate_sms_message(value, allow_empty=False):
    """Validate and clean SMS/MMS message text."""
    cleaned = value.strip()
    cleaned = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]', '', cleaned)
    if not allow_empty and not cleaned:
        raise serializers.ValidationError('Message cannot be empty after cleaning.')
    return cleaned


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ['clerk_org_id', 'name', 'slug']


class UserSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source='_membership_role', default='member', read_only=True)
    organisation = serializers.CharField(source='_org_name', default='', read_only=True)
    is_active = serializers.BooleanField(source='_is_active', default=True, read_only=True)

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'clerk_id', 'role', 'organisation', 'is_active', 'created_at', 'updated_at']


class MeSerializer(serializers.Serializer):
    user = UserSerializer(source='*')
    organisation = serializers.SerializerMethodField()

    def get_organisation(self, obj):
        request = self.context['request']
        org = getattr(request, 'org', None)
        if not org:
            return None
        data = OrganisationSerializer(org).data
        data['role'] = request.org_role
        data['permissions'] = request.org_permissions
        return data


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            'id', 'first_name', 'last_name', 'phone', 'email', 'company',
            'is_active', 'opt_out', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_phone(self, value):
        return validate_phone_number(value)

    def validate_first_name(self, value):
        return value.strip()[:100]

    def validate_last_name(self, value):
        return value.strip()[:100]


class ContactGroupSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True, default=0)
    member_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        default=list,
        write_only=True,
    )

    class Meta:
        model = ContactGroup
        fields = [
            'id', 'name', 'description', 'is_active',
            'member_count', 'member_ids', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_name(self, value):
        v = value.strip()
        if len(v) < 2:
            raise serializers.ValidationError('Name must be at least 2 characters.')
        return v[:100]

    def validate_description(self, value):
        if value:
            return value.strip()[:500]
        return value

    def create(self, validated_data):
        """Create ContactGroup and optionally add members."""
        member_ids = validated_data.pop('member_ids', [])
        group = ContactGroup.objects.create(**validated_data)

        # Add members if provided
        if member_ids:
            from app.models import Contact, ContactGroupMember
            request = self.context.get('request')
            org = request.organisation if request else None

            for contact_id in member_ids:
                contact = Contact.objects.filter(id=contact_id, organisation=org).first()
                if contact:
                    ContactGroupMember.objects.create(group=group, contact=contact)

        return group


class GroupMemberActionSerializer(serializers.Serializer):
    contact_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=100,
    )


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = [
            'id', 'name', 'text', 'is_active', 'version',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_name(self, value):
        v = value.strip()
        if len(v) < 1:
            raise serializers.ValidationError('Name is required.')
        return v[:100]

    def validate_text(self, value):
        v = value.strip()
        if len(v) < 1:
            raise serializers.ValidationError('Text is required.')
        if len(v) > 320:
            raise serializers.ValidationError('Text must be at most 320 characters.')
        return v


class ScheduleSerializer(serializers.ModelSerializer):
    contact_detail = ContactSerializer(source='contact', read_only=True)
    group_detail = ContactGroupSerializer(source='group', read_only=True)
    recipient_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Schedule
        fields = [
            'id', 'name', 'template', 'text', 'message_parts',
            'contact', 'contact_detail', 'phone',
            'group', 'group_detail', 'parent', 'recipient_count',
            'scheduled_time', 'sent_time',
            'status', 'error',
            'format', 'media_url', 'subject', 'alphanumeric_sender',
            'provider_message_id', 'retry_count', 'max_retries',
            'next_retry_at', 'failure_category', 'delivered_time',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'sent_time', 'provider_message_id', 'retry_count',
            'next_retry_at', 'failure_category', 'delivered_time',
            'created_at', 'updated_at',
        ]

    def validate_text(self, value):
        if value:
            v = value.strip()
            if len(v) > 306:
                raise serializers.ValidationError('Text must be at most 306 characters.')
            return v
        return value

    def validate_alphanumeric_sender(self, value):
        return validate_alphanumeric_sender(value) if value else value

    def validate_scheduled_time(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError('Scheduled time must be in the future.')
        return value

    def validate(self, attrs):
        if self.instance and self.instance.status != ScheduleStatus.PENDING:
            raise serializers.ValidationError('Only pending schedules can be updated.')
        return attrs


class GroupScheduleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    template_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    text = serializers.CharField(max_length=306, required=False, allow_null=True, allow_blank=True)
    group_id = serializers.IntegerField(min_value=1)
    scheduled_time = serializers.DateTimeField()
    alphanumeric_sender = serializers.CharField(max_length=11, required=False, allow_blank=True, allow_null=True, default=None)

    def validate_scheduled_time(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError('Scheduled time must be in the future.')
        return value

    def validate_alphanumeric_sender(self, value):
        return validate_alphanumeric_sender(value) if value else value

    def validate(self, attrs):
        has_template = attrs.get('template_id')
        has_text = attrs.get('text') and attrs['text'].strip()
        if not has_template and not has_text:
            raise serializers.ValidationError(
                'Either template_id or text must be provided.'
            )
        return attrs


class GroupScheduleUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    template_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    text = serializers.CharField(max_length=306, required=False, allow_null=True, allow_blank=True)
    scheduled_time = serializers.DateTimeField(required=False)
    status = serializers.ChoiceField(choices=ScheduleStatus.choices, required=False)

    def validate_scheduled_time(self, value):
        if value and value <= timezone.now():
            raise serializers.ValidationError('Scheduled time must be in the future.')
        return value


class ConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = Config
        fields = ['id', 'name', 'value']


class RecipientSerializer(serializers.Serializer):
    phone = serializers.CharField()
    contact_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate_phone(self, value):
        return validate_phone_number(value)


class SendSMSSerializer(serializers.Serializer):
    message = serializers.CharField(min_length=1, max_length=306)
    recipients = serializers.ListField(
        child=RecipientSerializer(), min_length=1, max_length=500,
    )
    alphanumeric_sender = serializers.CharField(max_length=11, required=False, allow_blank=True, allow_null=True, default=None)

    def validate_message(self, value):
        return validate_sms_message(value)

    def validate_alphanumeric_sender(self, value):
        return validate_alphanumeric_sender(value) if value else value


class SendGroupSMSSerializer(serializers.Serializer):
    message = serializers.CharField(min_length=1, max_length=306)
    group_id = serializers.IntegerField(min_value=1)
    alphanumeric_sender = serializers.CharField(max_length=11, required=False, allow_blank=True, allow_null=True, default=None)

    def validate_message(self, value):
        return validate_sms_message(value)

    def validate_alphanumeric_sender(self, value):
        return validate_alphanumeric_sender(value) if value else value


class SendMMSSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=306, allow_blank=True)
    media_url = serializers.URLField()
    recipients = serializers.ListField(
        child=RecipientSerializer(), min_length=1, max_length=500,
    )
    subject = serializers.CharField(max_length=64, required=False, allow_blank=True, allow_null=True)
    alphanumeric_sender = serializers.CharField(max_length=11, required=False, allow_blank=True, allow_null=True, default=None)

    def validate_message(self, value):
        return validate_sms_message(value, allow_empty=True)

    def validate_subject(self, value):
        if value:
            return value.strip()
        return value

    def validate_alphanumeric_sender(self, value):
        return validate_alphanumeric_sender(value) if value else value


class CreditTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditTransaction
        fields = [
            'id', 'transaction_type', 'amount', 'balance_after',
            'description', 'format', 'created_by', 'created_at', 'schedule',
        ]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            'id', 'provider_invoice_id', 'status', 'amount',
            'invoice_url', 'period_start', 'period_end', 'created_at',
        ]
        read_only_fields = fields


class BuyCreditSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=5, max_value=10000)
