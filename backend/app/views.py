import logging

from django.conf import settings
from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from svix.webhooks import Webhook, WebhookVerificationError

from app.models import *
from app.serializers import *

logger = logging.getLogger(__name__)


class MeView(generics.RetrieveAPIView):
    serializer_class = MeSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class ClerkWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        signing_secret = settings.CLERK_WEBHOOK_SIGNING_SECRET
        if not signing_secret:
            logger.error('CLERK_WEBHOOK_SIGNING_SECRET not configured')
            return Response({'error': 'Webhook not configured'}, status=500)

        headers = {
            'svix-id': request.headers.get('svix-id', ''),
            'svix-timestamp': request.headers.get('svix-timestamp', ''),
            'svix-signature': request.headers.get('svix-signature', ''),
        }

        try:
            wh = Webhook(signing_secret)
            payload = wh.verify(request.body, headers)
        except WebhookVerificationError:
            logger.warning('Clerk webhook signature verification failed')
            return Response({'error': 'Invalid signature'}, status=400)

        event_type = payload.get('type')
        data = payload.get('data', {})

        handler = WEBHOOK_HANDLERS.get(event_type)
        if handler:
            handler(data)
            logger.info('Processed Clerk webhook event: %s', event_type)
        else:
            logger.debug('Unhandled Clerk webhook event: %s', event_type)

        return Response({'status': 'ok'})


def _handle_user_created(data):
    email = ''
    email_addresses = data.get('email_addresses', [])
    for addr in email_addresses:
        if addr.get('id') == data.get('primary_email_address_id'):
            email = addr.get('email_address', '')
            break

    User.objects.update_or_create(
        clerk_id=data['id'],
        defaults={
            'email': email,
            'first_name': data.get('first_name', ''),
            'last_name': data.get('last_name', ''),
            'is_active': True,
        },
    )


def _handle_user_updated(data):
    _handle_user_created(data)


def _handle_user_deleted(data):
    User.objects.filter(clerk_id=data['id']).update(is_active=False)


def _handle_organisation_created(data):
    Organisation.objects.update_or_create(
        clerk_org_id=data['id'],
        defaults={
            'name': data.get('name', ''),
            'slug': data.get('slug', ''),
        },
    )


def _handle_organisation_updated(data):
    _handle_organisation_created(data)


def _handle_organisation_deleted(data):
    Organisation.objects.filter(clerk_org_id=data['id']).delete()


def _handle_membership_created(data):
    user = User.objects.filter(clerk_id=data.get('public_user_data', {}).get('user_id')).first()
    org = Organisation.objects.filter(clerk_org_id=data.get('organization', {}).get('id')).first()

    if user and org:
        OrganisationMembership.objects.update_or_create(
            user=user,
            organisation=org,
            defaults={'role': data.get('role', 'member')},
        )


def _handle_membership_updated(data):
    _handle_membership_created(data)


def _handle_membership_deleted(data):
    user_id = data.get('public_user_data', {}).get('user_id')
    org_id = data.get('organization', {}).get('id')

    if user_id and org_id:
        OrganisationMembership.objects.filter(
            user__clerk_id=user_id,
            organisation__clerk_org_id=org_id,
        ).delete()


# Clerk API event type strings must use US spelling (Clerk's API convention)
WEBHOOK_HANDLERS = {
    'user.created': _handle_user_created,
    'user.updated': _handle_user_updated,
    'user.deleted': _handle_user_deleted,
    'organization.created': _handle_organisation_created,
    'organization.updated': _handle_organisation_updated,
    'organization.deleted': _handle_organisation_deleted,
    'organizationMembership.created': _handle_membership_created,
    'organizationMembership.updated': _handle_membership_updated,
    'organizationMembership.deleted': _handle_membership_deleted,
}
