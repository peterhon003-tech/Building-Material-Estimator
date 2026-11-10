from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from estimator.views import can_see_price

from . import recorder
from .models import CalcRecord


def _check_enabled():
    if not recorder.enabled():
        raise Http404()


def _visible(request):
    """一般用戶只看自己的紀錄；系統管理員（職員狀態）可以看所有人的。"""
    qs = CalcRecord.objects.select_related("user")
    if request.user.is_staff:
        return qs
    return qs.filter(user=request.user)


@login_required
def record_list(request):
    _check_enabled()
    qs = _visible(request)
    users = None
    if request.user.is_staff:
        who = request.GET.get("user", "")
        if who == "me":
            qs = qs.filter(user=request.user)
        elif who.isdigit():
            qs = qs.filter(user_id=int(who))
        users = (CalcRecord.objects.exclude(user=None).values_list("user_id", "user__username")
                 .distinct().order_by("user__username"))
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "history/list.html", {
        "page": page, "users": users, "selected_user": request.GET.get("user", ""),
        "can_see_price": can_see_price(request.user), "keep_days": recorder.keep_days(),
    })


@login_required
def record_detail(request, pk):
    _check_enabled()
    rec = get_object_or_404(_visible(request), pk=pk)
    show_prices = rec.include_prices and can_see_price(request.user)
    return render(request, "history/detail.html", {
        "rec": rec, "show_prices": show_prices, "keep_days": recorder.keep_days(),
    })
