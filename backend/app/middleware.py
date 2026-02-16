from .models import Organisation


class ClerkTenantMiddleware:
    """For handling multi-tenant data
    
    Extracts organisation data from token and inserts it to the request,
    so that views can access directly. 
        * org_id is used by the`TenantScopedMixin` to auto filter querysets
        * org_role is used by `permissions.py` for RBAC

    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Define default values
        request.org_id = None
        request.org = None
        request.org_role = None
        request.org_permissions = []

        # Middleware runs on every request, so need to check if the auth data exists
        auth_payload = getattr(request, 'auth', None)
        if isinstance(auth_payload, dict):
            # 'o' is where clerk sends the org data
            org_claims = auth_payload.get('o', {})
            if org_claims:
                request.org_id = org_claims.get('id')  # org id
                request.org_role = org_claims.get('rol')  # user role
                per = org_claims.get('per', '')  # user permissions
                request.org_permissions = [
                    p.strip() for p in per.split(',') if p.strip()
                ] if per else []

                if request.org_id:
                    request.org = Organisation.objects.filter(clerk_org_id=request.org_id).first()

        return self.get_response(request)
