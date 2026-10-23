# اپ اندروید رز سفید — گام ۲

کلاینت بومی Kotlin/Jetpack Compose برای همان بک‌اند `/api/v1` که PWA مصرف می‌کند.
گام ۱ (ورود، ثبت ورود/خروج، ماندهٔ مرخصی) + گام ۲ (ثبت تردد با موقعیت مکانی
FusedLocationProvider و اعلان‌های زندهٔ WebSocket) فعال است.

## ساختار

```
android/
├── app/src/main/java/ir/rose/attendance/
│   ├── MainActivity.kt            # نقطهٔ ورود، قفل RTL، سوییچ Login/Home
│   ├── data/
│   │   ├── Models.kt              # DTO های kotlinx-serialization (قرارداد api.ts)
│   │   ├── Api.kt                 # Retrofit + interceptor توکن + refresh یک‌باره روی 401 + افست ساعت + URL سوکت
│   │   ├── LocationSource.kt      # FusedLocationProvider با مهلت کوتاه؛ خطا → punch بدون GPS
│   │   ├── LiveSocket.kt          # اعلان زندهٔ /ws/notifications/ با backoff + refresh
│   │   └── TokenStore.kt          # SharedPreferences نگهداری access/refresh
│   └── ui/
│       ├── LoginScreen.kt         # ورود username/password
│       ├── HomeScreen.kt          # کارت امروز، ثبت ورود/خروج با موقعیت، اعلان‌ها، ماندهٔ مرخصی
│       └── theme/Theme.kt         # تم M3 (رنگ برند در گام هویت بصری)
├── app/build.gradle.kts           # Compose BOM 2024.12، Kotlin 2.0.21، AGP 8.7.3، play-services-location
├── ci/android-build.yml           # دستور کار CI (فعال‌سازی یک‌باره — بخش بعد)
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

## رفتار موقعیت مکانی (مصوبهٔ §34)

- اولین ثبت تردد، دیالوگ مجوز موقعیت را می‌گیرد؛ رد مجوز = ثبت بدون GPS
  (سرور برچسب UNAVAILABLE می‌زند — رسیدگی، نه رد).
- گرفتن موقعیت با `PRIORITY_HIGH_ACCURACY` و مهلت ۸ ثانیه؛ اگر نرسید، رویداد
  بدون مختصات می‌رود.
- پاسخ سرور («در محدوده»، «خارج از محدوده»، «دقت پایین») به‌همراه نتیجهٔ ثبت
  نمایش داده می‌شود — برچسب است، رد نیست.
- افست ساعت دستگاه نسبت به سرور از `server_time` پاسخ `/me/` اندازه‌گیری و
  همراه هر تردد ارسال می‌شود تا قاعدهٔ CLOCK_SKEW دقیق تصمیم بگیرد.

## اعلان‌های زنده

اتصال به `/ws/notifications/?token=…` با backoff نمایی محدود (سقف ۱۵ ثانیه)
و یک تلاش refresh توکن پس از هر قطعی ۴۰۱. تصمیم‌های رسیدگی تردد و اضافه‌کاری
کارت «امروز» را بی‌درنگ تازه می‌کنند؛ ۲۰ اعلان آخر در کارت «اعلان‌های زنده» است.

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

1. **گام ۱ (اسکلت)** — ورود، ثبت تردد، ماندهٔ مرخصی ✔
2. **گام ۲** — ثبت تردد با موقعیت مکانی (FusedLocationProvider) + اعلان زندهٔ
   WebSocket ✔ (رویداد بدون GPS طبق مصوبه NEEDS_REVIEW می‌شود؛ اپ موقعیت را
   ترجیحاً می‌فرستد و برچسب سرور را شفاف نشان می‌دهد)
3. تاریخچهٔ کارکرد + خلاصهٔ ماه (Jalali)
4. درخواست مرخصی/مأموریت + رسیدگی مدیران
5. ساخت release-signed با keystore اختصاصی + مهاجرت توکن به DataStore رمزنگاری‌شده
