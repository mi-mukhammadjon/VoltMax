from pathlib import Path
from datetime import timedelta
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DEV_SECRET_KEY = 'django-insecure-voltmax-dev-key-change-in-production'
SECRET_KEY = os.getenv('SECRET_KEY', DEV_SECRET_KEY)
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# Bu kalit bilan sessiya cookie'lari va CSRF tokenlari imzolanadi. U
# omma uchun ochiq (kodda turibdi), ya'ni server undan foydalansa
# istalgan odam o'zini XOHLAGAN foydalanuvchi qilib ko'rsata oladi —
# parolsiz, ismini bilishning o'zi yetarli.
#
# Shu sababli server ISHGA TUSHMAYDI. Jimgina ishlab ketgan server bu
# yerda eng yomon variant: hamma narsa joyidek ko'rinadi.
if not DEBUG and SECRET_KEY == DEV_SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY sozlanmagan. Ishlab chiqarishda o'z kalitingizni bering: "
        'SECRET_KEY=<tasodifiy uzun matn>'
    )

# Django admini. Panel hamma ishni qamrab oladi, admin esa qo'shimcha
# hujum yuzasi: uning kirish formasi bizning urinishlar chegarasidan
# o'tmaydi (u alohida ko'rinish). Kerak bo'lsa ataylab yoqiladi.
ENABLE_DJANGO_ADMIN = os.getenv('ENABLE_DJANGO_ADMIN', 'True' if DEBUG else 'False') == 'True'
ALLOWED_HOSTS = [h for h in os.getenv(
    'ALLOWED_HOSTS', 'localhost,127.0.0.1,10.0.2.2').split(',') if h]

# Ishlab chiqishda telefon serverga LOKAL TARMOQ manzili bilan ulanadi va
# u har safar boshqacha: uy Wi-Fi'si, telefon hotspot'i, boshqa ofis.
# Ilgari bu yerda bitta manzil qattiq yozilgan edi va tarmoq
# o'zgarganda ilova `DisallowedHost` olardi — sababi esa telefonda
# «hech narsa yuklanmayapti» bo'lib ko'rinardi.
#
# Faqat XUSUSIY diapazonlar qo'shiladi va faqat DEBUG rejimida. Django
# ham `ALLOWED_HOSTS` bo'sh bo'lsa DEBUG'da shunga o'xshash yon
# beradi; ishlab chiqarishda ro'yxat o'zgarishsiz qoladi.
if DEBUG:
    import socket

    try:
        # `getaddrinfo` mashinaning HAMMA manzilini beradi: Wi-Fi,
        # Ethernet, hotspot — qaysi biri ishlatilishini oldindan bilib
        # bo'lmaydi
        for info in socket.getaddrinfo(socket.gethostname(), None):
            host = info[4][0]
            if host not in ALLOWED_HOSTS:
                ALLOWED_HOSTS.append(host)
    except OSError:
        # Nom yechilmasa ham server ishga tushishi kerak
        pass

# Railway (va boshqa reverse-proxy'lar) TLS'ni proksida tugatadi va Django'ga
# ichkarida oddiy HTTP sifatida yuboradi. Shu header bo'lmasa Django so'rovni
# "insecure" deb hisoblaydi va brauzerning https Origin/Referer'i bilan mos
# kelmay, CSRF tekshiruvi 403 bilan rad etadi.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o]

# Telegram Gateway (https://gateway.telegram.org) — OTP kodlarini Telegram orqali yuborish uchun.
# Token gateway.telegram.org hisobingiz sozlamalaridan olinadi.
TELEGRAM_GATEWAY_TOKEN = os.getenv('TELEGRAM_GATEWAY_TOKEN', '')

INSTALLED_APPS = [
    # 'daphne' birinchi bo'lishi shart — shundagina `runserver` ASGI/WebSocket'ni
    # ham avtomatik xizmat qiladi (OCPP charger ulanishlari shu orqali keladi).
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Panel jadvallarida summalarni "340 000" ko'rinishida chiqarish uchun (intcomma)
    'django.contrib.humanize',
    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    # Chiqishda `refresh` tokenini HAQIQATAN bekor qilish uchun. Usiz
    # "chiqish" faqat telefondagi nusxani o'chirardi — server tomonda
    # token yana bir oy amal qilaverardi.
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'channels',
    # Local
    'accounts',
    'stations',
    'management',
    'sessions_app',
    'wallet',
    'dashboard',
    'ocpp_gateway',
    'bookings',
]

ASGI_APPLICATION = 'voltmax.asgi.application'

# Real charger'lar ulanganda backend bir nechta worker/process sifatida ishlasa
# (masalan productionda), InMemoryChannelLayer worker'lar orasida signal
# almashtira olmaydi — shunda CHANNEL_LAYER_URL orqali Redis'ga o'tkazing
# (`channels_redis` kutubxonasini o'rnatib, RedisChannelLayer'ga almashtiring).
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Tizim sozlamalari bitta so'rov davomida bir marta o'qiladi
    'management.current.SettingsCacheMiddleware',
]

ROOT_URLCONF = 'voltmax.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dashboard.context_processors.maintenance_badge',
            ],
        },
    },
]

WSGI_APPLICATION = 'voltmax.wsgi.application'

DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    import dj_database_url
    DATABASES = {'default': dj_database_url.config(default=DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Parol qoidalari FAQAT xodimlarga taalluqli: mobil foydalanuvchi parol
# ishlatmaydi, u OTP bilan kiradi. Shuning uchun talabni qattiqlashtirish
# hech kimga noqulaylik tug'dirmaydi, panel esa butun tarmoqni boshqaradi.
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 10}},
    # "voltmax2026" kabi taxmin qilinadigan parollarni to'sadi
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    # Parol login yoki ismga o'xshamasin
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    # Django ning umumiy parollar ro'yxatida "voltmax2026" yo'q — u bizga
    # xos. Holbuki aynan shu parol eng xavflisi: hujjatlarda ochiq
    # yozilgan, ya'ni uni birinchi bo'lib sinab ko'rishadi.
    {'NAME': 'management.password.ProjectPasswordValidator'},
]

LANGUAGE_CODE = 'uz'
TIME_ZONE = 'Asia/Tashkent'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# ─── Yuklanadigan fayllar (media) ─────────────────────────────
# Django 5 da STORAGES ikkala kalitni ham talab qiladi. `default` tushib
# qolsa HAR QANDAY fayl yuklash InvalidStorageError bilan 500 beradi.
#
# R2_BUCKET o'rnatilgan bo'lsa fayllar Cloudflare R2 ga yoziladi, aks holda
# lokal diskda qoladi. Shu sabab ishlab chiqishda hech narsa sozlash shart emas,
# serverda esa deploy'dan keyin rasmlar yo'qolmaydi (konteyner fayl tizimi
# vaqtinchalik).
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

R2_BUCKET = os.getenv('R2_BUCKET', '')
USE_R2 = bool(R2_BUCKET)

if USE_R2:
    AWS_STORAGE_BUCKET_NAME = R2_BUCKET
    AWS_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID', '')
    AWS_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '')
    AWS_S3_ENDPOINT_URL = (
        os.getenv('R2_ENDPOINT_URL')
        or f"https://{os.getenv('R2_ACCOUNT_ID', '')}.r2.cloudflarestorage.com"
    )
    AWS_S3_REGION_NAME = 'auto'          # R2 da region tushunchasi yo'q
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_DEFAULT_ACL = None               # R2 ACL'ni qo'llab-quvvatlamaydi
    AWS_S3_FILE_OVERWRITE = False        # bir xil nomli fayl ustiga yozilmasin
    AWS_QUERYSTRING_AUTH = True          # standart: imzolangan (vaqtinchalik) havola
    AWS_QUERYSTRING_EXPIRE = 60 * 60 * 24 * 7

    # Bucket uchun ommaviy domen berilgan bo'lsa (r2.dev yoki o'z domeningiz),
    # havolalar imzosiz va abadiy bo'ladi — mobil ilova uchun shu ma'qul.
    R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', '').strip().rstrip('/')
    if R2_PUBLIC_URL:
        AWS_S3_CUSTOM_DOMAIN = R2_PUBLIC_URL.replace('https://', '').replace('http://', '')
        AWS_QUERYSTRING_AUTH = False

    DEFAULT_FILE_STORAGE_BACKEND = 'storages.backends.s3.S3Storage'
else:
    DEFAULT_FILE_STORAGE_BACKEND = 'django.core.files.storage.FileSystemStorage'

STORAGES = {
    'default': {'BACKEND': DEFAULT_FILE_STORAGE_BACKEND},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Web dashboard ────────────────────────────────────────────
LOGIN_URL = 'dashboard:login'
LOGIN_REDIRECT_URL = 'dashboard:home'

# ─── REST Framework ───────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    # STANDART — YOPIQ. Ilgari `AllowAny` turardi: yangi endpoint
    # yozilganda `permission_classes` ni yozish UNUTILSA, u jimgina
    # hammaga ochiq bo'lib qolardi. Xato ko'zga tashlanmaydi — endpoint
    # ishlayveradi, faqat begona odam ham ko'ra oladi.
    #
    # Ochiq bo'lishi KERAK bo'lganlar (OTP yuborish/tekshirish, stansiyalar
    # ro'yxati, sharhlarni o'qish) buni o'zida aniq yozadi.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Umumiy chegara: hech bir endpoint cheksiz so'rovga ochiq
        # qolmasin. Oddiy foydalanuvchi bunga hech qachon yetmaydi —
        # ilova bir ekranda o'nlab so'rov yubormaydi.
        'anon': '60/min',
        'user': '240/min',
        'otp': '5/min',
        # Promo-kod TANLASH mumkin edi: kod qisqa va urinishlar soni
        # cheklanmagan bo'lsa, uni topib olish vaqt masalasi
        'promo': '10/min',
        # Sharh spamiga qarshi
        'review': '20/min',
    },
}

# Parolni tiklash havolasi shuncha yashaydi. Django ning standarti —
# UCH KUN, bu esa juda uzoq: xat pochtada qolib ketsa, unga uch kun
# davomida kirish mumkin bo'lardi. Panel butun tarmoqni boshqaradi.
#
# Xatdagi matn ham shu qiymatdan olinadi — ikkalasi ajralib qolmasin.
PASSWORD_RESET_HOURS = 2
PASSWORD_RESET_TIMEOUT = PASSWORD_RESET_HOURS * 3600

# ─── JWT ─────────────────────────────────────────────────────
SIMPLE_JWT = {
    # Kirish tokeni QISQA yashaydi. Ilgari u bir hafta amal qilardi: token
    # bir marta oshkor bo'lsa (telefon o'g'irlansa, log'ga tushsa, zararli
    # Wi-Fi), hujumchi bir hafta to'liq kirish huquqiga ega bo'lardi.
    #
    # Ilova tokenni o'zi yangilaydi (`api.ts` dagi 401 ushlagichi), shuning
    # uchun foydalanuvchi buni sezmaydi.
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    # Har yangilashda YANGI refresh beriladi, eskisi qora ro'yxatga
    # tushadi. Shunda o'g'irlangan eski token ishlamay qoladi va tokenning
    # ikki joyda ishlatilayotgani ham bilinadi.
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ─── Xatolar haqida xabar (ixtiyoriy) ─────────────────────────
# Ishlab chiqarishda istisno yuz bersa, u faqat server loglariga tushadi
# va odatda hech kim ko'rmaydi — nosozlikni foydalanuvchi aytganda bilamiz.
# To'lov va OCPP oqimida bu qimmatga tushadi.
#
# `SENTRY_DSN` berilmasa hech narsa yoqilmaydi: kutubxona ham, hisob ham
# majburiy emas, loyiha usiz ham ishlayveradi.
SENTRY_DSN = os.getenv('SENTRY_DSN', '').strip()
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            environment=os.getenv('SENTRY_ENV', 'production'),
            # Xatolar bilan birga foydalanuvchi ma'lumoti yuborilmaydi:
            # telefon raqami va hamyon holati tashqi xizmatga chiqmasin
            send_default_pii=False,
            traces_sample_rate=float(os.getenv('SENTRY_TRACES', '0')),
        )
    except ImportError:
        # Kutubxona o'rnatilmagan — bu xato emas, shunchaki xabar yo'q
        pass

# ─── Xavfsizlik (faqat ishlab chiqarishda) ────────────────────
# Panelga xodimlar parol bilan kiradi. HTTPS'siz sessiya cookie'sini
# tarmoqdan o'qib olish mumkin, shuning uchun `DEBUG=False` bo'lganda
# ulanish majburiy shifrlanadi.
#
# Lokal ishlab chiqishda bular o'chirilgan: `localhost` da HTTPS yo'q va
# yoqilsa brauzer cheksiz qayta yo'naltirishga tushib qolardi.
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Brauzer bir yil davomida faqat HTTPS orqali murojaat qiladi
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Sahifani begona saytga joylab bo'lmasin (clickjacking)
    X_FRAME_OPTIONS = 'DENY'
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'

# ─── CORS ─────────────────────────────────────────────────────
# Mobil ilova (axios, native HTTP) Origin header yubormaydi — CORS unga umuman
# taalluqli emas. Bu faqat brauzerdan (masalan `expo start --web`) kirilganda ishlaydi.
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:8081,http://localhost:19006,http://127.0.0.1:8081,http://127.0.0.1:19006',
).split(',')
CORS_ALLOW_CREDENTIALS = True
