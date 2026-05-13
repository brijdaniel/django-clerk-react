"""
Tests for SMS endpoint (SMSViewSet).

Tests critical SMS/MMS functionality:
- send_sms: Individual SMS sending with limit checking
- send_to_group: Bulk SMS to contact groups
- send_mms: MMS sending with media
- upload_file: File upload for MMS media

These are CRITICAL tests as they verify:
- SMS/MMS sending logic
- Monthly limit enforcement
- Multi-tenancy isolation
- Provider abstraction integration
"""

import pytest
from decimal import Decimal
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status

from app.models import MessageFormat, Organisation, Schedule, ScheduleStatus
from app.utils.storage import StorageProvider
from app.utils.billing import get_balance, grant_credits
from tests.factories import (
    ConfigFactory,
    ContactFactory,
    ContactGroupFactory,
    ScheduleFactory,
    create_contact_group_with_members,
)


@pytest.mark.django_db
class TestSendSMS:
    """Tests for POST /api/sms/send/ endpoint."""

    def test_send_sms_creates_schedule(
        self, authenticated_client, organisation, user, mock_check_sms_limit, mock_send_message_task
    ):
        """Sending SMS creates a QUEUED Schedule record and returns 202."""
        data = {
            'message': 'Test message',
            'recipients': [{'phone': '0412345678'}],
        }

        response = authenticated_client.post('/api/sms/send/', data, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data['success'] is True
        assert 'schedule_id' in response.data

        # Verify Schedule created with QUEUED status
        schedule = Schedule.objects.filter(
            organisation=organisation,
            phone='0412345678',
            format=MessageFormat.SMS
        ).first()

        assert schedule is not None
        assert schedule.text == 'Test message'
        assert schedule.status == ScheduleStatus.QUEUED
        assert schedule.message_parts == 1

        # Verify Celery task was dispatched
        mock_send_message_task.delay.assert_called_once_with(schedule.pk)

    def test_send_sms_with_contact_id(
        self, authenticated_client, contact, mock_check_sms_limit, mock_send_message_task
    ):
        """Sending SMS with contact_id links to contact."""
        data = {
            'message': 'Hello!',
            'recipients': [{'phone': contact.phone, 'contact_id': contact.id}],
        }

        response = authenticated_client.post('/api/sms/send/', data, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED

        schedule = Schedule.objects.filter(contact=contact).first()
        assert schedule is not None
        assert schedule.contact == contact

    def test_send_sms_checks_monthly_limit(
        self, authenticated_client, organisation
    ):
        """Send SMS is blocked when monthly spending limit is reached."""
        organisation.credit_balance = Decimal('10.00')
        organisation.save()
        ConfigFactory(organisation=organisation, name='monthly_limit', value='0.01')

        data = {'message': 'Test', 'recipients': [{'phone': '0412345678'}]}
        response = authenticated_client.post('/api/sms/send/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'limit' in str(response.data).lower()

    def test_send_sms_validates_phone_number(
        self, authenticated_client, mock_check_sms_limit, mock_send_message_task
    ):
        """Invalid phone numbers rejected."""
        data = {
            'message': 'Test',
            'recipients': [{'phone': 'invalid-phone'}],
        }

        response = authenticated_client.post('/api/sms/send/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_send_sms_validates_message(
        self, authenticated_client, mock_check_sms_limit, mock_send_message_task
    ):
        """Empty/invalid messages rejected."""
        data = {
            'message': '',  # Empty message
            'recipients': [{'phone': '0412345678'}],
        }

        response = authenticated_client.post('/api/sms/send/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_send_sms_dispatches_celery_task(
        self, authenticated_client, organisation, mock_check_sms_limit, mock_send_message_task
    ):
        """send_sms dispatches a Celery task (not the provider directly)."""
        data = {
            'message': 'Test message',
            'recipients': [{'phone': '0412345678'}],
        }

        response = authenticated_client.post('/api/sms/send/', data, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        # Provider is NOT called in the view — it's called inside the Celery task
        mock_send_message_task.delay.assert_called_once()

    def test_send_sms_requires_authentication(self, api_client):
        """Unauthenticated requests rejected."""
        data = {'message': 'Test', 'recipients': [{'phone': '0412345678'}]}
        response = api_client.post('/api/sms/send/', data, format='json')

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.django_db
class TestSendToGroup:
    """Tests for POST /api/sms/send-to-group/ endpoint."""

    def test_send_to_group_creates_parent_and_children(
        self, authenticated_client, organisation, user, mock_check_sms_limit, mock_send_batch_message_task
    ):
        """Sending to group creates parent + QUEUED child schedules."""
        # Create group with 3 members
        group, contacts = create_contact_group_with_members(organisation, num_members=3, user=user)

        data = {
            'message': 'Bulk message',
            'group_id': group.id
        }

        response = authenticated_client.post('/api/sms/send-to-group/', data)

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data['success'] is True
        assert response.data['results']['total'] == 3

        # Verify parent schedule
        parent_id = response.data['group_schedule_id']
        parent = Schedule.objects.get(id=parent_id)
        assert parent.group == group
        assert parent.text == 'Bulk message'

        # Verify children are QUEUED (not yet sent)
        children = Schedule.objects.filter(parent=parent)
        assert children.count() == 3

        for child in children:
            assert child.parent == parent
            assert child.text == 'Bulk message'
            assert child.status == ScheduleStatus.QUEUED
            assert child.contact in contacts

        # Single batch task dispatched for parent
        mock_send_batch_message_task.delay.assert_called_once_with(parent.pk)

    def test_send_to_group_skips_opted_out_contacts(
        self, authenticated_client, organisation, user, mock_check_sms_limit, mock_send_message_task
    ):
        """Opted-out contacts excluded from bulk send."""
        group, contacts = create_contact_group_with_members(organisation, num_members=3, user=user)

        # Mark one contact as opted out
        contacts[0].opt_out = True
        contacts[0].save()

        data = {'message': 'Bulk', 'group_id': group.id}
        response = authenticated_client.post('/api/sms/send-to-group/', data)

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data['results']['total'] == 2  # Only 2 queued

    def test_send_to_group_validates_group_exists(
        self, authenticated_client, mock_check_sms_limit, mock_send_message_task
    ):
        """Non-existent group ID rejected."""
        data = {'message': 'Test', 'group_id': 99999}
        response = authenticated_client.post('/api/sms/send-to-group/', data)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_send_to_group_checks_bulk_limit(
        self, authenticated_client, organisation, user
    ):
        """Bulk send is blocked when monthly spending limit is reached."""
        group, _ = create_contact_group_with_members(organisation, num_members=10, user=user)
        organisation.credit_balance = Decimal('10.00')
        organisation.save()
        ConfigFactory(organisation=organisation, name='monthly_limit', value='0.01')

        data = {'message': 'Bulk', 'group_id': group.id}
        response = authenticated_client.post('/api/sms/send-to-group/', data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'limit' in str(response.data).lower()


@pytest.mark.django_db
class TestSendMMS:
    """Tests for POST /api/sms/send-mms/ endpoint."""

    def test_send_mms_creates_schedule(
        self, authenticated_client, organisation, mock_check_mms_limit, mock_send_message_task
    ):
        """Sending MMS creates a QUEUED Schedule with format=MMS."""
        data = {
            'message': 'Check this out!',
            'media_url': 'https://example.com/image.jpg',
            'recipients': [{'phone': '0412345678'}],
            'subject': 'Photo',
        }

        response = authenticated_client.post('/api/sms/send-mms/', data, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data['success'] is True
        assert 'schedule_id' in response.data

        schedule = Schedule.objects.filter(
            organisation=organisation,
            format=MessageFormat.MMS
        ).first()

        assert schedule is not None
        assert schedule.media_url == 'https://example.com/image.jpg'
        assert schedule.subject == 'Photo'
        assert schedule.message_parts == 1  # MMS always 1 part
        assert schedule.status == ScheduleStatus.QUEUED

    def test_send_mms_multiple_recipients_creates_parent_and_children(
        self, authenticated_client, organisation, mock_check_mms_limit, mock_send_batch_message_task
    ):
        """MMS with multiple recipients creates parent + children."""
        data = {
            'message': 'Check this out!',
            'media_url': 'https://example.com/image.jpg',
            'recipients': [{'phone': '0412345678'}, {'phone': '0400000000'}],
            'subject': 'Photo',
        }

        response = authenticated_client.post('/api/sms/send-mms/', data, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert 'parent_schedule_id' in response.data
        assert response.data['total'] == 2

        parent = Schedule.objects.get(pk=response.data['parent_schedule_id'])
        assert parent.format == MessageFormat.MMS
        assert parent.media_url == 'https://example.com/image.jpg'
        assert parent.subject == 'Photo'

        children = Schedule.objects.filter(parent=parent)
        assert children.count() == 2
        for child in children:
            assert child.format == MessageFormat.MMS
            assert child.media_url == 'https://example.com/image.jpg'
            assert child.subject == 'Photo'

        mock_send_batch_message_task.delay.assert_called_once_with(parent.pk)

    def test_send_mms_checks_monthly_limit(
        self, authenticated_client, organisation
    ):
        """Send MMS is blocked when monthly spending limit is reached."""
        organisation.credit_balance = Decimal('10.00')
        organisation.save()
        ConfigFactory(organisation=organisation, name='monthly_limit', value='0.01')

        data = {
            'message': 'Test',
            'media_url': 'https://example.com/image.jpg',
            'recipients': [{'phone': '0412345678'}],
        }

        response = authenticated_client.post('/api/sms/send-mms/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'limit' in str(response.data).lower()

    def test_send_mms_accepts_empty_message(
        self, authenticated_client, mock_check_mms_limit, mock_send_message_task
    ):
        """MMS with empty text (image-only) accepted."""
        data = {
            'message': '',
            'media_url': 'https://example.com/image.jpg',
            'recipients': [{'phone': '0412345678'}],
        }

        response = authenticated_client.post('/api/sms/send-mms/', data, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED

    def test_send_mms_missing_media_url_rejected(
        self, authenticated_client, mock_check_mms_limit, mock_send_message_task
    ):
        """MMS without a media_url is rejected with 400."""
        data = {
            'message': 'Check this out',
            'recipients': [{'phone': '0412345678'}],
            # media_url intentionally omitted
        }

        response = authenticated_client.post('/api/sms/send-mms/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_send_mms_invalid_media_url_rejected(
        self, authenticated_client, mock_check_mms_limit, mock_send_message_task
    ):
        """MMS with a non-URL media_url is rejected with 400."""
        data = {
            'message': 'Hello',
            'media_url': 'not-a-url',
            'recipients': [{'phone': '0412345678'}],
        }

        response = authenticated_client.post('/api/sms/send-mms/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestSendToGroupInactiveMembers:
    """Additional coverage for send_to_group inactive member filtering."""

    def test_send_to_group_skips_inactive_members(
        self, authenticated_client, organisation, user, mock_check_sms_limit, mock_send_message_task
    ):
        """Members with is_active=False are excluded from group sends."""
        group, contacts = create_contact_group_with_members(organisation, num_members=3, user=user)

        # Deactivate one member
        contacts[0].is_active = False
        contacts[0].save()

        data = {
            'message': 'Hello group',
            'group_id': group.id
        }

        response = authenticated_client.post('/api/sms/send-to-group/', data)

        assert response.status_code == status.HTTP_202_ACCEPTED
        # Only 2 active members should be queued
        assert response.data['results']['total'] == 2

    def test_send_to_group_all_inactive_returns_400(
        self, authenticated_client, organisation, user, mock_send_message_task
    ):
        """Group with all inactive members returns 400."""
        group, contacts = create_contact_group_with_members(organisation, num_members=2, user=user)

        for contact in contacts:
            contact.is_active = False
            contact.save()

        data = {
            'message': 'Hello',
            'group_id': group.id
        }

        response = authenticated_client.post('/api/sms/send-to-group/', data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestUploadFile:
    """Tests for POST /api/sms/upload-file/ endpoint."""

    def test_upload_file_accepts_valid_image(
        self, authenticated_client, mock_storage_provider
    ):
        """Valid image file accepted and uploaded."""
        image = SimpleUploadedFile(
            'test.jpg',
            b'fake image content',
            content_type='image/jpeg'
        )

        response = authenticated_client.post(
            '/api/sms/upload-file/',
            {'file': image},
            format='multipart'
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True
        assert 'url' in response.data
        assert 'file_id' in response.data

    def test_upload_file_validates_file_type(self, authenticated_client, mock_storage_provider):
        """Non-image files rejected."""
        txt_file = SimpleUploadedFile(
            'test.txt',
            b'text content',
            content_type='text/plain'
        )

        response = authenticated_client.post(
            '/api/sms/upload-file/',
            {'file': txt_file},
            format='multipart'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_upload_file_validates_file_size(self, authenticated_client, mock_storage_provider):
        """Files exceeding MAX_FILE_SIZE rejected."""
        large_image = SimpleUploadedFile(
            'large.jpg',
            b'x' * (StorageProvider.MAX_FILE_SIZE + 1),
            content_type='image/jpeg'
        )

        response = authenticated_client.post(
            '/api/sms/upload-file/',
            {'file': large_image},
            format='multipart'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'File too large' in str(response.data)

    def test_upload_file_requires_file(self, authenticated_client):
        """Request without file rejected."""
        response = authenticated_client.post(
            '/api/sms/upload-file/',
            {},
            format='multipart'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize('content_type', [
        'image/png',
        'image/jpeg',
        'image/jpg',
        'image/gif',
    ])
    def test_upload_file_accepts_allowed_types(
        self, authenticated_client, mock_storage_provider, content_type
    ):
        """All allowed image types accepted."""
        image = SimpleUploadedFile(
            f'test.{content_type.split("/")[1]}',
            b'image',
            content_type=content_type
        )

        response = authenticated_client.post(
            '/api/sms/upload-file/',
            {'file': image},
            format='multipart'
        )

        assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Prepaid credit reservation at dispatch time
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPrepaidCreditReservation:
    """Credits are reserved in the HTTP request for trial orgs, not in the Celery task."""

    def test_send_sms_trial_reserves_credits(
        self, authenticated_client, organisation, mock_send_message_task
    ):
        """Prepaid org balance decreases at 202 time (before Celery task runs)."""
        organisation.billing_mode = Organisation.BILLING_PREPAID
        organisation.save()
        grant_credits(organisation, Decimal('1.00'), 'test grant')
        balance_before = get_balance(organisation)

        response = authenticated_client.post('/api/sms/send/', {
            'message': 'Hello',
            'recipients': [{'phone': '0412345678'}],
        }, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        # SMS rate deducted immediately
        assert get_balance(organisation) == balance_before - settings.SMS_RATE

    def test_send_sms_subscribed_does_not_reserve_credits(
        self, authenticated_client, organisation, mock_send_message_task
    ):
        """Subscribed org balance is unchanged at dispatch — usage recorded on SENT by task."""
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()
        balance_before = get_balance(organisation)

        response = authenticated_client.post('/api/sms/send/', {
            'message': 'Hello',
            'recipients': [{'phone': '0412345678'}],
        }, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert get_balance(organisation) == balance_before

    def test_send_mms_trial_reserves_credits(
        self, authenticated_client, organisation, mock_send_message_task
    ):
        """Prepaid org MMS send deducts MMS rate immediately."""
        organisation.billing_mode = Organisation.BILLING_PREPAID
        organisation.save()
        grant_credits(organisation, Decimal('1.00'), 'test grant')
        balance_before = get_balance(organisation)

        response = authenticated_client.post('/api/sms/send-mms/', {
            'message': 'Check this',
            'media_url': 'https://example.com/image.jpg',
            'recipients': [{'phone': '0412345678'}],
        }, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert get_balance(organisation) == balance_before - settings.MMS_RATE

    def test_send_to_group_trial_reserves_credits_per_member(
        self, authenticated_client, organisation, user, mock_send_message_task
    ):
        """Group send deducts 1 SMS rate per eligible member at dispatch time."""
        organisation.billing_mode = Organisation.BILLING_PREPAID
        organisation.save()
        grant_credits(organisation, Decimal('10.00'), 'test grant')
        balance_before = get_balance(organisation)

        group, _ = create_contact_group_with_members(organisation, num_members=3, user=user)

        response = authenticated_client.post('/api/sms/send-to-group/', {
            'message': 'Hello group',
            'group_id': group.id,
        })

        assert response.status_code == status.HTTP_202_ACCEPTED
        # 3 members × SMS rate
        assert get_balance(organisation) == balance_before - (3 * settings.SMS_RATE)


# ---------------------------------------------------------------------------
# Contact isolation and empty-group edge cases
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendEdgeCases:
    def test_send_sms_with_unknown_contact_id_returns_404(
        self, authenticated_client, mock_check_sms_limit, mock_send_message_task
    ):
        """contact_id belonging to a different org (or non-existent) returns 404."""
        other_contact = ContactFactory()  # different org — not visible to request.org

        response = authenticated_client.post('/api/sms/send/', {
            'message': 'Hello',
            'recipients': [{'phone': '0412345678', 'contact_id': other_contact.id}],
        }, format='json')

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_send_to_group_with_all_opted_out_returns_400(
        self, authenticated_client, organisation, user, mock_send_message_task
    ):
        """Group where all members are opted out raises 400 'No eligible contacts'."""
        group, contacts = create_contact_group_with_members(organisation, num_members=2, user=user)
        for c in contacts:
            c.opt_out = True
            c.save()

        response = authenticated_client.post('/api/sms/send-to-group/', {
            'message': 'Hello',
            'group_id': group.id,
        })

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'eligible' in str(response.data).lower()
