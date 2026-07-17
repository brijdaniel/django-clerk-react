import logging
import time
import uuid


logger = logging.getLogger('app.middleware')


class RequestLoggingMiddleware:
    """Logs every request with a unique request ID and duration.

    Mirrors the v1 Express requestLogger middleware:
      - Reads or generates a UUID (via X-Request-ID header)
      - Attaches request.request_id for downstream use
      - Logs incoming request (method, path, IP, user-agent)
      - Logs response completion (method, path, status, duration)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = (
            request.headers.get('X-Request-ID') or uuid.uuid4().hex
        )

        logger.info(
            'Incoming request',
            extra={
                'request_id': request.request_id,
                'method': request.method,
                'path': request.get_full_path(),
                'ip': request.META.get('REMOTE_ADDR', ''),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            },
        )

        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = (time.monotonic() - start) * 1000

        logger.info(
            'Request completed',
            extra={
                'request_id': request.request_id,
                'method': request.method,
                'path': request.get_full_path(),
                'status': response.status_code,
                'duration_ms': round(duration_ms, 1),
            },
        )

        return response
