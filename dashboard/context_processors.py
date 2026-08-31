"""Panelning barcha sahifalarida kerak bo'ladigan qiymatlar.

Ikkitasi: ochiq nosozliklar soni va bayramlar ro'yxatining versiyasi. U yon menyudagi nishonda turadi,
shuning uchun har bir view'da alohida hisoblash o'rniga shu yerda bir marta
olinadi. So'rov faqat panel sahifalarida va tizimga kirgan xodim uchun
bajariladi — mobil API va login sahifasi ortiqcha yuk olmasin.
"""


def maintenance_badge(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated or not user.is_staff:
        return {}

    from stations.models import MaintenanceIssue

    from management.models import SiteSettings

    settings_obj = SiteSettings.load()
    # Bayramlar sana tanlagichda ishlatiladi va brauzer xotirasida
    # saqlanadi. Versiya — oxirgi sinxronlash vaqti: kalendar yangilangach
    # eski nusxa o'z-o'zidan eskiradi va qayta so'raladi.
    synced = settings_obj.holidays_synced_at
    return {
        'open_issue_count': MaintenanceIssue.objects.filter(
            status=MaintenanceIssue.Status.OPEN
        ).count(),
        'holidays_version': synced.strftime('%Y%m%d%H%M%S') if synced else '0',
    }
