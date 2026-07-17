"""
Tests for Django REST Framework serializers.

Covers the framework serializers:
- ConfigSerializer (validation, required fields)
- CreditTransactionSerializer (read-only ledger representation)
- OrganisationSerializer / UserSerializer (field exposure)
"""

from decimal import Decimal

import pytest

from app.serializers import (
    ConfigSerializer,
    CreditTransactionSerializer,
    OrganisationSerializer,
    UserSerializer,
)
from app.models import CreditTransaction
from tests.factories import OrganisationFactory, UserFactory


# ============================================================================
# Config Serializer Tests
# ============================================================================

@pytest.mark.django_db
class TestConfigSerializer:
    """Tests for ConfigSerializer."""

    def test_valid_config_data(self):
        """Valid config data passes validation."""
        data = {
            'name': 'monthly_limit',
            'value': '100'
        }
        serializer = ConfigSerializer(data=data)
        assert serializer.is_valid()

    def test_name_required(self):
        """Name is required."""
        data = {'value': '100'}
        serializer = ConfigSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_value_required(self):
        """Value is required."""
        data = {'name': 'test'}
        serializer = ConfigSerializer(data=data)
        assert not serializer.is_valid()
        assert 'value' in serializer.errors


# ============================================================================
# CreditTransaction Serializer Tests
# ============================================================================

@pytest.mark.django_db
class TestCreditTransactionSerializer:
    """Tests for CreditTransactionSerializer (read-only ledger rows)."""

    def test_serializes_ledger_fields(self):
        org = OrganisationFactory()
        user = UserFactory()
        tx = CreditTransaction.objects.create(
            organisation=org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('0.10'),
            balance_after=Decimal('9.90'),
            description='API usage',
            usage_type='api_call',
            reference='order:1234',
            created_by=user,
        )

        data = CreditTransactionSerializer(tx).data

        assert data['transaction_type'] == 'usage'
        assert data['amount'] == '0.10'
        assert data['balance_after'] == '9.90'
        assert data['description'] == 'API usage'
        assert data['usage_type'] == 'api_call'
        assert data['reference'] == 'order:1234'
        assert data['created_by'] == user.pk
        assert 'created_at' in data

    def test_all_fields_read_only(self):
        """The ledger is append-only via billing utils — the API never writes it."""
        serializer = CreditTransactionSerializer(data={
            'transaction_type': 'grant',
            'amount': '5.00',
            'balance_after': '5.00',
            'description': 'sneaky grant',
        })
        assert serializer.is_valid()
        # Every field is read-only, so nothing survives validation.
        assert serializer.validated_data == {}


# ============================================================================
# Organisation / User Serializer Tests
# ============================================================================

@pytest.mark.django_db
class TestOrganisationSerializer:
    def test_exposes_public_fields_only(self):
        org = OrganisationFactory(name='Acme', slug='acme')
        data = OrganisationSerializer(org).data
        assert set(data.keys()) == {'clerk_org_id', 'name', 'slug'}


@pytest.mark.django_db
class TestUserSerializer:
    def test_serializes_user(self):
        user = UserFactory(first_name='Jane', last_name='Doe')
        data = UserSerializer(user).data
        assert data['first_name'] == 'Jane'
        assert data['last_name'] == 'Doe'
        assert data['clerk_id'] == user.clerk_id
        # Annotated fields fall back to defaults when not annotated.
        assert data['role'] == 'member'
        assert data['is_active'] is True
