# -*- coding: utf-8 -*-
"""«Qayerga qaytish» manzilini xavfsiz tekshiradi.

Panelda ko'p tugma `next` maydonini yuboradi: amal bajarilgach operator
o'zi turgan sahifaga qaytadi. Bu manzil FOYDALANUVCHIDAN keladi va
ilgari to'g'ridan-to'g'ri ishlatilardi.

Nima uchun bu muhim: tashqi manzil qabul qilinsa, bizning domenimizdagi
havola begona saytga olib borishi mumkin bo'ladi. Bunday havola ishonchli
ko'rinadi (domen o'zimizniki) va fishing sahifasiga yo'llash uchun aynan
shunday ochiq yo'naltirishlar ishlatiladi.

Bu yerda hujum og'ir emas — `next` POST bilan keladi va CSRF himoyasi
bor. Lekin tuzatish bir qatordan iborat, xavf esa haqiqiy.
"""
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def safe_redirect(request, fallback):
    """`next` ni tekshirib qaytaradi, mos kelmasa `fallback` ga.

    Faqat SHU saytdagi manzillar qabul qilinadi. Tashqi domen, boshqa
    protokol (`javascript:`) va sxemasiz `//evil.example` — hammasi rad
    etiladi.
    """
    target = request.POST.get('next') or request.GET.get('next')

    if target and url_has_allowed_host_and_scheme(
        url=target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)

    return redirect(fallback)
