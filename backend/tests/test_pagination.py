"""Unit tests for StandardPagination (previously untested).

The custom envelope ({results, pagination:{total,page,limit,totalPages,
hasNext,hasPrev}}) is load-bearing: every frontend list view parses it.
"""

import pytest
from rest_framework.test import APIRequestFactory

from app.pagination import StandardPagination


def _paginate(objects, query=''):
    factory = APIRequestFactory()
    request = factory.get(f'/api/things/?{query}')
    paginator = StandardPagination()

    # DRF wraps the WSGI request before pagination sees it
    from rest_framework.request import Request
    drf_request = Request(request)
    page = paginator.paginate_queryset(objects, drf_request)
    return paginator.get_paginated_response(page).data


class TestStandardPagination:
    def test_envelope_shape(self):
        data = _paginate(list(range(120)))

        assert set(data.keys()) == {'results', 'pagination'}
        assert set(data['pagination'].keys()) == {
            'total', 'page', 'limit', 'totalPages', 'hasNext', 'hasPrev',
        }

    def test_first_page_defaults(self):
        data = _paginate(list(range(120)))

        assert data['pagination'] == {
            'total': 120, 'page': 1, 'limit': 50, 'totalPages': 3,
            'hasNext': True, 'hasPrev': False,
        }
        assert len(data['results']) == 50

    def test_last_page(self):
        data = _paginate(list(range(120)), 'page=3')

        assert data['pagination']['hasNext'] is False
        assert data['pagination']['hasPrev'] is True
        assert len(data['results']) == 20

    def test_limit_param_respected(self):
        data = _paginate(list(range(30)), 'limit=10')

        assert data['pagination']['limit'] == 10
        assert data['pagination']['totalPages'] == 3
        assert len(data['results']) == 10

    def test_limit_capped_at_max_page_size(self):
        data = _paginate(list(range(200)), 'limit=500')

        assert data['pagination']['limit'] == 50  # max_page_size
        assert len(data['results']) == 50

    def test_empty_queryset(self):
        data = _paginate([])

        assert data['results'] == []
        assert data['pagination']['total'] == 0
        assert data['pagination']['totalPages'] == 0
        assert data['pagination']['hasNext'] is False
