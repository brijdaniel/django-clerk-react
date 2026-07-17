from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import MethodNotAllowed

from .models import Organisation


class SoftDeleteMixin:
    """
    Mixin for DRF viewsets that implements soft delete.
    Sets is_active=False instead of deleting the object from the database.
    Only works with models that have an is_active field.
    """
    def perform_destroy(self, instance):
        """Soft delete by setting is_active=False."""
        if not hasattr(instance, 'is_active'):
            raise MethodNotAllowed('DELETE', detail='This resource does not support deletion')

        instance.is_active = False
        if hasattr(instance, 'updated_by'):
            instance.updated_by = self.request.user
            instance.save(update_fields=['is_active', 'updated_by'])
        else:
            instance.save(update_fields=['is_active'])


class TenantScopedMixin:
    """
    Mixin for DRF views that operate on tenant-scoped models.
    Automatically filters querysets by the active organisation.

    Set `tenant_org_field` on the view to specify the lookup path to the
    organisation. Defaults to 'organisation' (direct FK). For nested
    relationships, use Django's double-underscore syntax:

        class CommentViewSet(TenantScopedMixin, viewsets.ModelViewSet):
            tenant_org_field = 'task__project__organisation'

    For models with a direct organisation FK, `perform_create` will
    auto-set it. For nested models, the serializer should handle
    setting the parent FK instead.
    """
    tenant_org_field = 'organisation'

    def get_queryset(self):
        qs = super().get_queryset()
        org_id = getattr(self.request, 'org_id', None)
        if not org_id:
            return qs.none()
        lookup = f'{self.tenant_org_field}__clerk_org_id'
        return qs.filter(**{lookup: org_id})

    def perform_create(self, serializer):
        kwargs = {}

        if self.tenant_org_field == 'organisation':
            org = getattr(self.request, 'org', None)
            if not org and getattr(self.request, 'org_id', None):
                org = Organisation.objects.filter(clerk_org_id=self.request.org_id).first()
            kwargs['organisation'] = org

        model = serializer.Meta.model
        if hasattr(model, 'created_by'):
            kwargs['created_by'] = self.request.user
        if hasattr(model, 'updated_by'):
            kwargs['updated_by'] = self.request.user

        serializer.save(**kwargs)

    def perform_update(self, serializer):
        kwargs = {}
        model = serializer.Meta.model
        if hasattr(model, 'updated_by'):
            kwargs['updated_by'] = self.request.user
        serializer.save(**kwargs)
