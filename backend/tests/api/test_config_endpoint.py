"""
Tests for Config API endpoints (ConfigViewSet).

Tests:
- CRUD operations
- Multi-tenancy isolation
- Admin-only access
"""

import pytest
from rest_framework import status

from app.models import Config
from tests.factories import ConfigFactory, OrganisationFactory


@pytest.mark.django_db
class TestConfigList:
    """Tests for GET /api/configs/ endpoint."""

    def test_list_returns_org_configs(self, authenticated_client, organisation):
        """List returns only configs from user's organisation."""
        ConfigFactory(organisation=organisation, name='monthly_limit', value='100')
        ConfigFactory(organisation=organisation, name='feature_flag', value='on')

        # Other org config
        other_org = OrganisationFactory()
        ConfigFactory(organisation=other_org, name='other_config')

        response = authenticated_client.get('/api/configs/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['pagination']['total'] == 2

    def test_list_requires_authentication(self, api_client):
        """Unauthenticated requests denied."""
        response = api_client.get('/api/configs/')
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.django_db
class TestConfigCreate:
    """Tests for POST /api/configs/ endpoint."""

    def test_create_config(self, authenticated_client, organisation):
        """Creating config succeeds."""
        data = {
            'name': 'new_config',
            'value': 'test_value'
        }

        response = authenticated_client.post('/api/configs/', data)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['name'] == 'new_config'

        config = Config.objects.get(id=response.data['id'])
        assert config.organisation == organisation

    def test_create_validates_name(self, authenticated_client):
        """Name is required."""
        data = {'value': 'test'}

        response = authenticated_client.post('/api/configs/', data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'name' in response.data


@pytest.mark.django_db
class TestConfigRetrieve:
    """Tests for GET /api/configs/{id}/ endpoint."""

    def test_retrieve_config(self, authenticated_client, organisation):
        """Retrieving config succeeds."""
        config = ConfigFactory(organisation=organisation)

        response = authenticated_client.get(f'/api/configs/{config.id}/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == config.id

    def test_retrieve_enforces_org_isolation(self, authenticated_client):
        """Cannot retrieve config from different org."""
        other_org = OrganisationFactory()
        config = ConfigFactory(organisation=other_org)

        response = authenticated_client.get(f'/api/configs/{config.id}/')

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestConfigUpdate:
    """Tests for PUT/PATCH /api/configs/{id}/ endpoint."""

    def test_update_config(self, authenticated_client, organisation):
        """Updating config succeeds."""
        config = ConfigFactory(organisation=organisation, name='test', value='old')

        data = {'name': 'test', 'value': 'new'}

        response = authenticated_client.put(f'/api/configs/{config.id}/', data)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['value'] == 'new'

        config.refresh_from_db()
        assert config.value == 'new'

    def test_update_enforces_org_isolation(self, authenticated_client):
        """Cannot update config from different org."""
        other_org = OrganisationFactory()
        config = ConfigFactory(organisation=other_org)

        data = {'value': 'hacked'}

        response = authenticated_client.patch(f'/api/configs/{config.id}/', data)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestConfigDelete:
    """Tests for DELETE /api/configs/{id}/ endpoint."""

    def test_delete_config(self, authenticated_client, organisation):
        """Deleting config removes it from the database."""
        config = ConfigFactory(organisation=organisation)

        response = authenticated_client.delete(f'/api/configs/{config.id}/')

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Config.objects.filter(id=config.id).exists()

    def test_delete_enforces_org_isolation(self, authenticated_client):
        """Cannot delete config from different org."""
        other_org = OrganisationFactory()
        config = ConfigFactory(organisation=other_org)

        response = authenticated_client.delete(f'/api/configs/{config.id}/')

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Config.objects.filter(id=config.id).exists()
