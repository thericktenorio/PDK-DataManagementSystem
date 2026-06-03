from django.conf import settings
from django.db import models


class ReviewEntry(models.Model):
    """
    One-to-one review metadata for a ProductAssignment.
    Lifecycle state on the PA remains authoritative; this stores reviewer context,
    notes, and filing timestamps.
    """

    product_assignment = models.OneToOneField(
        "core.ProductAssignment",
        on_delete=models.CASCADE,
        related_name="review_entry",
    )
    assigned_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_assignments",
        help_text="Last staff member who started review (not an exclusive lock).",
    )
    notes = models.TextField(blank=True, default="")
    review_started_at = models.DateTimeField(null=True, blank=True)
    filed_at = models.DateTimeField(null=True, blank=True)
    filed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="filed_review_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Review for PA {self.product_assignment_id}"
