release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: daphne -b 0.0.0.0 -p $PORT voltmax.asgi:application
# Parkovka to'lovi — ALOHIDA jarayon. Veb-worker ichiga qo'shilsa, har bir
# worker mustaqil hisoblab, foydalanuvchidan ortiqcha yechilishi mumkin edi.
# Faqat bitta nusxada ishlashi kerak (Railway'da replica soni = 1).
parking: python manage.py bill_parking --loop --interval 300 --quiet

# Qurilma holati — aloqa uzilishi hodisa emas, uni faqat vaqtni tekshirib
# bilish mumkin. Bu jarayon holatni va nosozlik yozuvlarini yangilab turadi;
# foydalanuvchiga xabar yubormaydi (u panel orqali qo'lda yuboriladi).
devices: python manage.py sync_devices --loop --interval 120 --quiet

# Vaqt chegarasidan oshgan sessiyalarni to'xtatadi. Unutilgan sessiya kun
# bo'yi hisoblanib, foydalanuvchiga katta hisob chiqarardi.
# Faqat bitta nusxada ishlashi kerak (replica soni = 1).
overdue: python manage.py stop_overdue --loop --interval 300 --quiet

# Push xabarlarni telefonlarga yetkazadi. Yuborish so'rov ichida emas,
# alohida jarayonda: tashqi xizmat sekin javob bersa, xabar yozilishi
# (zaryadni to'xtatish, nosozlikni qayd etish) ham sekinlashardi.
push: python manage.py send_push --loop --interval 30 --quiet
