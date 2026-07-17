import logging

from rest_framework.views import exception_handler

logger = logging.getLogger('app')


def custom_exception_handler(exc, context):
    """DRF exception handler that logs errors with request context."""
    response = exception_handler(exc, context)

    request = context.get('request')
    extra = {}
    if request:
        extra = {
            'request_id': getattr(request, 'request_id', None),
            'method': request.method,
            'path': request.get_full_path(),
            'user_id': getattr(request.user, 'id', None) if hasattr(request, 'user') else None,
            'org_id': getattr(request, 'org_id', None),
        }

    if response is None:
        # Unhandled exception — will become a 500. Sentry captures these
        # automatically, but we also log for Azure Monitor visibility.
        logger.error(
            'Unhandled exception: %s',
            str(exc),
            exc_info=exc,
            extra=extra,
        )
        return None

    status_code = response.status_code

    if status_code >= 500:
        logger.error(
            'Server error %d: %s',
            status_code,
            str(exc),
            extra=extra,
        )
    elif status_code >= 400:
        logger.warning(
            'Client error %d: %s',
            status_code,
            str(exc),
            extra=extra,
        )

    # Attach request_id to response so callers can reference it in support
    if request and hasattr(request, 'request_id'):
        if isinstance(response.data, dict):
            response.data['request_id'] = request.request_id

    return response
