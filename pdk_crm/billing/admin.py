from django.contrib import admin
from .models import QboConnection, QboWebhookDelivery, QboEntityEvent, DeliveryStatus, EventStatus, Invoice


@admin.register(QboConnection)
class QboConnectionAdmin(admin.ModelAdmin):
    list_display = ("org", "realm_id", "is_active", "access_token_expires_at")
    readonly_fields = ("access_token", "refresh_token")


@admin.register(QboWebhookDelivery)
class QboWebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("received_at", "realm_id", "status", "event_hash")
    list_filter = ("status", "realm_id")
    search_fields = ("event_hash",)
    readonly_fields = ("received_at", "raw_body", "json_payload", "event_hash", "intuit_signature")


@admin.register(QboEntityEvent)
class QboEntityEventAdmin(admin.ModelAdmin):
    list_display = ("entity_name", "entity_id", "operation", "realm_id", "status", "last_updated")
    list_filter = ("entity_name", "operation", "status", "realm_id")
    search_fields = ("entity_id",)
    readonly_fields = ("event_hash",)
    actions = ["mark_queued"]

    def mark_queued(self, request, queryset):
        updated = queryset.update(status = EventStatus.QUEUED)
        self.message_user(request, f"{updated} event(s) marked as queued.")
    mark_queued.short_description = "Mark selected as queued"


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("qbo_invoice_number", "qbo_invoice_id", "client", "status", "qbo_amount_cents", "qbo_balance_cents", "qbo_txn_date", "qbo_due_date", "last_synced_at")
    list_filter = ("status",)
    search_fields = ("qbo_invoice_number", "qbo_invoice_id")