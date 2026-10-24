package ir.rose.attendance.ui

import java.time.LocalDate
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import ir.rose.attendance.data.Jalali
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import retrofit2.HttpException

/** منطقهٔ زمانی سازمان — همهٔ بازه‌های مرخصی با این افست ارسال می‌شود. */
val TEHRAN: ZoneId = ZoneId.of("Asia/Tehran")

private val HHMM: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")

/** «۲ ساعت و ۳۰ دقیقه» — صفر به شکل «۰». */
fun minutesToHM(m: Int): String {
    if (m <= 0) return Jalali.faDigits("0")
    val h = m / 60
    val min = m % 60
    val parts = mutableListOf<String>()
    if (h > 0) parts.add(Jalali.faDigits(h.toString()) + " ساعت")
    if (min > 0) parts.add(Jalali.faDigits(min.toString()) + " دقیقه")
    return parts.joinToString(" و ")
}

/** HH:mm از رشتهٔ ISO (زمان سرور) — خالی → «—». */
fun timeHM(iso: String?): String {
    if (iso.isNullOrBlank()) return "—"
    return runCatching {
        val t = OffsetDateTime.parse(iso).toLocalTime().truncatedTo(ChronoUnit.MINUTES)
        Jalali.faDigits(t.format(HHMM))
    }.getOrDefault("—")
}

/** ۱۴۰۵/۰۸/۰۲ ۰۹:۰۰ از رشتهٔ ISO. */
fun jalaliDateTime(iso: String?): String {
    if (iso.isNullOrBlank()) return "—"
    return runCatching {
        val odt = OffsetDateTime.parse(iso)
        "${Jalali.formatJalali(odt.toLocalDate())} ${Jalali.faDigits(odt.toLocalTime().truncatedTo(ChronoUnit.MINUTES).format(HHMM))}"
    }.getOrDefault("—")
}

/** برچسب وضعیت درخواست/پاره — همان چهار وضعیت enum سرور. */
fun requestStatusLabel(s: String): String = when (s) {
    "PENDING" -> "در انتظار"
    "APPROVED" -> "تأییدشده"
    "REJECTED" -> "ردشده"
    "CANCELLED" -> "لغوشده"
    else -> s
}

/** استخراج پیام فارسی سرور از بدنهٔ خطا؛ در غیر این صورت پیام عمومی. */
fun friendlyError(e: Exception): String {
    if (e is HttpException) {
        val body = runCatching { e.response()?.errorBody()?.string() }.getOrNull()
        if (!body.isNullOrBlank()) {
            runCatching {
                val obj = Json.parseToJsonElement(body).jsonObject
                obj["detail"]?.let { return it.jsonPrimitive.content }
                // خطاهای فیلدی DRF: {"starts_at": ["..."]}
                for ((_, v) in obj) {
                    if (v is JsonArray && v.jsonArray.isNotEmpty()) {
                        return v.jsonArray.first().jsonPrimitive.content
                    }
                }
            }
        }
        return "خطای سرور (کد ${Jalali.faDigits(e.code().toString())})"
    }
    return "ارتباط با سرور برقرار نشد — دوباره تلاش کنید."
}

/** «شنبه ۲ آبان ۱۴۰۵» برای تاریخ شیفتی ISO (YYYY-MM-DD). */
fun jalaliDayLong(isoDate: String?): String {
    if (isoDate.isNullOrBlank()) return "—"
    return runCatching {
        Jalali.formatJalaliLong(LocalDate.parse(isoDate))
    }.getOrDefault(isoDate)
}

/** نقش‌های تصمیم‌گیر رسیدگی — همان قرارداد MANAGER_ROLES سرور (core/rbac). */
val MANAGER_ROLES = setOf("BRANCH_MANAGER", "REGION_MANAGER", "HR", "ADMIN")

fun hasManagerRole(roles: List<String>?): Boolean =
    roles?.any { it in MANAGER_ROLES } == true

/**
 * «۱۴۰۵/۰۸/۰۲» (با ارقام فارسی یا لاتین) → LocalDate؛ نامعتبر → null.
 * برای فیلدهای متنی تاریخ جلالی (فرم مرخصی، رسیدگی تردد).
 */
fun parseJalaliText(raw: String?): LocalDate? {
    if (raw.isNullOrBlank()) return null
    val parts = Jalali.latinDigits(raw.trim()).split('/')
    if (parts.size != 3) return null
    val y = parts[0].trim().toIntOrNull() ?: return null
    val m = parts[1].trim().toIntOrNull() ?: return null
    val d = parts[2].trim().toIntOrNull() ?: return null
    return Jalali.parse(y, m, d)
}

/** «۰۹:۰۰» → LocalTime؛ نامعتبر → null (ارقام فارسی پذیرفته می‌شود). */
fun parseHmText(raw: String?): LocalTime? {
    if (raw.isNullOrBlank()) return null
    val s = Jalali.latinDigits(raw.trim())
    val m = Regex("^(\\d{1,2}):(\\d{2})$").find(s) ?: return null
    val hh = m.groupValues[1].toInt()
    val mm = m.groupValues[2].toInt()
    if (hh !in 0..23 || mm !in 0..59) return null
    return LocalTime.of(hh, mm)
}
