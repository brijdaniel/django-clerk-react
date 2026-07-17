import logging

import jwt
from jwt import PyJWKClient
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import Organisation, User

logger = logging.getLogger('app.auth')


# defined at the module level to utilise the PyJWKClient built in cache
jwks_client = PyJWKClient(f'{settings.CLERK_FRONTEND_API}/.well-known/jwks.json')

class ClerkJWTAuthentication(BaseAuthentication):
    """Reads bearer token, authenticates against Clerk,
    returns User and token payload.
    """
    def authenticate(self, request):
        # Only accepts bearer tokens
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return None

        # Validate against clerk and decode
        token = auth_header.split(' ')[1]
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=['RS256'],
                options={
                    'verify_exp': True,
                    'verify_nbf': True,
                    'verify_iss': True,
                    'verify_aud': False,
                },
                issuer=settings.CLERK_FRONTEND_API,
            )
        except jwt.ExpiredSignatureError as e:
            logger.warning('Token expired')
            raise AuthenticationFailed('Token has expired') from e
        except jwt.InvalidTokenError as e:
            logger.warning('Invalid token: %s', e)
            raise AuthenticationFailed(f'Invalid token: {str(e)}') from e

        # Check request origin for CSRF protection
        azp = payload.get('azp')
        if azp not in settings.CLERK_AUTHORIZED_PARTIES:
            logger.warning('Unauthorized party: %s', azp)
            raise AuthenticationFailed('Invalid authorised party')

        # Subject claim is the clerk user id, use it to find user in our db
        clerk_user_id = payload.get('sub')
        if not clerk_user_id:
            raise AuthenticationFailed('Token missing sub claim')
        user, _ = User.objects.get_or_create(clerk_id=clerk_user_id, defaults={'is_active': True})

        # Extract org claims from JWT and set on Django request for downstream use
        # (must happen here, not in Django middleware, because DRF auth runs after middleware)
        django_request = getattr(request, '_request', request)
        org_claims = payload.get('o', {})
        if org_claims:
            django_request.org_id = org_claims.get('id')
            django_request.org_role = org_claims.get('rol')
            per = org_claims.get('per', '')
            django_request.org_permissions = [p.strip() for p in per.split(',') if p.strip()] if per else []
            if django_request.org_id:
                django_request.org = Organisation.objects.filter(clerk_org_id=django_request.org_id).first()
                if not django_request.org:
                    # The JWT references an org our webhook hasn't synced yet
                    # (or that failed to sync). Without this guard the request
                    # proceeds with org_id set but org=None — TenantScopedMixin
                    # then queries against a nonexistent org and views that use
                    # request.org fail in confusing, view-specific ways.
                    logger.warning('Organisation not found in DB: %s', django_request.org_id)
                    raise AuthenticationFailed(
                        'Organisation is not synced yet — please retry shortly.'
                    )

        return user, payload
