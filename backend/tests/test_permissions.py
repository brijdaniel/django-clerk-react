"""
Tests for custom permission classes.

Tests:
- IsOrgMember: Requires request.org to be set
- IsOrgAdmin: Requires org_role='admin'
- HasOrgPermission: Checks org_permissions for specific perms
"""

import pytest
from rest_framework.test import APIRequestFactory

from app.permissions import HasOrgPermission, IsOrgAdmin, IsOrgMember
from tests.factories import OrganisationFactory, UserFactory


@pytest.fixture
def rf():
    """Request factory fixture."""
    return APIRequestFactory()


# ============================================================================
# IsOrgMember Permission Tests
# ============================================================================

class TestIsOrgMember:
    """Tests for IsOrgMember permission."""

    def test_denies_without_org(self, rf):
        """Request without org denied."""
        request = rf.get('/')
        request.org = None
        request.user = UserFactory.build()

        permission = IsOrgMember()
        assert not permission.has_permission(request, None)

    def test_allows_with_org(self, rf):
        """Request with org allowed."""
        request = rf.get('/')
        request.org = OrganisationFactory.build()
        request.user = UserFactory.build()

        permission = IsOrgMember()
        assert permission.has_permission(request, None)


# ============================================================================
# IsOrgAdmin Permission Tests
# ============================================================================

class TestIsOrgAdmin:
    """Tests for IsOrgAdmin permission."""

    def test_denies_member(self, rf):
        """Member role denied."""
        request = rf.get('/')
        request.org = OrganisationFactory.build()
        request.org_role = 'member'
        request.user = UserFactory.build()

        permission = IsOrgAdmin()
        assert not permission.has_permission(request, None)

    def test_allows_admin(self, rf):
        """Admin role allowed."""
        request = rf.get('/')
        request.org = OrganisationFactory.build()
        request.org_role = 'admin'
        request.user = UserFactory.build()

        permission = IsOrgAdmin()
        assert permission.has_permission(request, None)

    def test_denies_without_org_role(self, rf):
        """Request without org_role denied."""
        request = rf.get('/')
        request.org = OrganisationFactory.build()
        request.user = UserFactory.build()

        permission = IsOrgAdmin()
        assert not permission.has_permission(request, None)


# ============================================================================
# HasOrgPermission Permission Tests
# ============================================================================

class TestHasOrgPermission:
    """Tests for HasOrgPermission permission."""

    def test_checks_method_permissions(self, rf):
        """Permission checked per HTTP method."""
        request = rf.post('/')
        request.org = OrganisationFactory.build()
        request.org_permissions = ['items:read']
        request.user = UserFactory.build()

        # Create mock view with required_permissions
        view = type('MockView', (), {'required_permissions': {'POST': ['items:write']}})()

        permission = HasOrgPermission()
        assert not permission.has_permission(request, view)

    def test_allows_with_wildcard(self, rf):
        """Wildcard permission (*) allows all."""
        request = rf.post('/')
        request.org = OrganisationFactory.build()
        request.org_permissions = ['*']
        request.user = UserFactory.build()

        view = type('MockView', (), {'required_permissions': {'POST': ['items:write']}})()

        permission = HasOrgPermission()
        assert permission.has_permission(request, view)

    def test_allows_with_exact_permission(self, rf):
        """Exact permission match allows."""
        request = rf.post('/')
        request.org = OrganisationFactory.build()
        request.org_permissions = ['items:write', 'items:read']
        request.user = UserFactory.build()

        view = type('MockView', (), {'required_permissions': {'POST': ['items:write']}})()

        permission = HasOrgPermission()
        assert permission.has_permission(request, view)

    def test_denies_without_permission(self, rf):
        """Missing permission denies."""
        request = rf.delete('/')
        request.org = OrganisationFactory.build()
        request.org_permissions = ['items:read']
        request.user = UserFactory.build()

        view = type('MockView', (), {'required_permissions': {'DELETE': ['items:delete']}})()

        permission = HasOrgPermission()
        assert not permission.has_permission(request, view)

    def test_allows_when_no_required_permissions(self, rf):
        """View with no required_permissions allows access."""
        request = rf.get('/')
        request.org = OrganisationFactory.build()
        request.org_permissions = []
        request.user = UserFactory.build()

        view = type('MockView', (), {})()  # No required_permissions attribute

        permission = HasOrgPermission()
        assert permission.has_permission(request, view)

    def test_denies_method_not_in_dict(self, rf):
        """Method not defined in required_permissions dict denies access."""
        request = rf.delete('/')  # DELETE not in dict below
        request.org = OrganisationFactory.build()
        request.org_permissions = ['items:delete']
        request.user = UserFactory.build()

        view = type('MockView', (), {
            'required_permissions': {
                'GET': ['items:read'],
                'POST': ['items:write'],
                # DELETE not included
            }
        })()

        permission = HasOrgPermission()
        assert not permission.has_permission(request, view)
