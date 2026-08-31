from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def staff_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied("Bu sahifa faqat xodimlar uchun")
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    """Faqat administrator uchun.

    Panelda ikki daraja bor: menejer kundalik ish bilan shug'ullanadi
    (stansiyalar, sessiyalar, kartalar, mijozlar), administrator esa
    TIZIMNI SOZLAYDI — narx, to'lov tizimlari kalitlari, xodimlar va
    hamkorlar bilan hisob-kitob.

    Ilgari bu farq faqat qog'ozda edi: `is_staff` bo'lgan har kim
    sozlamalarni ham, hamkorga to'lovni ham o'zgartira olardi. Panelda
    «Rollar» bo'limi bor edi-yu, hech qayerda tekshirilmasdi.
    """
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied("Bu sahifa faqat xodimlar uchun")
        if not request.user.is_superuser:
            raise PermissionDenied(
                "Bu bo'lim faqat administrator uchun. Menejer uni ko'ra olmaydi."
            )
        return view_func(request, *args, **kwargs)
    return wrapper
