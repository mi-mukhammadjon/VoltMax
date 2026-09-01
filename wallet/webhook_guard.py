# -*- coding: utf-8 -*-
"""Rad etilgan webhook so'rovlarini YOZIB QO'YADI.

To'lov manzillari imzo bilan himoyalangan: kalitsiz hech narsa
qilib bo'lmaydi. Lekin urinishning O'ZI hech qayerga yozilmasdi —
ya'ni kimdir kalit tanlayotganini bilishning iloji yo'q edi. Bu OCPP
ulanishlari bilan bir xil holat edi va u yerda ham shunday tuzatilgan.

NIMA UCHUN BLOKLANMAYDI: agar operator panelda kalitni xato kiritsa,
to'lov tizimining O'Z so'rovlari ham imzo tekshiruvidan o'tmaydi.
Bloklash yoqilgan bo'lsa, biz Payme yoki Click serverini bloklab
qo'yardik — va kalit tuzatilgandan keyin ham to'lovlar o'tmasdi.
Bunday "himoya" muammoni tuzatishning o'zini imkonsiz qiladi.

Shuning uchun faqat KO'RINADIGAN qilinadi: urinishlar yoziladi va
Tizim holati sahifasida ko'rinadi.
"""
import logging

logger = logging.getLogger('wallet.webhook')


def note_rejected(request, provider_code: str) -> None:
    """Imzodan o'tmagan so'rovni yozadi. Hech qachon xato tashlamaydi."""
    try:
        from management.login_guard import LoginAttempt, client_ip

        LoginAttempt.objects.create(
            # `webhook:` old qo'shimchasi panel loginlaridan ajratadi
            username=f'webhook:{provider_code}'[:150],
            ip=client_ip(request),
            successful=False,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:200],
        )
    except Exception:       # noqa: BLE001 — yozuv javobni buzmasin
        logger.warning('Rad etilgan webhook yozilmadi: %s', provider_code)
