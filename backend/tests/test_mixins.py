"""
Tests for mixin classes to achieve 100% coverage.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from rest_framework.exceptions import MethodNotAllowed

from app.mixins import SoftDeleteMixin, TenantScopedMixin
from app.models import Config, CreditTransaction
from tests.factories import OrganisationFactory, UserFactory


@pytest.mark.django_db
class TestSoftDeleteMixin:
    """Test SoftDeleteMixin."""

    def test_perform_destroy_without_is_active_field(self):
        """Raises MethodNotAllowed for models without is_active field."""
        mixin = SoftDeleteMixin()
        mixin.request = Mock()
        mixin.request.user = UserFactory()

        # Create mock instance without is_active attribute
        instance = Mock(spec=[])  # Empty spec = no attributes
        del instance.is_active  # Ensure it doesn't have is_active

        with pytest.raises(MethodNotAllowed) as exc_info:
            mixin.perform_destroy(instance)

        assert 'does not support deletion' in str(exc_info.value.detail)

    def test_perform_destroy_without_updated_by_field(self):
        """Soft delete works on models without updated_by field."""
        mixin = SoftDeleteMixin()
        mixin.request = Mock()
        mixin.request.user = UserFactory()

        # Create mock instance with is_active but no updated_by
        instance = Mock()
        instance.is_active = True
        instance.updated_by = Mock(side_effect=AttributeError)  # hasattr will return True but accessing raises error

        # Remove updated_by from instance
        delattr(instance, 'updated_by')

        mixin.perform_destroy(instance)

        # Should set is_active=False and call save with just is_active
        assert instance.is_active is False
        instance.save.assert_called_once_with(update_fields=['is_active'])


@pytest.mark.django_db
class TestTenantScopedMixin:
    """Test TenantScopedMixin."""

    def test_get_queryset_without_org_id(self):
        """Returns empty queryset when request has no org_id."""
        # Create a viewset class that uses TenantScopedMixin with a real base
        class FakeBase:
            def get_queryset(self):
                return Config.objects.all()

        class TestViewSet(TenantScopedMixin, FakeBase):
            tenant_org_field = 'organisation'

        viewset = TestViewSet()
        viewset.request = Mock()
        viewset.request.org_id = None  # No org_id

        result = viewset.get_queryset()

        # Should return an empty queryset
        assert result.count() == 0
        assert list(result) == []

    def test_perform_create_fetches_org_from_org_id(self):
        """Creates org from org_id when org not in request."""
        org = OrganisationFactory()
        user = UserFactory()

        mixin = TenantScopedMixin()
        mixin.request = Mock()
        mixin.request.org = None  # No org attribute
        mixin.request.org_id = org.clerk_org_id  # But has org_id
        mixin.request.user = user
        mixin.tenant_org_field = 'organisation'

        # Mock serializer for a model with audit fields (created_by/updated_by)
        serializer = Mock()
        serializer.Meta.model = CreditTransaction

        mixin.perform_create(serializer)

        # Should call save with organisation fetched from org_id
        call_args = serializer.save.call_args
        assert 'organisation' in call_args[1]
        assert call_args[1]['organisation'].clerk_org_id == org.clerk_org_id
        assert call_args[1]['created_by'] == user
        assert call_args[1]['updated_by'] == user
