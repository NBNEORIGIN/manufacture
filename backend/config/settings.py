import os
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='dev-insecure-key-change-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'core',
    'products',
    'stock',
    'production',
    'shipments',
    'procurement',
    'imports',
    'd2c',
    'restock',
    'barcodes',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

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
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

import dj_database_url

DATABASE_URL = config('DATABASE_URL', default=None)
if DATABASE_URL:
    DATABASES = {'default': dj_database_url.parse(DATABASE_URL)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='manufacture'),
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default='postgres123'),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-gb'
TIME_ZONE = 'Europe/London'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000,https://manufacture.nbnesigns.co.uk',
).split(',')
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000,https://manufacture.nbnesigns.co.uk',
).split(',')

SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_HTTPONLY = True

SPREADSHEET_PATH = config(
    'SPREADSHEET_PATH',
    default=str(Path('C:/Users/zentu/Downloads/Shipment Stock Sheet (1).xlsx'))
)

# Phloe staff sync
PHLOE_API_URL = config('PHLOE_API_URL', default='')
PHLOE_API_TOKEN = config('PHLOE_API_TOKEN', default='')

# Cairn AMI integration (for SP-API delegation and SKU lookup)
CAIRN_API_URL = config('CAIRN_API_URL', default='http://localhost:8765')
CAIRN_API_KEY = config('CAIRN_API_KEY', default='')

# Restock Newsvendor defaults
RESTOCK_LEAD_TIME_DAYS = config('RESTOCK_LEAD_TIME_DAYS', default=7, cast=int)
RESTOCK_REVIEW_PERIOD_DAYS = config('RESTOCK_REVIEW_PERIOD_DAYS', default=30, cast=int)
RESTOCK_CV_DEFAULT = config('RESTOCK_CV_DEFAULT', default=0.4, cast=float)
RESTOCK_TARGET_SERVICE_LEVEL = config('RESTOCK_TARGET_SERVICE_LEVEL', default=0.90, cast=float)

# Avery label sheet layout (defaults: L4791, 27-up, 3×9 on A4)
AVERY_COLS = int(os.environ.get('AVERY_COLS', '3'))
AVERY_ROWS = int(os.environ.get('AVERY_ROWS', '9'))
AVERY_LABEL_W_MM = float(os.environ.get('AVERY_LABEL_W_MM', '63.5'))
AVERY_LABEL_H_MM = float(os.environ.get('AVERY_LABEL_H_MM', '29.6'))
AVERY_TOP_MARGIN_MM = float(os.environ.get('AVERY_TOP_MARGIN_MM', '7.9'))
AVERY_LEFT_MARGIN_MM = float(os.environ.get('AVERY_LEFT_MARGIN_MM', '9.25'))
AVERY_H_GAP_MM = float(os.environ.get('AVERY_H_GAP_MM', '3.0'))
AVERY_V_GAP_MM = float(os.environ.get('AVERY_V_GAP_MM', '0.0'))

# Label printing
LABEL_COMMAND_LANGUAGE = os.environ.get('LABEL_COMMAND_LANGUAGE', 'zpl')
LABEL_WIDTH_MM = float(os.environ.get('LABEL_WIDTH_MM', '50'))
LABEL_HEIGHT_MM = float(os.environ.get('LABEL_HEIGHT_MM', '25'))
LABEL_DPI = int(os.environ.get('LABEL_DPI', '203'))
LABEL_WIDTH_DOTS = int(LABEL_WIDTH_MM * LABEL_DPI / 25.4)
LABEL_HEIGHT_DOTS = int(LABEL_HEIGHT_MM * LABEL_DPI / 25.4)
PRINT_AGENT_TOKEN = os.environ.get('PRINT_AGENT_TOKEN', '')
LABELARY_API_BASE = os.environ.get('LABELARY_API_BASE', 'http://api.labelary.com/v1')

# SP-API credentials (shared with restock module — uses existing AMAZON_* env vars)
SP_API_CREDENTIALS = {
    'refresh_token': os.environ.get('AMAZON_REFRESH_TOKEN_EU', ''),  # EU covers UK/DE
    'lwa_app_id': os.environ.get('AMAZON_CLIENT_ID', ''),
    'lwa_client_secret': os.environ.get('AMAZON_CLIENT_SECRET', ''),
}
# Per-marketplace refresh tokens for multi-region sync
SP_API_REFRESH_TOKENS = {
    'UK': os.environ.get('AMAZON_REFRESH_TOKEN_EU', ''),
    'DE': os.environ.get('AMAZON_REFRESH_TOKEN_EU', ''),
    'FR': os.environ.get('AMAZON_REFRESH_TOKEN_EU', ''),
    'IT': os.environ.get('AMAZON_REFRESH_TOKEN_EU', ''),
    'ES': os.environ.get('AMAZON_REFRESH_TOKEN_EU', ''),
    'NL': os.environ.get('AMAZON_REFRESH_TOKEN_EU', ''),
    'US': os.environ.get('AMAZON_REFRESH_TOKEN_NA', ''),
    'CA': os.environ.get('AMAZON_REFRESH_TOKEN_NA', ''),
    'AU': os.environ.get('AMAZON_REFRESH_TOKEN_AU', ''),
}

# Bug report SMTP
SMTP_HOST = config('SMTP_HOST', default='smtp.ionos.co.uk')
SMTP_PORT = config('SMTP_PORT', default=587, cast=int)
SMTP_USER = config('SMTP_USER', default='')
SMTP_PASSWORD = config('SMTP_PASSWORD', default='')
