import jwt
from jwt import PyJWKClient
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import User


# defined at the module level to utilise the PyJWKClient built in cache
jwks_client = PyJWKClient(f'https://{settings.CLERK_FRONTEND_API}/.well-known/jwks.json')

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
                issuer=f'https://{settings.CLERK_FRONTEND_API}',
            )
        except jwt.ExpiredSignatureError as e:
            raise AuthenticationFailed('Token has expired') from e
        except jwt.InvalidTokenError as e:
            raise AuthenticationFailed(f'Invalid token: {str(e)}') from e

        # Check request origin for CSRF protection
        azp = payload.get('azp')
        if azp not in settings.CLERK_AUTHORIZED_PARTIES:
            raise AuthenticationFailed('Invalid authorised party')

        # Subject claim is the clerk user id, use it to find user in our db
        clerk_user_id = payload.get('sub')
        if not clerk_user_id:
            raise AuthenticationFailed('Token missing sub claim')
        user, _ = User.objects.get_or_create(clerk_id=clerk_user_id, defaults={'is_active': True})

        return user, payload
