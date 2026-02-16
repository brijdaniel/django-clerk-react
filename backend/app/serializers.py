from rest_framework import serializers
from app.models import User, Organisation


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ['clerk_org_id', 'name', 'slug']


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['clerk_id', 'email', 'first_name', 'last_name']


class MeSerializer(serializers.Serializer):
    user = UserSerializer(source='*')
    organisation = serializers.SerializerMethodField()

    def get_organisation(self, obj):
        request = self.context['request']
        org = getattr(request, 'org', None)
        if not org:
            return None
        data = OrganisationSerializer(org).data
        data['role'] = request.org_role
        data['permissions'] = request.org_permissions
        return data
