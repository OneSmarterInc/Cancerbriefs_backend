import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = os.environ['SECRET_KEY']

DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        'ALLOWED_HOSTS',
        'backend.cyberbriefs.org,localhost,127.0.0.1,100.60.190.113,cyberbriefs.org,www.cyberbriefs.org'
    ).split(',')
    if host.strip()
]

if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get(
        'SECURE_SSL_REDIRECT',
        'False'
    ).lower() == 'true'

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    SECURE_CONTENT_TYPE_NOSNIFF = True

    X_FRAME_OPTIONS = 'DENY'

    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

    SECURE_PROXY_SSL_HEADER = (
        'HTTP_X_FORWARDED_PROTO',
        'https'
    )


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework.authtoken',

    'corsheaders',

    'news_api',
]


MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',

    'django.middleware.security.SecurityMiddleware',
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


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',

        'NAME': os.environ.get(
            'DB_NAME',
            'cyberbrief_db'
        ),

        'USER': os.environ.get(
            'DB_USER',
            'postgres'
        ),

        'PASSWORD': os.environ['DB_PASSWORD'],

        'HOST': os.environ.get(
            'DB_HOST',
            'localhost'
        ),

        'PORT': os.environ.get(
            'DB_PORT',
            '5432'
        ),
    }
}


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'America/New_York'

USE_I18N = True

USE_TZ = True


STATIC_URL = '/static/'

STATIC_ROOT = os.path.join(
    BASE_DIR,
    'static'
)


MEDIA_URL = '/media/'

MEDIA_ROOT = os.path.join(
    BASE_DIR,
    'media'
)


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

APPEND_SLASH = True


REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],

    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],

    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
    },
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },

    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',

        'OPTIONS': {
            'min_length': 8,
        },
    },

    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },

    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOW_CREDENTIALS = True


CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'https://www.cyberbriefs.org',
    'https://backend.cyberbriefs.org',
    'http://backend.cyberbriefs.org',
    'https://cyberbrief-new-15-sep-2026.vercel.app',
]


env_cors = os.environ.get(
    'CORS_ALLOWED_ORIGINS',
    ''
)

if env_cors and env_cors != '*':
    CORS_ALLOWED_ORIGINS.extend(
        [
            origin.strip()
            for origin in env_cors.split(',')
            if origin.strip()
            and origin.strip() not in CORS_ALLOWED_ORIGINS
        ]
    )


CSRF_TRUSTED_ORIGINS = [
    'https://backend.cyberbriefs.org',
    'http://backend.cyberbriefs.org',
    'https://cyberbrief-new-15-sep-2026.vercel.app',
]


CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]