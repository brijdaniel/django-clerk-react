class ClerkTenantMiddleware:
    """Sets default tenant attributes on every request.

    The actual org extraction from the JWT happens in
    ClerkJWTAuthentication.authenticate(), which runs after this middleware.
    This middleware just ensures the attributes always exist so downstream
    code can safely use getattr() without KeyError.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.org_id = None
        request.org = None
        request.org_role = None
        request.org_permissions = []
        return self.get_response(request)
