from django.contrib import admin

from review.models import ReviewEntry


@admin.register(ReviewEntry)
class ReviewEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product_assignment",
        "assigned_reviewer",
        "review_started_at",
        "filed_at",
        "updated_at",
    )
    search_fields = (
        "product_assignment__client__name",
        "assigned_reviewer__email",
        "notes",
    )
    raw_id_fields = ("product_assignment", "assigned_reviewer", "filed_by")
