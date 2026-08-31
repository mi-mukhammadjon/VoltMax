# -*- coding: utf-8 -*-
"""Amallar jurnaliga yozish.

Bitta qisqa funksiya: `log_action(request, action, title, detail, url)`. U
`ActivityLog` yozuvini yaratadi va HECH QACHON istisno ko'tarmaydi —
jurnal asosiy amalni to'xtatmasligi kerak. Karta bloklanishi yoki pul
o'tkazilishi jurnalga yozib bo'lmagani uchun bekor bo'lsa, bu jurnalning
o'zidan ko'ra jiddiyroq muammo bo'lardi.
"""

import logging

logger = logging.getLogger('management.activity')


def log_action(request, action, title, detail='', url=''):
    """Amalni yozib qo'yadi va yozuvni (yoki `None`) qaytaradi."""
    from .models import ActivityLog

    try:
        user = getattr(request, 'user', None)
        return ActivityLog.objects.create(
            actor=user if user is not None and user.is_authenticated else None,
            action=action,
            title=title[:150],
            detail=(detail or '')[:400],
            target_url=(url or '')[:200],
        )
    except Exception as error:      # noqa: BLE001 — jurnal amalni to'xtatmaydi
        logger.warning('Amal jurnalga yozilmadi (%s): %s', title, error)
        return None
