release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: daphne -b 0.0.0.0 -p $PORT voltmax.asgi:application

# Davriy vazifalar — parkovka hisobi, qurilma nazorati, sessiya vaqti
# chegarasi va push yuborish. Hammasi BITTA jarayonda, har biri o'z
# oralig'ida ishlaydi.
#
# Nima uchun bitta: har vazifa uchun alohida servis sozlash unutilsa,
# u jimgina ishlamay qoladi va buni hech kim payqamaydi — parkovka
# hisoblanmaydi, xabar telefonga bormaydi.
#
# MUHIM: bir vaqtda faqat BITTA nusxada ishlashi kerak (replica = 1).
# Veb-server ichiga qo'shib bo'lmaydi: har bir web worker mustaqil
# hisoblab, foydalanuvchidan ortiqcha pul yechilardi.
worker: python manage.py run_workers
