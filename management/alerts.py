# -*- coding: utf-8 -*-
"""Tizimdagi muammo haqida pochtaga xabar.

Tizim holati sahifasi bor, lekin unga QARASH kerak. Kechqurun charger
uzilib qolsa yoki ishchi servis to'xtasa, buni ertalab kimdir panelga
kirgandagina bilib qolinadi — oradagi vaqtda esa parkovka hisoblanmaydi,
push ketmaydi, mijoz esa zaryadlay olmaydi.

Ikki qoida bu xabarni foydali qiladi:

  1. FAQAT O'ZGARISH haqida yoziladi. Har tsiklda bir xil ro'yxatni
     yuborish — bu spam, va o'sha pochta bir haftada e'tibordan
     chiqadi. Xabar muammo PAYDO BO'LGANDA va TUZALGANDA ketadi.
  2. Faqat `down` holati. `warn` — bu "e'tibor bering", yarim kechada
     uyg'otadigan narsa emas.
"""
import logging

logger = logging.getLogger('management.alerts')

# Oxirgi yuborilgan holat shu nom bilan saqlanadi — `JobStatus` allaqachon
# "oxirgi marta nima bo'ldi" ni saqlaydigan joy
STATE_KEY = '__alerts_state__'

logger_prefix = 'VoltMax'


def _previous():
    """Oxirgi xabar yuborilgandagi muammolar ro'yxati."""
    from management.jobs import JobStatus

    row = JobStatus.objects.filter(name=STATE_KEY).first()
    if row is None or not row.last_summary:
        return set()
    return {key for key in row.last_summary.split('|') if key}


def _remember(keys):
    from management.jobs import JobStatus

    JobStatus.record(STATE_KEY, summary='|'.join(sorted(keys)))


def _body(report, appeared, resolved):
    lines = []

    if appeared:
        lines.append('YANGI MUAMMO:')
        for check in report['checks']:
            if check['key'] in appeared:
                lines.append(f"  · {check['title']} — {check['value']}")
                if check['hint']:
                    lines.append(f"    {check['hint']}")
        lines.append('')

    if resolved:
        lines.append('TUZALDI:')
        for key in sorted(resolved):
            lines.append(f'  · {key}')
        lines.append('')

    still = [c for c in report['down'] if c['key'] not in appeared]
    if still:
        lines.append('Hali ham ochiq:')
        for check in still:
            lines.append(f"  · {check['title']} — {check['value']}")
        lines.append('')

    lines.append('Batafsil: panel > Tizim holati')
    return '\n'.join(lines)


def check_and_notify(force=False):
    """Holatni tekshiradi va o'zgargan bo'lsa xabar yuboradi.

    `(yuborildimi, izoh)` qaytaradi. Xato TASHLAMAYDI: ogohlantirish
    yuborilmagani uchun ishchi servis to'xtab qolishi mantiqsiz.
    """
    from management.health import collect
    from management.mail import is_configured, try_send
    from management.models import SiteSettings

    settings_obj = SiteSettings.load()
    recipients = settings_obj.alert_recipients

    if not is_configured(settings_obj) or not recipients:
        return False, ''

    report = collect()
    current = {check['key'] for check in report['down']}
    previous = _previous()

    appeared = current - previous
    resolved = previous - current

    if not appeared and not resolved and not force:
        return False, ''

    if current:
        subject = f'{logger_prefix}: {len(current)} ta muammo'
    else:
        subject = f'{logger_prefix}: hammasi tuzaldi'

    sent, reason = try_send(recipients, subject, _body(report, appeared, resolved))
    if sent:
        # Holat FAQAT muvaffaqiyatli yuborilgach yangilanadi: aks holda
        # pochta ishlamagan paytdagi muammo haqida hech qachon xabar
        # kelmasdi
        _remember(current)
        return True, f'ogohlantirish: {len(appeared)} yangi, {len(resolved)} tuzalgan'

    logger.warning('Ogohlantirish yuborilmadi: %s', reason)
    return False, reason
