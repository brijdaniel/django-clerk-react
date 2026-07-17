from rest_framework import serializers

from app.models import (
    Config,
    CreditTransaction,
    Invoice,
    Organisation,
    User,
)


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


class ConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = Config
        fields = ['id', 'name', 'value']


class CreditTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditTransaction
        fields = [
            'id', 'transaction_type', 'amount', 'balance_after',
            'description', 'usage_type', 'created_by', 'created_at', 'reference',
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
