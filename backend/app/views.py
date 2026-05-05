import csv
import io
import logging
import re
import zoneinfo
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import json

from clerk_backend_api import Clerk
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.db.models import Count, OuterRef, Subquery, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.throttles import ImportThrottle, SMSThrottle
from svix.webhooks import Webhook, WebhookVerificationError

from app.filters import ContactFilter, ContactGroupFilter, GroupScheduleFilter, ScheduleFilter
from app.mixins import SoftDeleteMixin, TenantScopedMixin
from app.models import *
from app.permissions import IsOrgAdmin, IsOrgMember
from app.serializers import *
from app.utils import clerk
from app.utils.billing import check_can_send, record_usage, refund_usage, get_monthly_limit_info, get_monthly_usage, get_rate, get_current_month_preview
from app.utils.metered_billing import get_billing_provider
from app.utils.storage import get_storage_provider
from app.celery import _estimate_parts, generate_monthly_invoices, process_delivery_event, send_batch_message as send_batch_message_task, send_message as send_message_task
from app.utils.sms import get_sms_provider

logger = logging.getLogger(__name__)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get_queryset(self):
        org = getattr(self.request, 'org', None)
        if not org:
            return User.objects.none()
        return User.objects.filter(
            organisationmembership__organisation=org,
        ).annotate(
            _membership_role=Subquery(
                OrganisationMembership.objects.filter(
                    user=OuterRef('pk'), organisation=org,
                ).values('role')[:1]
            ),
            _org_name=Subquery(
                OrganisationMembership.objects.filter(
                    user=OuterRef('pk'), organisation=org,
                ).values('organisation__name')[:1]
            ),
            _is_active=Subquery(
                OrganisationMembership.objects.filter(
                    user=OuterRef('pk'), organisation=org,
                ).values('is_active')[:1]
            ),
        ).order_by('first_name', 'last_name')

    @action(detail=False, methods=['get'])
    def me(self, request):
        """GET /api/users/me/ — authenticated user (read-only, managed by Clerk)."""
        serializer = UserSerializer(request.user)
        # Exclude clerk_id from response
        data = serializer.data
        data.pop('clerk_id', None)
        return Response(data)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsOrgAdmin])
    def role(self, request, pk=None):
        """PATCH /api/users/{id}/role/ — update a member's role (admin only)."""
        new_role = request.data.get('role')
        if new_role not in ('org:admin', 'org:member'):
            return Response({'detail': 'Role must be org:admin or org:member.'}, status=status.HTTP_400_BAD_REQUEST)

        user = self.get_object()
        if user == request.user:
            return Response({'detail': 'Cannot change your own role.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from clerk_backend_api import Clerk
            clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)
            result = clerk_client.organization_memberships.update(
                organization_id=request.org.clerk_org_id,
                user_id=user.clerk_id,
                role=new_role,
            )
            return Response({'status': 'updated', 'role': result.role})
        except Exception as e:
            logger.error('Failed to update role via Clerk: %s', e, exc_info=True)
            return Response({'detail': f'Failed to update role: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsOrgAdmin])
    def status(self, request, pk=None):
        """PATCH /api/users/{id}/status/ — deactivate/reactivate a member (admin only)."""
        is_active = request.data.get('is_active')
        if not isinstance(is_active, bool):
            return Response({'detail': 'is_active must be a boolean.'}, status=status.HTTP_400_BAD_REQUEST)

        user = self.get_object()
        if user == request.user:
            return Response({'detail': 'Cannot change your own status.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)

            if not is_active:
                # Deactivate: delete membership via Clerk → webhook will soft-delete locally
                clerk_client.organization_memberships.delete(
                    organization_id=request.org.clerk_org_id,
                    user_id=user.clerk_id,
                )
                return Response({'status': 'deactivated', 'is_active': False})
            else:
                # Reactivate: send a new invitation via Clerk
                clerk_client.organization_invitations.create(
                    organization_id=request.org.clerk_org_id,
                    email_address=user.email,
                    role='org:member',
                    inviter_user_id=request.user.clerk_id,
                )
                return Response({'status': 'invitation_sent', 'is_active': False})
        except Exception as e:
            logger.error('Failed to update member status via Clerk: %s', e, exc_info=True)
            return Response({'detail': f'Failed to update status: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated, IsOrgAdmin])
    def invite(self, request):
        """POST /api/users/invite/ — invite a new user by email (admin only)."""
        email = request.data.get('email', '').strip()
        role = request.data.get('role', 'org:member')

        if not email:
            return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if role not in ('org:admin', 'org:member'):
            return Response({'detail': 'Role must be org:admin or org:member.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)
            clerk_client.organization_invitations.create(
                organization_id=request.org.clerk_org_id,
                email_address=email,
                role=role,
                inviter_user_id=request.user.clerk_id,
            )
            return Response({'status': 'invitation_sent', 'email': email}, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error('Failed to invite user via Clerk: %s', e, exc_info=True)
            return Response({'detail': f'Failed to send invitation: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)


class ClerkWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if settings.TEST:
            payload = json.loads(request.body)
        else:
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
                logger.error('Clerk webhook signature verification failed')
                return Response({'error': 'Invalid signature'}, status=400)

        event_type = payload.get('type')
        data = payload.get('data', {})
        logger.info('Clerk webhook: type=%s data_keys=%s', event_type, list(data.keys()))

        handler = clerk.WEBHOOK_HANDLERS.get(event_type)
        if handler:
            handler(data)
            logger.info('Processed Clerk webhook event: %s', event_type)
        else:
            logger.warning('Unhandled Clerk webhook event: %s', event_type)

        return Response({'status': 'ok'})


class SMSDeliveryWebhookView(APIView):
    """Receive delivery status callbacks from the SMS/MMS provider.

    Unauthenticated endpoint — validation is delegated to the provider's
    validate_callback_request() method (e.g. shared-secret token for Welcorp).
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        provider = get_sms_provider()

        if not provider.validate_callback_request(request):
            return Response({'error': 'Unauthorized'}, status=401)

        content_type = request.content_type or ''
        if 'form' in content_type or 'urlencoded' in content_type:
            data = dict(request.POST)
        else:
            data = request.data

        try:
            events = provider.parse_delivery_callback(data, content_type)
        except Exception:
            logger.exception('Failed to parse delivery callback')
            return Response({'error': 'Bad request'}, status=400)

        for event in events:
            process_delivery_event.delay(event.__dict__)

        return Response({'status': 'ok'})


class ContactViewSet(SoftDeleteMixin, TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Contact.objects.order_by('-created_at')
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]
    filterset_class = ContactFilter
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    @action(detail=True, methods=['get'])
    def schedules(self, request, pk=None):
        """Create nested GET /api/contacts/:id/schedules/"""
        contact = self.get_object()
        schedules = Schedule.objects.filter(
            contact=contact,
            organisation=contact.organisation,
        ).order_by('-scheduled_time')
        
        page = self.paginate_queryset(schedules)
        serializer = ScheduleSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=['post'], url_path='import', throttle_classes=[ImportThrottle])
    def import_contacts(self, request):
        """POST /api/contacts/import/ — bulk import contacts from a CSV file."""
        org = getattr(request, 'org', None)
        if not org:
            return Response({'detail': 'Organisation required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate file is present and is CSV
        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response({'detail': 'No file uploaded.'}, status=status.HTTP_400_BAD_REQUEST)
        if not uploaded.name.lower().endswith('.csv'):
            return Response({'detail': 'Only CSV files are allowed.'}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded.size > 5 * 1024 * 1024:
            return Response({'detail': 'File size must be less than 5MB.'}, status=status.HTTP_400_BAD_REQUEST)

        # Parse CSV
        try:
            text = io.TextIOWrapper(uploaded, encoding='utf-8')
            reader = csv.DictReader(text)
        except Exception:
            logger.warning('Failed to parse CSV file', exc_info=True)
            return Response({'detail': 'Failed to parse CSV file.'}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch existing phones for this org to detect duplicates
        existing_phones = set(
            Contact.objects.filter(organisation=org).values_list('phone', flat=True)
        )

        error_records = []
        to_create = []

        for row in reader:
            first_name = (row.get('first_name') or '').strip()[:100]
            last_name = (row.get('last_name') or '').strip()[:100]
            phone_raw = row.get('phone', '')

            # Validate and normalise phone
            cleaned = re.sub(r'\s+', '', phone_raw)
            if cleaned.startswith('+614'):
                cleaned = '0' + cleaned[3:]

            if not re.match(r'^04\d{8}$', cleaned):
                error_records.append({**row, 'error': 'Invalid phone number format.'})
                continue

            if cleaned in existing_phones:
                error_records.append({**row, 'error': 'Contact already exists.'})
                continue

            # Track phone to catch duplicates within the file itself
            existing_phones.add(cleaned)

            to_create.append(Contact(
                organisation=org,
                first_name=first_name,
                last_name=last_name,
                phone=cleaned,
                created_by=request.user,
                updated_by=request.user,
            ))

        # Bulk create all valid records
        Contact.objects.bulk_create(to_create)

        record_count = len(to_create) + len(error_records)
        success_count = len(to_create)
        error_count = len(error_records)
        has_errors = error_count > 0

        logger.info('Contact import: %d imported, %d failed', success_count, error_count, extra={
            'org_id': getattr(request, 'org_id', None),
            'record_count': record_count,
        })

        return Response(
            {
                'status': 'partial' if has_errors else 'success',
                'message': f'{success_count} imported, {error_count} failed' if has_errors
                    else f'{success_count} imported successfully',
                'record_count': record_count,
                'success_count': success_count,
                'error_count': error_count,
                'error_records': error_records,
            },
            status=207 if has_errors else status.HTTP_200_OK,
        )


class ContactGroupViewSet(SoftDeleteMixin, TenantScopedMixin, viewsets.ModelViewSet):
    queryset = ContactGroup.objects.all()
    serializer_class = ContactGroupSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]
    filterset_class = ContactGroupFilter

    def get_queryset(self):
        return super().get_queryset().annotate(
            member_count=Count('contactgroupmember'),
        ).order_by('name')

    def perform_create(self, serializer):
        super().perform_create(serializer)
        member_ids = serializer.validated_data.get('member_ids', [])
        if member_ids:
            group = serializer.instance
            contacts = Contact.objects.filter(id__in=member_ids, organisation=group.organisation)
            members = [ContactGroupMember(contact=c, group=group) for c in contacts]
            ContactGroupMember.objects.bulk_create(members, ignore_conflicts=True)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        data = self.get_serializer(instance).data
        
        members_qs = Contact.objects.filter(contactgroupmember__group=instance).order_by('first_name', 'last_name')
        
        page = self.paginate_queryset(members_qs)
        members_data = ContactSerializer(page, many=True).data
        paginated = self.paginator.get_paginated_response(members_data).data
        
        data['members'] = paginated.get('results', [])
        data['pagination'] = paginated.get('pagination', {})
        return Response(data)

    @action(detail=True, methods=['post', 'delete'], url_path='members')
    def members(self, request, pk=None):
        """
        POST /api/groups/:id/members/ — add members
        DELETE /api/groups/:id/members/ — remove members
        """
        group = self.get_object()
        serializer = GroupMemberActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact_ids = serializer.validated_data['contact_ids']

        if request.method == 'POST':
            contacts = Contact.objects.filter(id__in=contact_ids, organisation=group.organisation)
            members = [ContactGroupMember(contact=c, group=group) for c in contacts]
            created = ContactGroupMember.objects.bulk_create(members, ignore_conflicts=True)
            return Response(
                {'message': f'{len(created)} members added.', 'added_count': len(created)},
                status=status.HTTP_201_CREATED,
            )

        elif request.method == 'DELETE':
            deleted, _ = ContactGroupMember.objects.filter(group=group, contact_id__in=contact_ids).delete()
            return Response(
                {'message': f'{deleted} members removed.', 'removed_count': deleted},
                status=status.HTTP_200_OK,
            )


class TemplateViewSet(SoftDeleteMixin, TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Template.objects.filter(is_active=True).order_by('name')
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def perform_update(self, serializer):
        """Auto-increment version on update."""
        instance = serializer.save()
        instance.version += 1
        instance.save(update_fields=['version'])


class ScheduleViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Schedule.objects.filter(
        parent__isnull=True,  # Exclude child schedules
        group__isnull=True,   # Exclude group schedules (handled by /api/group-schedules/)
    ).annotate(
        recipient_count=Count('schedule'),
    ).select_related('contact', 'template', 'group').order_by('-scheduled_time')

    serializer_class = ScheduleSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]
    filterset_class = ScheduleFilter
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def perform_destroy(self, instance):
        """Soft delete by setting status=CANCELLED (v1 used DELETED, v2 uses CANCELLED)."""
        # Only allow deleting PENDING schedules
        if instance.status != ScheduleStatus.PENDING:
            raise ValidationError(f'Cannot delete schedule - only {ScheduleStatus.PENDING} schedules can be deleted')

        instance.status = ScheduleStatus.CANCELLED
        instance.updated_by = self.request.user
        instance.save(update_fields=['status', 'updated_by'])

    @action(detail=True, methods=['get'], url_path='recipients')
    def recipients(self, request, pk=None):
        """GET /api/schedules/{id}/recipients/ — list child schedules for a batch parent."""
        parent = self.get_object()
        children = Schedule.objects.filter(
            parent=parent,
        ).select_related('contact').order_by('id')
        serializer = ScheduleSerializer(children, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['patch'], url_path='force-status')
    def force_status(self, request, pk=None):
        """PATCH /api/schedules/{id}/force-status/ — set status directly (TEST mode only)."""
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        schedule = self.get_object()
        schedule.status = request.data['status']
        schedule.save(update_fields=['status'])
        return Response({'status': schedule.status})

    @action(detail=True, methods=['post'], url_path='retry')
    def retry(self, request, pk=None):
        """POST /api/schedules/{id}/retry/ — re-enqueue a failed schedule."""
        schedule = self.get_object()

        if schedule.status != ScheduleStatus.FAILED:
            raise ValidationError('Only failed schedules can be retried.')

        org = schedule.organisation
        failed_children = Schedule.objects.filter(parent=schedule, status=ScheduleStatus.FAILED)
        is_batch_parent = failed_children.exists()

        # Billing gate
        fmt = schedule.format or 'sms'
        units = sum(c.message_parts for c in failed_children) if is_batch_parent else schedule.message_parts
        can_send, error = check_can_send(org, units=units, format=fmt)
        if not can_send:
            return Response({'detail': error}, status=status.HTTP_402_PAYMENT_REQUIRED)

        # Reset state + re-charge trial credits in one transaction
        reset_fields = dict(status=ScheduleStatus.QUEUED, retry_count=0,
                            error=None, failure_category=None, next_retry_at=None)
        with transaction.atomic():
            for field, value in reset_fields.items():
                setattr(schedule, field, value)
            schedule.save(update_fields=[*reset_fields.keys(), 'updated_at'])

            if is_batch_parent:
                failed_children.update(**reset_fields)

            if org.billing_mode == org.BILLING_TRIAL:
                for s in (list(failed_children) if is_batch_parent else [schedule]):
                    record_usage(
                        org, s.message_parts, format=s.format or 'sms',
                        description=f"Retry {(s.format or 'sms').upper()} to {s.phone}",
                        user=request.user, schedule=s,
                    )

        (send_batch_message_task if is_batch_parent else send_message_task).delay(schedule.pk)

        serializer = self.get_serializer(schedule)
        return Response(serializer.data)


class GroupScheduleViewSet(TenantScopedMixin, viewsets.GenericViewSet):
    """Manages group schedules — a parent Schedule linked to per-member child Schedules.

    A "group schedule" is a parent Schedule row (group set, no contact) with
    one child Schedule per group member (contact set, parent set). All mutations
    happen inside a transaction so the parent and children stay in sync.
    """
    permission_classes = [IsAuthenticated, IsOrgMember]
    serializer_class = ScheduleSerializer
    filterset_class = GroupScheduleFilter

    queryset = Schedule.objects.all()

    def get_queryset(self):
        # TenantScopedMixin handles org scoping; add group schedule filters on top
        return super().get_queryset().filter(
            parent__isnull=True,
            group__isnull=False,
        )

    def list(self, request):
        qs = self.get_queryset().select_related('group', 'template').order_by('-scheduled_time')

        # Apply filters manually (ViewSet doesn't integrate django-filter automatically)
        filterset = GroupScheduleFilter(request.query_params, queryset=qs)
        qs = filterset.qs

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ScheduleSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = ScheduleSerializer(qs, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        parent = self.get_queryset().filter(pk=pk).first()
        if not parent:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Include per-member child schedules in the response
        data = ScheduleSerializer(parent).data
        children = Schedule.objects.filter(parent=parent).select_related('contact')
        data['schedules'] = ScheduleSerializer(children, many=True).data
        data['child_count'] = children.count()
        return Response(data)

    def create(self, request):
        serializer = GroupScheduleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        org = getattr(request, 'org', None)
        if not org:
            return Response({'detail': 'Organisation required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve the group
        group = ContactGroup.objects.filter(id=data['group_id'], organisation=org).first()
        if not group:
            return Response({'detail': 'Group not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Resolve template or inline text
        template, text = None, data.get('text', '')
        if data.get('template_id'):
            template = Template.objects.filter(id=data['template_id'], organisation=org).first()
            if not template:
                return Response({'detail': 'Template not found.'}, status=status.HTTP_404_NOT_FOUND)
            text = template.text
        elif text:
            text = text.strip()

        # Ensure the group has members to schedule (skip opted-out contacts)
        members = Contact.objects.filter(contactgroupmember__group=group, opt_out=False)
        if not members.exists():
            return Response({'detail': 'Group has no members.'}, status=status.HTTP_400_BAD_REQUEST)

        # Gate on billing capacity (both modes) and reserve credits (trial only)
        message_parts = _estimate_parts(text, MessageFormat.SMS)
        member_count = members.count()
        can_send, error = check_can_send(org, units=member_count * message_parts, format='sms')
        if not can_send:
            return Response({'detail': error}, status=status.HTTP_402_PAYMENT_REQUIRED)

        # Create parent + one child per member atomically
        with transaction.atomic():
            parent = Schedule.objects.create(
                organisation=org,
                name=data['name'],
                template=template,
                text=text,
                group=group,
                scheduled_time=data['scheduled_time'],
                format=MessageFormat.SMS,
                message_parts=message_parts,
                created_by=request.user,
                updated_by=request.user,
            )
            children = Schedule.objects.bulk_create([
                Schedule(
                    organisation=org,
                    template=template,
                    text=text,
                    contact=member,
                    phone=member.phone,
                    group=group,
                    parent=parent,
                    scheduled_time=data['scheduled_time'],
                    format=MessageFormat.SMS,
                    message_parts=message_parts,
                    max_retries=getattr(settings, 'MESSAGE_MAX_RETRIES', 3),
                    created_by=request.user,
                    updated_by=request.user,
                )
                for member in members
            ])

            # Trial: reserve credits per child now so subsequent requests see the updated balance.
            # Subscribed: record_usage is called by the Celery task on successful send.
            if org.billing_mode == org.BILLING_TRIAL:
                for child in children:
                    record_usage(
                        org,
                        message_parts,
                        format='sms',
                        description=f"SMS to group '{group.name}'",
                        user=request.user,
                        schedule=child,
                    )

        resp = ScheduleSerializer(parent).data
        resp['schedules'] = ScheduleSerializer(children, many=True).data
        return Response(resp, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        parent = self.get_queryset().filter(pk=pk).first()
        if not parent:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if parent.status != ScheduleStatus.PENDING:
            return Response(
                {'detail': 'Only pending group schedules can be updated.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Schedule.objects.filter(parent=parent).exclude(status=ScheduleStatus.PENDING).exists():
            return Response(
                {'detail': 'Cannot update group schedule after messages have already been sent or failed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = GroupScheduleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org = getattr(request, 'org', None)

        # Build the set of fields to update on the parent
        update_fields = {'updated_by': request.user}
        if 'name' in data:
            update_fields['name'] = data['name']
        if 'scheduled_time' in data:
            update_fields['scheduled_time'] = data['scheduled_time']
        if 'text' in data:
            update_fields['text'] = data['text']

        # Resolve template if provided (None clears the template)
        if 'template_id' in data:
            if data['template_id']:
                template = Template.objects.filter(id=data['template_id'], organisation=org).first()
                if not template:
                    return Response({'detail': 'Template not found.'}, status=status.HTTP_404_NOT_FOUND)
                update_fields['template'] = template
                update_fields['text'] = template.text
            else:
                update_fields['template'] = None

        # Update parent and propagate relevant fields to pending children
        with transaction.atomic():
            for field, value in update_fields.items():
                setattr(parent, field, value)
            parent.save()

            # Only propagate shared fields (text, template, time) to children
            child_fields = {
                k: v for k, v in update_fields.items()
                if k in ('text', 'template', 'scheduled_time', 'updated_by')
            }
            if child_fields:
                Schedule.objects.filter(
                    parent=parent, status=ScheduleStatus.PENDING,
                ).update(**child_fields)

        parent.refresh_from_db()
        resp = ScheduleSerializer(parent).data
        children = Schedule.objects.filter(parent=parent).select_related('contact')
        resp['schedules'] = ScheduleSerializer(children, many=True).data
        return Response(resp)

    def partial_update(self, request, pk=None):
        """PATCH /api/group-schedules/{id}/ - same as update."""
        return self.update(request, pk)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """POST /api/group-schedules/{id}/cancel/ - cancel parent and pending children."""
        parent = self.get_queryset().filter(pk=pk).first()
        if not parent:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if parent.status != ScheduleStatus.PENDING:
            return Response(
                {'detail': 'Only pending group schedules can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cancel the parent and all pending children atomically
        with transaction.atomic():
            Schedule.objects.filter(
                parent=parent, status=ScheduleStatus.PENDING,
            ).update(status=ScheduleStatus.CANCELLED, updated_by=request.user)
            parent.status = ScheduleStatus.CANCELLED
            parent.updated_by = request.user
            parent.save()

        return Response({'message': 'Group schedule cancelled.'})

    def destroy(self, request, pk=None):
        parent = self.get_queryset().filter(pk=pk).first()
        if not parent:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if parent.status != ScheduleStatus.PENDING:
            return Response(
                {'detail': 'Only pending group schedules can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cancel the parent and all pending children atomically, then refund credits
        org = getattr(request, 'org', None)
        with transaction.atomic():
            pending_children = list(
                Schedule.objects.filter(parent=parent, status=ScheduleStatus.PENDING)
            )
            Schedule.objects.filter(
                parent=parent, status=ScheduleStatus.PENDING,
            ).update(status=ScheduleStatus.CANCELLED, updated_by=request.user)
            parent.status = ScheduleStatus.CANCELLED
            parent.updated_by = request.user
            parent.save()

            for child in pending_children:
                refund_usage(org, child)

        return Response(status=status.HTTP_204_NO_CONTENT)


class StatsView(APIView):
    """GET /api/stats/monthly/ — per-month SMS/MMS counts for the last 12 months."""
    permission_classes = [IsAuthenticated, IsOrgMember]

    ADELAIDE_TZ = zoneinfo.ZoneInfo('Australia/Adelaide')

    def get(self, request):
        org = getattr(request, 'org', None)
        if not org:
            return Response({'detail': 'Organisation required.'}, status=status.HTTP_400_BAD_REQUEST)

        # 12 months ago, first day of that month
        now = datetime.now(self.ADELAIDE_TZ)
        start = now.replace(month=now.month, day=1) - timezone.timedelta(days=330)
        start = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Aggregate schedules by month, status, and format
        rows = (
            Schedule.objects.filter(
                organisation=org,
                scheduled_time__gte=start,
            )
            .annotate(month=TruncMonth('scheduled_time', tzinfo=self.ADELAIDE_TZ))
            .values('month', 'status', 'format')
            .annotate(count=Count('id'), parts=Sum('message_parts'))
            .order_by('month')
        )

        # Build per-month buckets
        buckets = defaultdict(lambda: {
            'sms_sent': 0, 'sms_message_parts': 0,
            'mms_sent': 0, 'pending': 0, 'errored': 0,
        })
        for row in rows:
            b = buckets[row['month']]
            count = row['count']
            if row['status'] == ScheduleStatus.SENT:
                if row['format'] == MessageFormat.MMS:
                    b['mms_sent'] += count
                else:
                    b['sms_sent'] += count
                    b['sms_message_parts'] += row['parts'] or 0
            elif row['status'] == ScheduleStatus.PENDING:
                b['pending'] += count
            elif row['status'] == ScheduleStatus.FAILED:
                b['errored'] += count

        # Format month labels and sort (current month first, then reverse chronological)
        monthly_stats = []
        for month_dt, counts in sorted(buckets.items(), reverse=True):
            label = month_dt.astimezone(self.ADELAIDE_TZ).strftime('%B %Y')
            monthly_stats.append({'month': label, **counts})

        limit_info = get_monthly_limit_info(org)

        return Response({
            'monthly_stats': monthly_stats,
            'monthly_limit': str(limit_info['limit']) if limit_info['limit'] is not None else None,
            'total_monthly_spend': str(limit_info['current']),
        })


class ConfigViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Config.objects.all()
    serializer_class = ConfigSerializer
    permission_classes = [IsAuthenticated, IsOrgMember]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']


class SMSViewSet(viewsets.ViewSet):
    """SMS/MMS endpoints with pluggable provider abstraction."""
    permission_classes = [IsAuthenticated, IsOrgMember]

    def _get_org(self, request):
        """Get organisation from request or raise ValidationError."""
        org = getattr(request, 'org', None)
        if not org:
            raise ValidationError('Organisation required.')
        return org

    def _resolve_contact(self, contact_id, org):
        """Resolve contact by ID or raise NotFound. Returns None if contact_id is None."""
        if not contact_id:
            return None
        contact = Contact.objects.filter(id=contact_id, organisation=org).first()
        if not contact:
            raise NotFound('Contact not found.')
        return contact

    def _dispatch_single(self, org, recipient, message, request, *,
                         format_type, message_parts, media_url=None, subject=None):
        """Create one Schedule, record trial billing, dispatch task, return 202."""
        contact = self._resolve_contact(recipient.get('contact_id'), org)
        max_retries = getattr(settings, 'MESSAGE_MAX_RETRIES', 3)

        with transaction.atomic():
            schedule = Schedule.objects.create(
                organisation=org, contact=contact, phone=recipient['phone'],
                text=message, scheduled_time=timezone.now(),
                status=ScheduleStatus.QUEUED, message_parts=message_parts,
                max_retries=max_retries, format=format_type,
                media_url=media_url, subject=subject,
                created_by=request.user, updated_by=request.user,
            )
            if org.billing_mode == org.BILLING_TRIAL:
                record_usage(
                    org, message_parts, format=format_type,
                    description=f"{format_type.upper()} to {recipient['phone']}",
                    user=request.user, schedule=schedule,
                )

        send_message_task.delay(schedule.pk)  # type: ignore[union-attr]
        return Response(
            {'success': True, 'schedule_id': schedule.pk, 'message': 'Message queued for delivery'},
            status=status.HTTP_202_ACCEPTED,
        )

    def _dispatch_batch(self, org, members, message, request, *,
                        format_type, message_parts, media_url=None, subject=None,
                        group=None, description_prefix=None):
        """Create parent + children, record trial billing, dispatch batch task.

        members: list of {'phone': str, 'contact': Contact | None}
        Returns the parent Schedule.
        """
        parent_name = (message or format_type.upper())[:20] + ('...' if len(message or '') > 20 else '')
        max_retries = getattr(settings, 'MESSAGE_MAX_RETRIES', 3)

        with transaction.atomic():
            parent = Schedule.objects.create(
                organisation=org, name=parent_name, text=message,
                message_parts=message_parts, group=group,
                scheduled_time=timezone.now(), status=ScheduleStatus.QUEUED,
                max_retries=max_retries, format=format_type,
                media_url=media_url, subject=subject,
                created_by=request.user, updated_by=request.user,
            )

            for m in members:
                child = Schedule.objects.create(
                    organisation=org, contact=m['contact'], phone=m['phone'],
                    text=message, parent=parent, group=group,
                    scheduled_time=timezone.now(), status=ScheduleStatus.QUEUED,
                    message_parts=message_parts, max_retries=max_retries,
                    format=format_type, media_url=media_url, subject=subject,
                    created_by=request.user, updated_by=request.user,
                )
                if org.billing_mode == org.BILLING_TRIAL:
                    desc = description_prefix or f"{format_type.upper()} to {m['phone']}"
                    record_usage(
                        org, message_parts, format=format_type,
                        description=desc, user=request.user, schedule=child,
                    )

        send_batch_message_task.delay(parent.pk)  # type: ignore[union-attr]
        return parent

    @action(detail=False, methods=['post'], url_path='send', throttle_classes=[SMSThrottle])
    def send_sms(self, request):
        """POST /api/sms/send/ — queue SMS for async delivery."""
        org = self._get_org(request)

        serializer = SendSMSSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        recipients = data['recipients']

        can_send, error = check_can_send(org, units=len(recipients), format='sms')
        if not can_send:
            raise ValidationError(error)

        message_parts = _estimate_parts(data['message'], 'sms')

        if len(recipients) == 1:
            return self._dispatch_single(
                org, recipients[0], data['message'], request,
                format_type=MessageFormat.SMS, message_parts=message_parts,
            )

        members = [
            {'phone': r['phone'], 'contact': self._resolve_contact(r.get('contact_id'), org)}
            for r in recipients
        ]
        parent = self._dispatch_batch(
            org, members, data['message'], request,
            format_type=MessageFormat.SMS, message_parts=message_parts,
        )
        return Response({
            'success': True,
            'message': f'SMS queued for {len(recipients)} recipients',
            'parent_schedule_id': parent.pk,
            'total': len(recipients),
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=['post'], url_path='send-to-group', throttle_classes=[SMSThrottle])
    def send_to_group(self, request):
        """POST /api/sms/send-to-group/ — queue SMS to all eligible group members."""
        org = self._get_org(request)

        serializer = SendGroupSMSSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        group = ContactGroup.objects.filter(id=data['group_id'], organisation=org).first()
        if not group:
            raise NotFound('Group not found.')

        contacts = list(Contact.objects.filter(
            contactgroupmember__group=group, is_active=True, opt_out=False
        ))
        if not contacts:
            raise ValidationError('No eligible contacts found in group.')

        member_count = len(contacts)
        can_send, error = check_can_send(org, units=member_count, format='sms')
        if not can_send:
            raise ValidationError(error)

        message_parts = _estimate_parts(data['message'], 'sms')
        members = [{'phone': c.phone, 'contact': c} for c in contacts]
        parent = self._dispatch_batch(
            org, members, data['message'], request,
            format_type=MessageFormat.SMS, message_parts=message_parts,
            group=group, description_prefix=f"SMS to group '{group.name}'",
        )

        logger.info('Queued batch SMS for %d group members (group %s)', member_count, group.name)

        return Response({
            'success': True,
            'message': f'SMS queued for {member_count} recipients',
            'results': {
                'successful': 0,
                'failed': 0,
                'total': member_count,
            },
            'group_name': group.name,
            'group_schedule_id': parent.pk,
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=['post'], url_path='send-mms', throttle_classes=[SMSThrottle])
    def send_mms(self, request):
        """POST /api/sms/send-mms/ — queue MMS with media for async delivery."""
        org = self._get_org(request)

        serializer = SendMMSSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        recipients = data['recipients']

        can_send, error = check_can_send(org, units=len(recipients), format='mms')
        if not can_send:
            raise ValidationError(error)

        media_url = data['media_url']
        subject = data.get('subject')

        if len(recipients) == 1:
            return self._dispatch_single(
                org, recipients[0], data['message'], request,
                format_type=MessageFormat.MMS, message_parts=1,
                media_url=media_url, subject=subject,
            )

        members = [
            {'phone': r['phone'], 'contact': self._resolve_contact(r.get('contact_id'), org)}
            for r in recipients
        ]
        parent = self._dispatch_batch(
            org, members, data['message'], request,
            format_type=MessageFormat.MMS, message_parts=1,
            media_url=media_url, subject=subject,
        )
        return Response({
            'success': True,
            'message': f'MMS queued for {len(recipients)} recipients',
            'parent_schedule_id': parent.pk,
            'total': len(recipients),
        }, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=['post'], url_path='upload-file')
    def upload_file(self, request):
        """POST /api/sms/upload-file/ — upload image for MMS."""
        uploaded = request.FILES.get('file')
        if not uploaded:
            raise ValidationError('No file provided.')

        # Get storage provider and upload
        # Validation happens in provider._validate_file()
        provider = get_storage_provider()
        result = provider.upload_file(
            file_obj=uploaded,
            filename=uploaded.name,
            content_type=uploaded.content_type
        )

        if result['success']:
            return Response({
                'success': True,
                'url': result['url'],
                'file_id': result['file_id'],
                'size': result['size'],
            })
        else:
            return Response({
                'success': False,
                'error': result['error']
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BillingViewSet(TenantScopedMixin, viewsets.GenericViewSet):
    """GET /api/billing/summary/ — billing summary and transaction history (admin only)."""
    permission_classes = [IsAuthenticated, IsOrgAdmin]
    serializer_class = CreditTransactionSerializer
    queryset = CreditTransaction.objects.all()

    def get_queryset(self):
        return super().get_queryset().order_by('-created_at')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        org = request.org
        limit_info = get_monthly_limit_info(org)

        known_formats = (
            CreditTransaction.objects.filter(organisation=org, format__isnull=False)
            .values_list('format', flat=True)
            .distinct()
        )
        monthly_usage_by_format = {
            fmt: {'spend': str(get_monthly_usage(org, fmt)), 'rate': str(get_rate(fmt, org))}
            for fmt in known_formats
        }

        page = self.paginate_queryset(self.get_queryset())
        tx_data = self.get_serializer(page, many=True).data
        response = self.get_paginated_response(tx_data)
        
        # Latest invoice (for subscribed orgs)
        latest_invoice = None
        latest = (
            Invoice.objects.filter(organisation=org)
            .order_by('-period_start')
            .first()
        )
        if latest:
            latest_invoice = {
                'status': latest.status,
                'amount': str(latest.amount),
                'invoice_url': latest.invoice_url,
                'period_start': latest.period_start.isoformat(),
                'period_end': latest.period_end.isoformat(),
            }

        response.data.update({
            'billing_mode': org.billing_mode,
            'balance': str(org.credit_balance),
            'monthly_limit': str(limit_info['limit']) if limit_info['limit'] is not None else None,
            'total_monthly_spend': str(limit_info['current']),
            'monthly_usage_by_format': monthly_usage_by_format,
            'latest_invoice': latest_invoice,
        })
        return response

    @action(detail=False, methods=['patch'], url_path='test-set-balance')
    def test_set_balance(self, request):
        """PATCH /api/billing/test-set-balance/ — set org credit balance (and optionally
        billing_customer_id) directly (TEST mode only)."""
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        update_fields = []
        if 'balance' in request.data:
            request.org.credit_balance = Decimal(str(request.data['balance']))
            update_fields.append('credit_balance')
        if 'billing_customer_id' in request.data:
            request.org.billing_customer_id = request.data['billing_customer_id']
            update_fields.append('billing_customer_id')
        if update_fields:
            request.org.save(update_fields=update_fields)
        return Response({'credit_balance': str(request.org.credit_balance)})

    @action(detail=False, methods=['post'], url_path='test-seed-usage')
    def test_seed_usage(self, request):
        """POST /api/billing/test-seed-usage/ — create CreditTransaction usage records (TEST mode only).

        Body: { "format": "sms", "amount": "2.50", "description": "Test SMS usage", "backdate_days": 35 }
        Optional backdate_days shifts created_at into the past (for invoice generation testing).
        """
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        fmt = request.data.get('format', 'sms')
        tx = CreditTransaction.objects.create(
            organisation=request.org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal(str(request.data['amount'])),
            balance_after=request.org.credit_balance,
            description=request.data.get('description', 'E2E test usage'),
            format=fmt,
            unit_rate=get_rate(fmt, request.org),
        )
        backdate_days = request.data.get('backdate_days')
        if backdate_days:
            backdated = timezone.now() - timedelta(days=int(backdate_days))
            CreditTransaction.objects.filter(pk=tx.pk).update(created_at=backdated)
        return Response({'status': 'ok'})

    @action(detail=False, methods=['post'], url_path='test-generate-invoices')
    def test_generate_invoices(self, request):
        """POST /api/billing/test-generate-invoices/ — trigger invoice generation (TEST mode only)."""
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        result = generate_monthly_invoices()
        return Response(result)

    @action(detail=False, methods=['post'], url_path='test-create-invoice')
    def test_create_invoice(self, request):
        """POST /api/billing/test-create-invoice/ — create an Invoice record directly (TEST mode only).

        Bypasses the billing provider entirely. Used in E2E tests when the real
        Stripe provider would reject a mock customer ID.

        Body: { "amount": "3.50", "period_start": "2026-03-01T00:00:00+10:30",
                "period_end": "2026-04-01T00:00:00+10:30" }
        """
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        inv = Invoice.objects.create(
            organisation=request.org,
            provider_invoice_id=f'mock_inv_{request.org.pk}_{Invoice.objects.filter(organisation=request.org).count() + 1}',
            status=Invoice.STATUS_OPEN,
            amount=Decimal(str(request.data.get('amount', '3.50'))),
            invoice_url=f'https://mock-billing.example.com/invoices/mock_inv_{request.org.pk}',
            period_start=request.data['period_start'],
            period_end=request.data['period_end'],
        )
        return Response(InvoiceSerializer(inv).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='test-link-billing-customer')
    def test_link_billing_customer(self, request):
        """POST /api/billing/test-link-billing-customer/ — trigger Stripe customer lookup (TEST mode only).

        Searches Stripe for a customer matching the org's clerk_org_id and saves
        the billing_customer_id. Used in E2E tests where the async retry task
        may not have run yet.
        """
        if not settings.TEST:
            return Response({'detail': 'Not available.'}, status=status.HTTP_403_FORBIDDEN)
        org = request.org
        if org.billing_customer_id:
            return Response({'billing_customer_id': org.billing_customer_id, 'already_linked': True})
        provider = get_billing_provider()
        result = provider.find_customer_by_org(org.clerk_org_id)
        if result.success:
            Organisation.objects.filter(pk=org.pk).update(billing_customer_id=result.customer_id)
            return Response({'billing_customer_id': result.customer_id, 'already_linked': False})
        return Response({'error': result.error}, status=404)

    @action(detail=False, methods=['get'])
    def invoices(self, request):
        """GET /api/billing/invoices/ — paginated list of all invoices for this org."""
        qs = Invoice.objects.filter(
            organisation=request.org,
        ).order_by('-period_start')
        page = self.paginate_queryset(qs)
        data = InvoiceSerializer(page, many=True).data
        return self.get_paginated_response(data)

    @action(detail=False, methods=['get'], url_path='invoice-preview')
    def invoice_preview(self, request):
        """GET /api/billing/invoice-preview/ — current month usage preview."""
        return Response(get_current_month_preview(request.org))

    @action(detail=False, methods=['post'], url_path='invoice-download')
    def invoice_download(self, request):
        """POST /api/billing/invoice-download/ — download invoice PDFs.

        Body: { "invoice_ids": [1, 2, 3] }
        Single invoice returns application/pdf; multiple returns application/zip.
        """
        import zipfile

        invoice_ids = request.data.get('invoice_ids', [])
        if not invoice_ids:
            return Response({'detail': 'invoice_ids is required.'}, status=status.HTTP_400_BAD_REQUEST)

        invoices = Invoice.objects.filter(
            organisation=request.org,
            pk__in=invoice_ids,
        )
        if not invoices.exists():
            return Response({'detail': 'No invoices found.'}, status=status.HTTP_404_NOT_FOUND)

        provider = get_billing_provider()
        results = []
        for inv in invoices:
            result = provider.get_invoice_pdf(inv.provider_invoice_id)
            if result.success and result.content:
                month_label = inv.period_start.strftime('%B_%Y').lower()
                results.append((f'{month_label}_invoice_1reach.pdf', result.content))

        if not results:
            return Response(
                {'detail': 'Could not fetch any invoice PDFs.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if len(results) == 1:
            filename, content = results[0]
            response = HttpResponse(content, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        # Multiple invoices — bundle into a zip
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filename, content in results:
                zf.writestr(filename, content)
        buffer.seek(0)

        response = HttpResponse(buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="invoices.zip"'
        return response
