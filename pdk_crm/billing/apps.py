from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'billing'

    def ready(self):
        pass  # Phase 6: billing hooks via billing.services.post_clearing (no signals)
