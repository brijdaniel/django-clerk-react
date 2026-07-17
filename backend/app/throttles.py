"""Custom throttle classes for rate limiting.

Pattern: subclass a DRF throttle with a `scope` string, add the scope's rate
to REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] in settings.py, then attach the
class to a view or action:

    @action(detail=False, methods=['post'], throttle_classes=[BurstActionThrottle])
    def expensive_action(self, request):
        ...

Nothing uses BurstActionThrottle out of the box — it ships as a documented
example of the pattern for expensive or abuse-prone endpoints.
"""

from rest_framework.throttling import UserRateThrottle


class BurstActionThrottle(UserRateThrottle):
    """Example per-user throttle for expensive endpoints.

    Rate comes from DEFAULT_THROTTLE_RATES['burst']. Subclasses UserRateThrottle
    (not ScopedRateThrottle) so the class-level `scope` is honoured directly —
    ScopedRateThrottle would instead require every view to also set
    `throttle_scope`, and silently throttles nothing when it is forgotten.
    """
    scope = 'burst'
