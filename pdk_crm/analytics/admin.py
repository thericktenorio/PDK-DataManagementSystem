from django.contrib import admin

from analytics.models import (
    DimClient,
    DimTaxSeason,
    EtlRun,
    FactAssignment,
    FactInvoice,
)


@admin.register(EtlRun)
class EtlRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "finished_at", "status", "is_full_refresh", "rows_assignments")
    readonly_fields = [f.name for f in EtlRun._meta.fields]


@admin.register(FactAssignment)
class FactAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "source_pa_id",
        "tax_season_year",
        "lifecycle_state",
        "expected_fee",
        "actual_revenue_recognized",
        "revenue_gap",
    )
    list_filter = ("tax_season_year", "lifecycle_state", "payment_method")
    search_fields = ("source_pa_id", "preparer_email")


admin.site.register(DimTaxSeason)
admin.site.register(DimClient)
admin.site.register(FactInvoice)
