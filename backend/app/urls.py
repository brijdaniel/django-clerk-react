from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from rest_framework.routers import DefaultRouter

from app.health import HealthCheckView, SmokeCheckView, WorkerHealthView
from app.utils.stripe import StripeWebhookView
from app.views import BillingViewSet, ClerkWebhookView, ConfigViewSet, UserViewSet


router = DefaultRouter()
router.register(r'configs', ConfigViewSet)
router.register(r'users', UserViewSet, basename='user')
router.register(r'billing', BillingViewSet, basename='billing')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', HealthCheckView.as_view(), name='health'),
    path('api/health/smoke/', SmokeCheckView.as_view(), name='health-smoke'),
    path('api/health/worker/', WorkerHealthView.as_view(), name='health-worker'),
    path('api/webhooks/clerk/', ClerkWebhookView.as_view(), name='clerk-webhook'),
    path('api/webhooks/stripe/', StripeWebhookView.as_view(), name='stripe-webhook'),
    path('api/', include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    ]
