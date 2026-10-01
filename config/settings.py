import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # pasta onde está o manage.py
BOT_ROOT = BASE_DIR / "v_1.0"                          # onde ficam core/, interface/, database/, api/

# Carrega o .env (BINANCE_API_KEY / BINANCE_API_SECRET) sem precisar de biblioteca extra
for _env in (BASE_DIR / ".env", BOT_ROOT / ".env"):
    if _env.exists():
        for line in _env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-key-troque-se-for-expor-na-rede")
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]             # só acessível neste computador

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,                                  # encontra dashboard/templates/
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]

DATABASES = {}                                         # o bot usa o próprio SQLite (v_1.0/database)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_TZ = False
STATIC_URL = "static/"
