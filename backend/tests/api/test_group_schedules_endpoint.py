"""
Tests for GroupSchedule API endpoints (GroupScheduleViewSet).

CRITICAL TESTS for parent/child schedule atomicity:
- Creating group schedule creates parent + children atomically
- Updating parent propagates to PENDING children only
- Cancelling parent cancels PENDING children
- Deleting parent deletes PENDING children
- Multi-tenancy isolation
"""

import pytest
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from rest_framework import status

from app.models import Organisation, Schedule, ScheduleStatus
from app.utils.billing import grant_credits
from tests.factories import (
    ContactFactory,
    ContactGroupFactory,
    ContactGroupMemberFactory,
    OrganisationFactory,
    ScheduleFactory,
    create_contact_group_with_members,
)


@pytest.mark.django_db
class TestGroupScheduleList:
    """Tests for GET /api/group-schedules/ endpoint."""

    def test_list_returns_org_group_schedules(self, authenticated_client, organisation, user):
        """List returns only group schedules from user's org."""
        # Group schedules (parent schedules)
        group1 = ContactGroupFactory(organisation=organisation, created_by=user)
        group2 = ContactGroupFactory(organisation=organisation, created_by=user)
        schedule1 = ScheduleFactory(
            organisation=organisation,
            group=group1,
            name='Campaign 1',
            created_by=user
        )
        schedule2 = ScheduleFactory(
            organisation=organisation,
            group=group2,
            name='Campaign 2',
            created_by=user
        )

        # Other org
        other_org = OrganisationFactory()
        other_group = ContactGroupFactory(organisation=other_org)
        ScheduleFactory(organisation=other_org, group=other_group, name='Other')

        response = authenticated_client.get('/api/group-schedules/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pagination']['total'] == 2

    def test_cancelled_group_schedule_appears_in_list(self, authenticated_client, organisation, user):
        """Cancelled group schedules remain visible in the list."""
        group = ContactGroupFactory(organisation=organisation, created_by=user)
        ScheduleFactory(
            organisation=organisation,
            group=group,
            name='Cancelled Campaign',
            status=ScheduleStatus.CANCELLED,
            created_by=user
        )

        response = authenticated_client.get('/api/group-schedules/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pagination']['total'] == 1
        assert response.data['results'][0]['status'] == ScheduleStatus.CANCELLED

    def test_cancelled_group_schedule_remains_in_list_after_cancel(
        self, authenticated_client, organisation, user
    ):
        """After cancelling a group schedule, it still appears in the list."""
        group, contacts = create_contact_group_with_members(organisation, num_members=2, user=user)
        parent = ScheduleFactory(
            organisation=organisation,
            group=group,
            status=ScheduleStatus.PENDING,
            created_by=user
        )

        # Cancel the group schedule
        cancel_response = authenticated_client.post(f'/api/group-schedules/{parent.id}/cancel/')
        assert cancel_response.status_code == status.HTTP_200_OK

        # It should still appear in the list
        list_response = authenticated_client.get('/api/group-schedules/')
        assert list_response.status_code == status.HTTP_200_OK
        assert list_response.data['pagination']['total'] == 1
        assert list_response.data['results'][0]['status'] == ScheduleStatus.CANCELLED

    def test_list_with_group_id_returns_all_dates(self, authenticated_client, organisation, user):
        """Filtering by group_id skips the today-only default and returns all dates."""
        group = ContactGroupFactory(organisation=organisation, created_by=user)
        now = timezone.now()

        today_schedule = ScheduleFactory(
            organisation=organisation, group=group, name='Today', scheduled_time=now, created_by=user
        )
        tomorrow_schedule = ScheduleFactory(
            organisation=organisation, group=group, name='Tomorrow',
            scheduled_time=now + timedelta(days=1), created_by=user
        )

        response = authenticated_client.get(f'/api/group-schedules/?group_id={group.id}')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pagination']['total'] == 2
        ids = {r['id'] for r in response.data['results']}
        assert today_schedule.id in ids
        assert tomorrow_schedule.id in ids

    def test_list_without_group_id_returns_only_today(self, authenticated_client, organisation, user):
        """Without group_id param, only today's group schedules are returned."""
        group = ContactGroupFactory(organisation=organisation, created_by=user)
        now = timezone.now()

        ScheduleFactory(
            organisation=organisation, group=group, name='Today', scheduled_time=now, created_by=user
        )
        ScheduleFactory(
            organisation=organisation, group=group, name='Tomorrow',
            scheduled_time=now + timedelta(days=1), created_by=user
        )

        response = authenticated_client.get('/api/group-schedules/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pagination']['total'] == 1
        assert response.data['results'][0]['name'] == 'Today'

    def test_list_only_shows_parent_schedules(self, authenticated_client, organisation, user):
        """List only shows parent schedules (group != None), not children."""
        # Parent with children
        group = ContactGroupFactory(organisation=organisation, created_by=user)
        parent = ScheduleFactory(
            organisation=organisation,
            group=group,
            name='Parent',
            created_by=user
        )
        child1 = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            for_contact=True,
            created_by=user
        )
        child2 = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            for_contact=True,
            created_by=user
        )

        response = authenticated_client.get('/api/group-schedules/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pagination']['total'] == 1
        assert response.data['results'][0]['id'] == parent.id


@pytest.mark.django_db
class TestGroupScheduleCreate:
    """Tests for POST /api/group-schedules/ endpoint."""

    def test_create_group_schedule_creates_parent_and_children(
        self, authenticated_client, organisation, user, mock_check_sms_limit
    ):
        """Creating group schedule creates parent + child schedules atomically."""
        group, contacts = create_contact_group_with_members(organisation, num_members=3, user=user)
        future = timezone.now() + timedelta(hours=1)

        data = {
            'name': 'Marketing Campaign',
            'group_id': group.id,
            'text': 'Hello everyone!',
            'scheduled_time': future.isoformat()
        }

        response = authenticated_client.post('/api/group-schedules/', data)

        assert response.status_code == status.HTTP_201_CREATED
        parent = Schedule.objects.get(id=response.data['id'])

        # Verify parent
        assert parent.group == group
        assert parent.text == 'Hello everyone!'
        assert parent.name == 'Marketing Campaign'

        # Verify children created
        children = Schedule.objects.filter(parent=parent)
        assert children.count() == 3

        for child in children:
            assert child.parent == parent
            assert child.text == 'Hello everyone!'
            assert child.status == ScheduleStatus.PENDING
            assert child.contact in contacts

    def test_create_validates_group_exists(self, authenticated_client):
        """Non-existent group ID rejected."""
        future = timezone.now() + timedelta(hours=1)
        data = {
            'name': 'Test',
            'group_id': 99999,
            'text': 'Test',
            'scheduled_time': future.isoformat()
        }

        response = authenticated_client.post('/api/group-schedules/', data)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_validates_group_org_isolation(self, authenticated_client):
        """Cannot create schedule for group from different org."""
        other_org = OrganisationFactory()
        other_group = ContactGroupFactory(organisation=other_org)
        future = timezone.now() + timedelta(hours=1)

        data = {
            'name': 'Test',
            'group_id': other_group.id,
            'text': 'Test',
            'scheduled_time': future.isoformat()
        }

        response = authenticated_client.post('/api/group-schedules/', data)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_skips_opted_out_contacts(self, authenticated_client, organisation, user, mock_check_sms_limit):
        """Opted-out contacts excluded from child schedule creation."""
        group, contacts = create_contact_group_with_members(organisation, num_members=5, user=user)

        # Mark 2 contacts as opted out
        contacts[0].opt_out = True
        contacts[0].save()
        contacts[1].opt_out = True
        contacts[1].save()

        future = timezone.now() + timedelta(hours=1)
        data = {
            'name': 'Test',
            'group_id': group.id,
            'text': 'Test',
            'scheduled_time': future.isoformat()
        }

        response = authenticated_client.post('/api/group-schedules/', data)

        assert response.status_code == status.HTTP_201_CREATED

        parent = Schedule.objects.get(id=response.data['id'])
        children = Schedule.objects.filter(parent=parent)

        # Should only create 3 children (5 - 2 opted out)
        assert children.count() == 3


@pytest.mark.django_db
class TestGroupScheduleUpdate:
    """Tests for PUT/PATCH /api/group-schedules/{id}/ endpoint."""

    def test_update_propagates_to_pending_children(self, authenticated_client, organisation, user):
        """Updating parent propagates changes to all PENDING children."""
        group, contacts = create_contact_group_with_members(organisation, num_members=3, user=user)
        parent = ScheduleFactory(
            organisation=organisation,
            group=group,
            text='Original',
            name='Campaign',
            created_by=user
        )

        child1 = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[0],
            phone=contacts[0].phone,
            text='Original',
            status=ScheduleStatus.PENDING,
            created_by=user
        )
        child2 = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[1],
            phone=contacts[1].phone,
            text='Original',
            status=ScheduleStatus.PENDING,
            created_by=user
        )

        future = timezone.now() + timedelta(hours=2)
        data = {
            'name': 'Campaign',
            'group_id': group.id,
            'text': 'Updated message',
            'scheduled_time': future.isoformat()
        }

        response = authenticated_client.put(f'/api/group-schedules/{parent.id}/', data)

        assert response.status_code == status.HTTP_200_OK

        child1.refresh_from_db()
        child2.refresh_from_db()
        assert child1.text == 'Updated message'
        assert child2.text == 'Updated message'

    def test_update_blocked_when_children_have_been_sent(self, authenticated_client, organisation, user):
        """Cannot update a group schedule after any child message has already been sent."""
        group, contacts = create_contact_group_with_members(organisation, num_members=2, user=user)
        parent = ScheduleFactory(
            organisation=organisation,
            group=group,
            text='Original',
            name='Campaign',
            created_by=user
        )
        ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[0],
            phone=contacts[0].phone,
            text='Original',
            status=ScheduleStatus.PENDING,
            created_by=user
        )
        # One child already sent
        ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[1],
            phone=contacts[1].phone,
            text='Original',
            status=ScheduleStatus.SENT,
            sent=True,
            created_by=user
        )

        future = timezone.now() + timedelta(hours=2)
        data = {
            'name': 'Campaign',
            'group_id': group.id,
            'text': 'Updated message',
            'scheduled_time': future.isoformat()
        }

        response = authenticated_client.put(f'/api/group-schedules/{parent.id}/', data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'already been sent' in response.data['detail']

    def test_create_group_schedule_all_opted_out_members(
        self, authenticated_client, organisation, user, mock_check_sms_limit
    ):
        """Creating a group schedule when all members are opted out returns 400."""
        group, contacts = create_contact_group_with_members(organisation, num_members=3, user=user)

        # Opt out all members
        for contact in contacts:
            contact.opt_out = True
            contact.save()

        future = timezone.now() + timedelta(hours=1)
        data = {
            'name': 'Campaign',
            'group_id': group.id,
            'text': 'Hello',
            'scheduled_time': future.isoformat()
        }

        response = authenticated_client.post('/api/group-schedules/', data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'no members' in response.data['detail'].lower()

    def test_cannot_update_sent_group_schedule(self, authenticated_client, organisation, user):
        """Cannot update group schedule that has been sent."""
        group = ContactGroupFactory(organisation=organisation, created_by=user)
        parent = ScheduleFactory(
            organisation=organisation,
            group=group,
            status=ScheduleStatus.SENT,
            sent=True,
            created_by=user
        )

        data = {'text': 'Updated'}

        response = authenticated_client.patch(f'/api/group-schedules/{parent.id}/', data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestGroupScheduleCancel:
    """Tests for POST /api/group-schedules/{id}/cancel/ endpoint."""

    def test_cancel_cancels_parent_and_pending_children(
        self, authenticated_client, organisation, user
    ):
        """Cancelling parent cancels parent + PENDING children."""
        group, contacts = create_contact_group_with_members(organisation, num_members=3, user=user)
        parent = ScheduleFactory(
            organisation=organisation,
            group=group,
            status=ScheduleStatus.PENDING,
            created_by=user
        )

        child_pending = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[0],
            phone=contacts[0].phone,
            status=ScheduleStatus.PENDING,
            created_by=user
        )
        child_sent = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[1],
            phone=contacts[1].phone,
            status=ScheduleStatus.SENT,
            sent=True,
            created_by=user
        )

        response = authenticated_client.post(f'/api/group-schedules/{parent.id}/cancel/')

        assert response.status_code == status.HTTP_200_OK

        parent.refresh_from_db()
        child_pending.refresh_from_db()
        child_sent.refresh_from_db()

        assert parent.status == ScheduleStatus.CANCELLED
        assert child_pending.status == ScheduleStatus.CANCELLED
        assert child_sent.status == ScheduleStatus.SENT  # SENT not cancelled


@pytest.mark.django_db
class TestGroupScheduleDelete:
    """Tests for DELETE /api/group-schedules/{id}/ endpoint."""

    def test_delete_deletes_parent_and_pending_children(
        self, authenticated_client, organisation, user
    ):
        """Deleting parent deletes parent + PENDING children."""
        group, contacts = create_contact_group_with_members(organisation, num_members=2, user=user)
        parent = ScheduleFactory(
            organisation=organisation,
            group=group,
            status=ScheduleStatus.PENDING,
            created_by=user
        )

        child_pending = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[0],
            phone=contacts[0].phone,
            status=ScheduleStatus.PENDING,
            created_by=user
        )
        child_sent = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[1],
            phone=contacts[1].phone,
            status=ScheduleStatus.SENT,
            sent=True,
            created_by=user
        )

        response = authenticated_client.delete(f'/api/group-schedules/{parent.id}/')

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify deletion (soft delete via status=CANCELLED)
        parent.refresh_from_db()
        child_pending.refresh_from_db()
        child_sent.refresh_from_db()

        assert parent.status == ScheduleStatus.CANCELLED
        assert child_pending.status == ScheduleStatus.CANCELLED
        assert child_sent.status == ScheduleStatus.SENT  # SENT children not cancelled

        # SENT child preserved
        child_sent.refresh_from_db()
        assert child_sent.status == ScheduleStatus.SENT

    def test_delete_enforces_org_isolation(self, authenticated_client):
        """Cannot delete group schedule from different org."""
        other_org = OrganisationFactory()
        other_group = ContactGroupFactory(organisation=other_org)
        schedule = ScheduleFactory(organisation=other_org, group=other_group)

        response = authenticated_client.delete(f'/api/group-schedules/{schedule.id}/')

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestGroupScheduleRetrieve:
    """Tests for GET /api/group-schedules/{id}/ endpoint."""

    def test_retrieve_includes_child_count(self, authenticated_client, organisation, user):
        """Retrieve response includes child schedule statistics."""
        group, contacts = create_contact_group_with_members(organisation, num_members=5, user=user)
        parent = ScheduleFactory(
            organisation=organisation,
            group=group,
            created_by=user
        )

        # Create children with different statuses
        ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[0],
            phone=contacts[0].phone,
            status=ScheduleStatus.PENDING,
            created_by=user
        )
        ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[1],
            phone=contacts[1].phone,
            status=ScheduleStatus.SENT,
            sent=True,
            created_by=user
        )
        ScheduleFactory(
            organisation=organisation,
            parent=parent,
            contact=contacts[2],
            phone=contacts[2].phone,
            status=ScheduleStatus.FAILED,
            failed=True,
            created_by=user
        )

        response = authenticated_client.get(f'/api/group-schedules/{parent.id}/')

        assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Billing integration tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGroupScheduleBilling:
    """Billing gate and credit reservation/refund for group scheduled sends."""

    def _make_payload(self, group, scheduled_time=None):
        return {
            'name': 'Billing test campaign',
            'group_id': group.id,
            'text': 'Hello',
            'scheduled_time': (scheduled_time or timezone.now() + timedelta(hours=1)).isoformat(),
        }

    def test_create_blocked_when_insufficient_credits(
        self, authenticated_client, organisation, user
    ):
        """Trial org with insufficient credits gets 402."""
        organisation.billing_mode = Organisation.BILLING_TRIAL
        organisation.credit_balance = Decimal('0.00')
        organisation.save()

        group, _ = create_contact_group_with_members(organisation, num_members=3)
        response = authenticated_client.post(
            '/api/group-schedules/',
            self._make_payload(group),
            format='json',
        )

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED

    def test_create_reserves_credits_for_trial_org(
        self, authenticated_client, organisation, user
    ):
        """Trial org: credit_balance decreases by members × message_parts × rate."""
        organisation.billing_mode = Organisation.BILLING_TRIAL
        organisation.save()
        grant_credits(organisation, Decimal('10.00'), 'Test grant')

        member_count = 3
        group, _ = create_contact_group_with_members(organisation, num_members=member_count, user=user)

        response = authenticated_client.post(
            '/api/group-schedules/',
            self._make_payload(group),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        organisation.refresh_from_db()
        expected_balance = Decimal('10.00') - (member_count * 1 * settings.SMS_RATE)
        assert organisation.credit_balance == expected_balance

    def test_create_does_not_reserve_credits_for_subscribed_org(
        self, authenticated_client, organisation, user
    ):
        """Subscribed org: credit_balance is unchanged after create."""
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.credit_balance = Decimal('0.00')
        organisation.save()

        group, _ = create_contact_group_with_members(organisation, num_members=2, user=user)
        response = authenticated_client.post(
            '/api/group-schedules/',
            self._make_payload(group),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        organisation.refresh_from_db()
        assert organisation.credit_balance == Decimal('0.00')

    def test_destroy_refunds_credits_for_trial_org(
        self, authenticated_client, organisation, user
    ):
        """Trial org: cancelling a PENDING group schedule restores the reserved credits."""
        organisation.billing_mode = Organisation.BILLING_TRIAL
        organisation.save()
        grant_credits(organisation, Decimal('10.00'), 'Test grant')

        member_count = 2
        group, _ = create_contact_group_with_members(organisation, num_members=member_count, user=user)

        # Create group schedule (reserves credits)
        create_response = authenticated_client.post(
            '/api/group-schedules/',
            self._make_payload(group),
            format='json',
        )
        assert create_response.status_code == status.HTTP_201_CREATED

        organisation.refresh_from_db()
        balance_after_create = organisation.credit_balance

        # Cancel the group schedule
        parent_id = create_response.data['id']
        cancel_response = authenticated_client.delete(f'/api/group-schedules/{parent_id}/')

        assert cancel_response.status_code == status.HTTP_204_NO_CONTENT
        organisation.refresh_from_db()
        # Balance should be restored to what it was before the create
        assert organisation.credit_balance == Decimal('10.00')
        assert organisation.credit_balance > balance_after_create

    def test_destroy_does_not_error_for_subscribed_org(
        self, authenticated_client, organisation, user
    ):
        """Subscribed org: cancelling a group schedule returns 204 without billing errors."""
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()

        group, _ = create_contact_group_with_members(organisation, num_members=2, user=user)

        create_response = authenticated_client.post(
            '/api/group-schedules/',
            self._make_payload(group),
            format='json',
        )
        assert create_response.status_code == status.HTTP_201_CREATED

        parent_id = create_response.data['id']
        cancel_response = authenticated_client.delete(f'/api/group-schedules/{parent_id}/')

        assert cancel_response.status_code == status.HTTP_204_NO_CONTENT
