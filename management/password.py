# -*- coding: utf-8 -*-
"""Loyihaga xos parol qoidasi.

Django'ning tayyor tekshiruvlari umumiy parollar ro'yxatiga qaraydi, u
ro'yxatda esa "voltmax2026" yo'q — u bizga xos. Holbuki aynan shu parol
eng xavflisi: u README va DEPLOY.md da OCHIQ yozilgan, ya'ni parol emas,
taklifnoma. Uni birinchi bo'lib sinab ko'rishadi.

Loyiha nomi kirgan har qanday parol shu toifaga kiradi: "VoltMax2026!",
"voltmax-admin", "Voltmax123" — hammasi taxmin qilinadigan.
"""
from django.core.exceptions import ValidationError

# Loyihaga bog'liq, ya'ni birinchi navbatda sinab ko'riladigan so'zlar
FORBIDDEN_PARTS = ('voltmax', 'volt-max', 'zaryad', 'charger')


class ProjectPasswordValidator:
    """Loyiha nomi yoki hujjatlardagi standart parolni to'sadi."""

    def validate(self, password, user=None):
        lowered = (password or '').lower()
        for part in FORBIDDEN_PARTS:
            if part in lowered:
                raise ValidationError(
                    f'Parolda «{part}» so\'zi bo\'lmasligi kerak — bunday '
                    f'parol birinchi bo\'lib sinab ko\'riladi.',
                    code='password_project_word',
                )

    def get_help_text(self):
        return ('Parolda loyiha nomi (masalan «voltmax») bo\'lmasligi kerak.')
