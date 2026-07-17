"""
Tests for Django models.

Tests the framework models:
- User, Organisation, OrganisationMembership
- Config
- CreditTransaction

Focuses on:
- Model creation with valid data
- Constraints (unique, foreign keys)
- Relationships (FKs, reverse relations)
- Model methods (__str__)
- Inheritance (TenantModel, AuditMixin)
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError

from app.models import CreditTransaction
from tests.factories import (
    ConfigFactory,
    OrganisationFactory,
    OrganisationMembershipFactory,
    UserFactory,
)


# ============================================================================
# User Model Tests
# ============================================================================

@pytest.mark.django_db
class TestUserModel:
    """Tests for User model."""

    def test_create_user(self):
        """User created with valid data."""
        user = UserFactory()
        assert user.clerk_id is not None
        assert user.email is not None
        assert user.first_name is not None
        assert user.last_name is not None

    def test_clerk_id_unique(self):
        """clerk_id must be unique."""
        UserFactory(clerk_id='user_123')
        with pytest.raises(IntegrityError):
            UserFactory(clerk_id='user_123')

    def test_user_str(self):
        """__str__ returns clerk_id."""
        user = UserFactory(clerk_id='user_123', email='test@example.com')
        assert str(user) == 'user_123'


# ============================================================================
# Organisation Model Tests
# ============================================================================

@pytest.mark.django_db
class TestOrganisationModel:
    """Tests for Organisation model."""

    def test_create_organisation(self):
        """Organisation created with valid data."""
        org = OrganisationFactory()
        assert org.clerk_org_id is not None
        assert org.name is not None
        assert org.slug is not None

    def test_clerk_org_id_unique(self):
        """clerk_org_id must be unique."""
        OrganisationFactory(clerk_org_id='org_123')
        with pytest.raises(IntegrityError):
            OrganisationFactory(clerk_org_id='org_123')

    def test_slug_allows_duplicates(self):
        """slug is not unique, duplicates are allowed."""
        org1 = OrganisationFactory(slug='test-org')
        org2 = OrganisationFactory(slug='test-org')  # Should not raise
        assert org1.slug == org2.slug

    def test_organisation_str(self):
        """__str__ returns name."""
        org = OrganisationFactory(name='Test Company')
        assert str(org) == 'Test Company'

    def test_billing_defaults(self):
        """New orgs start prepaid with a zero balance."""
        org = OrganisationFactory()
        assert org.billing_mode == org.BILLING_PREPAID
        assert org.credit_balance == Decimal('0.00')
        assert org.billing_customer_id is None


# ============================================================================
# OrganisationMembership Model Tests
# ============================================================================

@pytest.mark.django_db
class TestOrganisationMembershipModel:
    """Tests for OrganisationMembership model."""

    def test_create_membership(self):
        """Membership created with user and org."""
        membership = OrganisationMembershipFactory()
        assert membership.user is not None
        assert membership.organisation is not None
        assert membership.role in ['member', 'admin']

    def test_user_org_unique_together(self):
        """User can only have one membership per organisation."""
        user = UserFactory()
        org = OrganisationFactory()
        OrganisationMembershipFactory(user=user, organisation=org)

        with pytest.raises(IntegrityError):
            OrganisationMembershipFactory(user=user, organisation=org)

    def test_user_multiple_orgs(self):
        """User can be member of multiple organisations."""
        user = UserFactory()
        org1 = OrganisationFactory()
        org2 = OrganisationFactory()

        m1 = OrganisationMembershipFactory(user=user, organisation=org1)
        m2 = OrganisationMembershipFactory(user=user, organisation=org2)

        assert m1.organisation != m2.organisation

    def test_membership_str(self):
        """__str__ returns user clerk_id, org name, and role."""
        user = UserFactory(clerk_id='user_123')
        org = OrganisationFactory(name='Test Org')
        membership = OrganisationMembershipFactory(
            user=user,
            organisation=org,
            role='admin'
        )
        assert str(membership) == 'user_123 - Test Org (admin)'


# ============================================================================
# Config Model Tests
# ============================================================================

@pytest.mark.django_db
class TestConfigModel:
    """Tests for Config model."""

    def test_create_config(self):
        """Config created with name and value."""
        config = ConfigFactory()
        assert config.organisation is not None
        assert config.name is not None
        assert config.value is not None

    def test_name_unique_per_org(self):
        """Config name must be unique within organisation."""
        from django.db import transaction

        org = OrganisationFactory()
        ConfigFactory(organisation=org, name='monthly_limit')

        with transaction.atomic():
            with pytest.raises(IntegrityError):
                ConfigFactory(organisation=org, name='monthly_limit')

        # But allowed in different org
        other_org = OrganisationFactory()
        config2 = ConfigFactory(organisation=other_org, name='monthly_limit')
        assert config2.name == 'monthly_limit'

    def test_config_str(self):
        """__str__ returns '{name}: {value}' truncated at 50 chars."""
        config = ConfigFactory(name='monthly_limit', value='100')
        assert str(config) == 'monthly_limit: 100'
        # Test with longer value (truncated at 50 chars)
        long_value = 'a' * 100
        config2 = ConfigFactory(name='long_config', value=long_value)
        assert str(config2) == f'long_config: {long_value[:50]}'


# ============================================================================
# CreditTransaction Model Tests
# ============================================================================

@pytest.mark.django_db
class TestCreditTransactionModel:
    """Tests for the CreditTransaction ledger model."""

    def _make_tx(self, org, **kwargs):
        defaults = dict(
            organisation=org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('0.10'),
            balance_after=Decimal('0.00'),
            description='usage',
        )
        defaults.update(kwargs)
        return CreditTransaction.objects.create(**defaults)

    def test_create_transaction(self):
        """CreditTransaction created with required fields."""
        org = OrganisationFactory()
        tx = self._make_tx(org)
        assert tx.pk is not None
        assert tx.usage_type is None
        assert tx.reference is None
        assert tx.refunded_transaction is None

    def test_usage_type_and_reference_are_free_form(self):
        """usage_type and reference accept arbitrary strings (no FK coupling)."""
        org = OrganisationFactory()
        tx = self._make_tx(org, usage_type='api_call', reference='order:1234')
        tx.refresh_from_db()
        assert tx.usage_type == 'api_call'
        assert tx.reference == 'order:1234'

    def test_refunded_transaction_one_to_one(self):
        """A charge can be linked by at most one refund (DB-level refund-once)."""
        from django.db import transaction

        org = OrganisationFactory()
        charge = self._make_tx(org, transaction_type=CreditTransaction.DEDUCT)
        self._make_tx(
            org,
            transaction_type=CreditTransaction.REFUND,
            refunded_transaction=charge,
        )

        with transaction.atomic():
            with pytest.raises(IntegrityError):
                self._make_tx(
                    org,
                    transaction_type=CreditTransaction.REFUND,
                    refunded_transaction=charge,
                )

    def test_reverse_refund_relation(self):
        """The refund row is reachable from the charge via .refund."""
        org = OrganisationFactory()
        charge = self._make_tx(org, transaction_type=CreditTransaction.DEDUCT)
        refund = self._make_tx(
            org,
            transaction_type=CreditTransaction.REFUND,
            refunded_transaction=charge,
        )
        charge.refresh_from_db()
        assert charge.refund == refund

    def test_transaction_str(self):
        """__str__ includes type, amount and org."""
        org = OrganisationFactory(name='Test Co')
        tx = self._make_tx(org, transaction_type=CreditTransaction.GRANT, amount=Decimal('5.00'))
        assert str(tx) == f'grant $5.00 for {org}'
