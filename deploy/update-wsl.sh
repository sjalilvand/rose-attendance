#!/usr/bin/env bash
# بروزرسانی و اجرای سامانه رز سفید در حالت HTTP (بدون SSL) — برای WSL2/لینوکس
# فلوی استاندارد: git pull → آماده‌سازی secrets و .env → build → up -d → migrate
# مبتنی بر compose.http.yml (پورت پیش‌فرض 8080، بدون 443 و بدون گواهی TLS)
#
# اجرا:   bash deploy/update-wsl.sh
# پیش‌نیاز: git و docker (docker compose plugin) داخل همین محیط نصب باشند.

set -euo pipefail

# رفتن به ریشه مخزن (یک پوشه بالاتر از deploy/)
cd "$(dirname "$0")/.."

echo ''
echo '== بروزرسانی سامانه رز سفید — حالت HTTP روی پورت 8080 =='

# --- ۱) دریافت آخرین تغییرات -------------------------------------------------
echo '-- ۱/۴ دریافت تغییرات از origin/main --'
git pull --ff-only origin main

# --- ۲) آماده‌سازی secrets و .env ---------------------------------------------
echo '-- ۲/۴ آماده‌سازی secrets و .env --'
mkdir -p secrets deploy/tls
for name in django_secret db_password; do
  if [ ! -f "secrets/${name}.txt" ]; then
    openssl rand -hex 48 > "secrets/${name}.txt"
    echo "  ساخته شد: secrets/${name}.txt (مقدار تصادفی)"
  fi
done

if [ ! -f .env ]; then
  cp .env.example .env
  echo '  .env از روی .env.example ساخته شد.'
fi

# تضمین مقادیر لازم برای IP سرور و پورت 8080
ensure_key_value() {
  local key="$1"; local want="$2"
  if grep -q "^${key}=" .env; then
    local current
    current="$(grep "^${key}=" .env | head -1 | cut -d= -f2-)"
    if ! echo ",${current}," | grep -q ",${want},"; then
      sed -i "s|^${key}=.*|${key}=${current},${want}|" .env
      echo "  .env: ${want} به ${key} اضافه شد."
    fi
  else
    echo "${key}=${want}" >> .env
    echo "  .env: ${key} اضافه شد (${want})."
  fi
}
ensure_key_value DJANGO_ALLOWED_HOSTS '130.185.73.157'
ensure_key_value DJANGO_ALLOWED_HOSTS 'localhost'
ensure_key_value DJANGO_ALLOWED_HOSTS '127.0.0.1'
ensure_key_value DJANGO_CSRF_TRUSTED_ORIGINS 'http://130.185.73.157:8080'
ensure_key_value DJANGO_CSRF_TRUSTED_ORIGINS 'http://localhost'

# --- ۳) ساخت و اجرای سرویس‌ها --------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo 'خطا: docker یافت نشد. ابتدا Docker Engine را نصب کنید.' >&2
  exit 1
fi

echo '-- ۳/۴ ساخت و اجرای سرویس‌ها (compose.http.yml) --'
docker compose -f compose.http.yml build
docker compose -f compose.http.yml up -d

# --- ۴) مهاجرت دیتابیس --------------------------------------------------------
echo '-- ۴/۴ مهاجرت دیتابیس --'
docker compose -f compose.http.yml run --rm migrate

echo ''
echo 'بروزرسانی (حالت HTTP) کامل شد ✓'
echo 'سلامت سرویس‌ها : http://130.185.73.157:8080/api/v1/health/'
echo 'وب‌اپ (PWA)   : http://130.185.73.157:8080/'
echo ''
echo 'ساخت کاربر مدیر اولیه (اختیاری):'
echo '  DJANGO_SUPERUSER_PASSWORD="رمز-دلخواه" docker compose -f compose.http.yml run --rm migrate python manage.py createsuperuser --noinput --username admin'
