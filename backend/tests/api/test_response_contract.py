"""API response-shape contract tests.

The frontend hand-writes MSW handlers + TypeScript types that mirror these
backend responses (frontend/src/test/handlers.ts, factories.ts, src/types/*).
Nothing else couples the two, so a backend rename (e.g. ``total`` -> ``count``,
a changed error envelope, a dropped field) would leave every frontend test green
while production breaks.

These tests pin the canonical response envelopes the frontend depends on. When
one fails, update BOTH the backend and the mirrored frontend handler/type.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tests.factories import ConfigFactory


@pytest.fixture
def admin_client(user, organisation, org_membership):
    """Authenticated client with admin role (for admin-only endpoints)."""
    client = APIClient()
    client.force_authenticate(user=user)
    from rest_framework.views import APIView
    original_dispatch = APIView.dispatch

    def patched_dispatch(self, request, *args, **kwargs):
        request.org = organisation
        request.org_id = organisation.clerk_org_id
        request.org_role = 'admin'
        request.org_permissions = ['*']
        return original_dispatch(self, request, *args, **kwargs)

    APIView.dispatch = patched_dispatch
    yield client
    APIView.dispatch = original_dispatch


# Mirrored in frontend/src/test/factories.ts ``paginate()`` + types/pagination.types.ts
PAGINATION_KEYS = {'total', 'page', 'limit', 'totalPages', 'hasNext', 'hasPrev'}


@pytest.mark.django_db
class TestResponseContract:
    def test_list_pagination_envelope(self, authenticated_client, organisation):
        """List endpoints return {results: [...], pagination: {...}} (StandardPagination).

        Mirror: frontend factories.ts paginate() / api modules' list parsing.
        """
        ConfigFactory(organisation=organisation)
        resp = authenticated_client.get('/api/configs/')

        assert resp.status_code == status.HTTP_200_OK
        assert set(resp.data.keys()) >= {'results', 'pagination'}
        assert isinstance(resp.data['results'], list)
        assert set(resp.data['pagination'].keys()) == PAGINATION_KEYS
        assert isinstance(resp.data['pagination']['total'], int)
        assert isinstance(resp.data['pagination']['hasNext'], bool)

    def test_permission_denied_error_envelope(self, authenticated_client, organisation):
        """Admin-only endpoints reject members with a string ``detail``.

        Mirror: the frontend's buildError() reads ``detail`` off error bodies.
        """
        resp = authenticated_client.get('/api/billing/summary/')

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert isinstance(resp.data.get('detail'), str)

    def test_validation_error_envelope(self, authenticated_client, organisation):
        """Field validation failures return a 400 with per-field error lists.

        Mirror: frontend form-error rendering.
        """
        resp = authenticated_client.post('/api/configs/', {'name': 'incomplete'}, format='json')

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'value' in resp.data
        assert isinstance(resp.data['value'], list)

    def test_billing_summary_envelope(self, admin_client):
        """GET /api/billing/summary/ returns the fields the billing page reads.

        Mirror: frontend factories.ts createBillingSummary() / billing.types.ts.
        """
        resp = admin_client.get('/api/billing/summary/')
        assert resp.status_code == status.HTTP_200_OK
        assert 'billing_mode' in resp.data
        assert 'balance' in resp.data
        assert 'monthly_usage_by_type' in resp.data
        assert 'results' in resp.data
        assert 'pagination' in resp.data
