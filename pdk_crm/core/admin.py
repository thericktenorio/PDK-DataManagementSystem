from django.contrib import admin
from .models import (
    Organization,
    Client,
    TaxYear,
    Product,
    ProductAssignment,
    Intake,
    Acknowledgment,
    DailyClearing,
    TaxSeason,
    FilingType,
    Appointment,
    LifecycleTransition,
    ProductAssignmentEvent,
)


admin.site.register(Organization)
admin.site.register(TaxSeason)
admin.site.register(Client)
admin.site.register(TaxYear)
admin.site.register(Product)
admin.site.register(ProductAssignment)
admin.site.register(Intake)
admin.site.register(Acknowledgment)
admin.site.register(DailyClearing)
admin.site.register(FilingType)
admin.site.register(Appointment)


@admin.register(LifecycleTransition)
class LifecycleTransitionAdmin(admin.ModelAdmin):
    list_display = ("id", "product_assignment", "from_state", "to_state", "actor", "created_at")
    list_filter = ("to_state",)
    readonly_fields = ("product_assignment", "from_state", "to_state", "actor", "created_at", "note", "payload")


@admin.register(ProductAssignmentEvent)
class ProductAssignmentEventAdmin(admin.ModelAdmin):
    list_display = ("id", "product_assignment", "event_type", "created_at", "created_by")
    list_filter = ("event_type",)