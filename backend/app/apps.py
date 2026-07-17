from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'

    def ready(self):
        # Importing registers the system checks via their @register decorators.
        from . import checks  # noqa: F401
