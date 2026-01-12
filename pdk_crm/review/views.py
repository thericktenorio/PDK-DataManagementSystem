from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control


# To Review Page
@login_required
@cache_control(no_cache = True, must_revalidate = True, no_store = True)
def review(request):
    return render(request, "review/review.html")