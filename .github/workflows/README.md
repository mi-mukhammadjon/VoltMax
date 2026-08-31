# CI

`tests.yml` — har push va PR'da backend sinovlari ishlaydi.

Sinovlar tarmoqqa chiqmaydi: to'lov tizimlari, Google kalendari va push
xizmati testda almashtiriladi. Shuning uchun CI'da maxfiy kalit kerak
emas va sinovlar tashqi xizmat ishlamay qolganda ham o'tadi.

Baza — vaqtinchalik SQLite. Serverda PostgreSQL ishlatiladi, lekin
sinovlar ORM darajasida yozilgan va ikkalasida ham bir xil ishlaydi.
