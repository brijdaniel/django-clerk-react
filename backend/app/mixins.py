from .models import Organisation


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
        if self.tenant_org_field != 'organisation':
            serializer.save()
            return

        org = getattr(self.request, 'org', None)
        if not org and getattr(self.request, 'org_id', None):
            org = Organisation.objects.filter(clerk_org_id=self.request.org_id).first()
        serializer.save(organisation=org)
