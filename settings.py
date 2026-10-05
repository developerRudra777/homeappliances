"""
Django settings for appliances_core project.
"""

import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env with pure-python fallback
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    env_file = BASE_DIR / '.env'
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        k, v = k.strip(), v.strip()
                        if k not in os.environ:
                            os.environ[k] = v
        except (OSError, UnicodeError):
            pass

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured('SECRET_KEY must be set in the environment.')
DEBUG = True
ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # The single local app
    'store.apps.StoreConfig',

     

]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    

    
]

ROOT_URLCONF = 'appliances_core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_processors.cart_context',
                'store.context_processors.categories_processor',
            ],
        },
    },
]

WSGI_APPLICATION = 'appliances_core.wsgi.application'

# Database Configuration - Using SQLite (db.sqlite3)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (Product uploads, banners)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Session Configuration for Shopping Cart
SESSION_COOKIE_AGE = 86400 * 7  # 7 days
CART_SESSION_ID = 'appliance_cart'

# Authentication redirects
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'store:home'
LOGOUT_REDIRECT_URL = 'store:home'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Bootstrap messages tags mapping
from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG: 'secondary',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

# Email Configuration (Console fallback for dev, SMTP ready for Gmail)
# Email Configuration (Reads securely from environment variables)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST =  'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 15
EMAIL_HOST_USER = 'rudrasahasantipur39@gmail.com'
EMAIL_HOST_PASSWORD = 'olqcjmovcxifeqlx'
DEFAULT_FROM_EMAIL =  'HomeHub Appliances <rudrasahasantipur39@gmail.com>'

# Payment Gateway (Razorpay - Automatically reads Live or Test keys from .env)
RAZORPAY_KEY_ID = 'rzp_test_Th6oNVNNyH8BsU'
RAZORPAY_KEY_SECRET = 'xx6733IfDpamhdawZFMq3A8I'



# ---------------------------------------------------------------------------
# DJANGO-ALLAUTH MODERN CONFIGURATION (0 Warnings)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# SOCIAL ACCOUNT PROVIDERS CONFIGURATION
# ---------------------------------------------------------------------------
