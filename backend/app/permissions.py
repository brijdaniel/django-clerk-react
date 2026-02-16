"""The permissions that are checked here come from data set in the JWT, provided by Clerk.

Permissions are created/managed/assigned in the Clerk dashboard.
"""

from rest_framework.permissions import BasePermission


class IsOrgMember(BasePermission):
    """Requires the user to have an active organisation in their JWT."""
    def has_permission(self, request, view):
        return bool(getattr(request, 'org_id', None))


class IsOrgAdmin(BasePermission):
    """Requires the user to have the 'admin' role in their active organisation."""
    def has_permission(self, request, view):
        return getattr(request, 'org_role', None) == 'admin'


class HasOrgPermission(BasePermission):
    """
    Checks that the user has the required organisation permissions.
    Set `required_permissions` on the view as either:

    A list — all permissions required for every method:
        required_permissions = ['invoices:read', 'invoices:export']

    A dict — permissions required per HTTP method (unlisted methods are denied):
        required_permissions = {
            'GET': ['invoices:read'],
            'POST': ['invoices:create'],
            'PUT': ['invoices:update'],
            'PATCH': ['invoices:update'],
            'DELETE': ['invoices:delete'],
        }
    """
    def has_permission(self, request, view):
        required = getattr(view, 'required_permissions', None)
        if not required:
            return True

        # Block any requests if the method is not definde in required_permissions
        if isinstance(required, dict):
            if request.method not in required:
                return False
            required = required[request.method]

        # check that user_permissions contains all the required_permissions
        user_permissions = getattr(request, 'org_permissions', [])
        return all(p in user_permissions for p in required)
