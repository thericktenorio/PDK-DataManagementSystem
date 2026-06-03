from django.urls import path

from . import views


app_name = "review"


urlpatterns = [
    path("", views.review, name="review"),
    path(
        "product-assignments/<int:pa_id>/start/",
        views.start_review,
        name="start_review",
    ),
    path(
        "product-assignments/<int:pa_id>/mark-filed/",
        views.mark_filed,
        name="mark_filed",
    ),
    path(
        "product-assignments/<int:pa_id>/notes/",
        views.review_notes,
        name="review_notes",
    ),
    path("queue-count/", views.review_queue_count_api, name="queue_count"),
]
