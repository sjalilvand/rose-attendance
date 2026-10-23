# اپ اندروید رز سفید — اسکلت فاز ۱

کلاینت بومی Kotlin/Jetpack Compose برای همان بک‌اند `/api/v1` که PWA مصرف می‌کند.
این اسکلت عمداً کوچک است: ورود (JWT) + ثبت ورود/خروج + ماندهٔ مرخصی؛ بقیهٔ
قابلیت‌ها طبق نقشهٔ راه اضافه می‌شوند.

## ساختار

```
android/
├── app/src/main/java/ir/rose/attendance/
│   ├── MainActivity.kt            # نقطهٔ ورود، قفل RTL، سوییچ Login/Home
│   ├── data/
│   │   ├── Models.kt              # DTO های kotlinx-serialization (قرارداد api.ts)
│   │   ├── Api.kt                 # Retrofit + interceptor توکن + refresh یک‌باره روی 401
│   │   └── TokenStore.kt          # SharedPreferences نگهداری access/refresh
│   └── ui/
│       ├── LoginScreen.kt         # ورود username/password
│       ├── HomeScreen.kt          # کارت امروز، ثبت ورود/خروج، ماندهٔ مرخصی
│       └── theme/Theme.kt         # تم M3 (رنگ برند در گام هویت بصری)
├── app/build.gradle.kts           # Compose BOM 2024.12، Kotlin 2.0.21، AGP 8.7.3
└── gradle/wrapper/…               # Gradle 8.10.2
```

## ساخت و اجرا

- **Android Studio** (Koudlin توصیه‌شده): پوشهٔ `android/` را باز کنید؛ Studio
  wrapper را می‌سازد و sync می‌کند. سپس Run.
- **خط فرمان**: `gradle :app:assembleDebug` (Gradle 8.10.2 + JDK 17).
- **بدون نصب هیچ‌چیز**: با فعال‌سازی یک‌بارهٔ CI (بخش بعدی)، هر push که
  مسیر `android/**` را تغییر دهد باعث می‌شود GitHub Actions فایل
  `app-debug.apk` را در آرتیفکت‌های همان ران بسازد و نگه دارد.

## فعال‌سازی CI ساخت APK (یک‌بار)

دستور کار آماده در `android/ci/android-build.yml` قرار دارد (Gradle 8.10.2 +
JDK 17 → `app-debug.apk`). برای فعال‌سازی کافی است همین فایل یک‌بار در مسیر
`.github/workflows/android.yml` مخزن قرار بگیرد:

1. در گیت‌هاب، صفحهٔ مخزن را باز کنید و **Add file ← Create new file** را بزنید.
2. نام فایل را دقیقاً `.github/workflows/android.yml` بنویسید (با تایپ `/`
   پوشه ساخته می‌شود).
3. محتوای `android/ci/android-build.yml` را کپی و Paste کنید و **Commit** بزنید.

از این پس هر تغییر در `android/**` (یا اجرای دستی **Run workflow**) یک ران
ساخت می‌سازد که APK را در بخش **Actions ← ران ← Artifacts** قرار می‌دهد.
راه دیگر، قرار دادن فایل به‌صورت محلی با توکن دارای دسترسی `workflow` است؛
روش وب‌اینترفیس ساده‌ترین است و به هیچ توکنی نیاز ندارد.

## تنظیم آدرس سرور

مقدار `API_BASE` در `app/build.gradle.kts`:

| محیط | مقدار |
|------|-------|
| شبیه‌ساز اندروید → سرور localhost میزبان | `http://10.0.2.2/` |
| گوشی روی همان LAN | `http://<IP-سرور>/` |
| انتشار | آدرس HTTPS دامنهٔ واقعی |

در حال حاضر `usesCleartextTraffic="true"` است تا تست LAN ساده باشد؛ پیش از
انتشار باید TLS فعال و این پرچم حذف شود.

## قرارداد سرور مصرف‌شده فعلاً

| Endpoint | کاربرد |
|----------|--------|
| `POST /api/v1/auth/token/` | ورود با `platform: ANDROID` |
| `POST /api/v1/auth/token/refresh/` | تمدید access |
| `GET /api/v1/me/` | پروفایل + شعب مجاز |
| `GET /api/v1/attendance/daily/today/` | کارت امروز |
| `POST /api/v1/attendance/events/punch/` | ثبت ورود/خروج |
| `GET /api/v1/leaves/ledger/balances/` | ماندهٔ مرخصی |

## نقشهٔ راه

1. **فاز فعلی (اسکلت)** — ورود، ثبت تردد، ماندهٔ مرخصی ✔
2. ثبت تردد با موقعیت مکانی (FusedLocationProvider + دقت) — رویداد بدون GPS طبق
   مصوبه رد نمی‌شود ولی NEEDS_REVIEW می‌شود؛ اپ باید ترجیحاً موقعیت بفرستد
3. تاریخچهٔ کارکرد + خلاصهٔ ماه (Jalali)
4. درخواست مرخصی/مأموریت + رسیدگی مدیران
5. اعلان زندهٔ WebSocket (همان `user-<id>` گروه Channels)
6. ساخت release-signed با keystore اختصاصی + مهاجرت توکن به DataStore رمزنگاری‌شده
