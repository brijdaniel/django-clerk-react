from ..models import *


# Webhooks
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
            'is_active': True
        },
    )


def _handle_organisation_updated(data):
    _handle_organisation_created(data)


def _handle_organisation_deleted(data):
    Organisation.objects.filter(clerk_org_id=data['id']).update(is_active=False)
    
    memberships = OrganisationMembership.objects.filter(organisation__clerk_org_id=data['id'], is_active=True)
    memberships.update(is_active=False)
    
    user_ids = list(memberships.values_list('user_id', flat=True))
    User.objects.filter(
        id__in=user_ids,
    ).exclude(
        memberships__is_active=True,
    ).update(is_active=False)


def _handle_membership_created(data):
    user = User.objects.filter(clerk_id=data.get('public_user_data', {}).get('user_id')).first()
    org = Organisation.objects.filter(clerk_org_id=data.get('organization', {}).get('id')).first()

    if user and org:
        OrganisationMembership.objects.update_or_create(
            user=user,
            organisation=org,
            defaults={'role': data.get('role', 'member'), 'is_active': True},
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
        ).update(is_active=False)


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
