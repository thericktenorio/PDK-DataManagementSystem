from django.urls import path

from . import views


app_name = "review"


urlpatterns = [
    path("", views.review, name="review"),
    path(
        "product-assignments/<int:pa_id>/complete-review/",
        views.complete_review,
        name="complete_review",
    ),
    path(
        "product-assignments/<int:pa_id>/complete-reject-correction/",
        views.complete_reject_correction,
        name="complete_reject_correction",
    ),
    path(
        "product-assignments/<int:pa_id>/force-complete/",
        views.force_complete_review,
        name="force_complete_review",
    ),
    path(
        "product-assignments/<int:pa_id>/paper-filing/",
        views.paper_filing,
        name="paper_filing",
    ),
    path(
        "product-assignments/<int:pa_id>/notes/",
        views.review_notes,
        name="review_notes",
    ),
    path("queue-count/", views.review_queue_count_api, name="queue_count"),
]
