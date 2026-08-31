from pathlib import Path
from datetime import timedelta
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-voltmax-dev-key-change-in-production')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,10.0.2.2,192.168.1.8').split(',')

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

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
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
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_THROTTLE_RATES': {
        'otp': '5/min',
    },
}

# ─── JWT ─────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ─── CORS ─────────────────────────────────────────────────────
# Mobil ilova (axios, native HTTP) Origin header yubormaydi — CORS unga umuman
# taalluqli emas. Bu faqat brauzerdan (masalan `expo start --web`) kirilganda ishlaydi.
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:8081,http://localhost:19006,http://127.0.0.1:8081,http://127.0.0.1:19006',
).split(',')
CORS_ALLOW_CREDENTIALS = True
