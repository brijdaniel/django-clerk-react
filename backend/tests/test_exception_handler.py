"""Unit tests for the custom DRF exception handler (previously untested)."""

import logging
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import NotFound, ValidationError

from app.exception_handler import custom_exception_handler


@pytest.fixture
def app_logs(caplog):
    """Capture the 'app' logger despite its propagate=False configuration."""
    logger = logging.getLogger('app')
    old_propagate = logger.propagate
    logger.propagate = True
    with caplog.at_level('WARNING', logger='app'):
        yield caplog
    logger.propagate = old_propagate


def _make_request(request_id=None):
    request = Mock()
    request.method = 'GET'
    request.get_full_path.return_value = '/api/configs/'
    request.org_id = 'org_test'
    request.user = Mock(id=1)
    if request_id is not None:
        request.request_id = request_id
    else:
        # Mock auto-creates attributes; emulate a request without request_id
        del request.request_id
    return request


class TestCustomExceptionHandler:
    def test_handled_exception_returns_drf_response(self):
        response = custom_exception_handler(NotFound('missing'), {'request': _make_request()})

        assert response is not None
        assert response.status_code == 404
        assert response.data['detail'] == 'missing'

    def test_request_id_attached_to_dict_responses(self):
        response = custom_exception_handler(
            ValidationError({'phone': ['invalid']}),
            {'request': _make_request(request_id='req-123')},
        )

        assert response.status_code == 400
        assert response.data['request_id'] == 'req-123'

    def test_list_body_does_not_crash_request_id_attach(self):
        """ValidationError with a list body produces a non-dict response.data."""
        response = custom_exception_handler(
            ValidationError(['first', 'second']),
            {'request': _make_request(request_id='req-456')},
        )

        assert response.status_code == 400
        assert isinstance(response.data, list)  # request_id skipped, no crash

    def test_unhandled_exception_returns_none_and_logs(self, app_logs):
        response = custom_exception_handler(RuntimeError('boom'), {'request': _make_request()})

        assert response is None
        assert any('Unhandled exception' in r.getMessage() for r in app_logs.records)

    def test_client_error_logged_as_warning(self, app_logs):
        custom_exception_handler(ValidationError('bad'), {'request': _make_request()})

        assert any(r.levelname == 'WARNING' and 'Client error 400' in r.getMessage()
                   for r in app_logs.records)

    def test_handles_missing_request_in_context(self):
        response = custom_exception_handler(NotFound(), {'request': None})
        assert response.status_code == 404
