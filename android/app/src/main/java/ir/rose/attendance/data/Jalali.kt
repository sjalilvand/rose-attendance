package ir.rose.attendance.data

import java.time.DayOfWeek
import java.time.LocalDate

/**
 * تقویم جلالی — پورت تحت‌اللفظی الگوریتم jalaali-js (بدون وابستگی).
 *
 * الگوریتم پیش از ورود به مخزن با سوئیپ روزبه‌روز ۱۹۹۰..۲۰۴۰ میلادی و
 * ۱۳۸۰..۱۴۷۰ شمسی (~۵۲ هزار روز) در برابر کتابخانهٔ jdatetime — همان مرجعی
 * که سرور Django استفاده می‌کند — صحت‌سنجی شده است:
 * div = تقسیم صحیح به سمت صفر (مانند Int در Kotlin)، mod = باقیماندهٔ هم‌علامت
 * dividand (مانند JS). روز کبیسه و طول ماه‌های ۲۹/۳۰/۳۱ دقیقاً منطبق است.
 */
object Jalali {

    data class JDate(val jy: Int, val jm: Int, val jd: Int)

    private val BREAKS = intArrayOf(
        -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
        1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178,
    )

    private fun div(a: Int, b: Int): Int = a / b
    private fun mod(a: Int, b: Int): Int = a - (a / b) * b

    private class Cal(val leap: Int, val gy: Int, val march: Int)

    private fun jalCal(jy: Int): Cal {
        val bl = BREAKS.size
        val gy = jy + 621
        var leapJ = -14
        var jp = BREAKS[0]
        var jump = 0
        for (i in 1 until bl) {
            val jm = BREAKS[i]
            jump = jm - jp
            if (jy < jm) break
            leapJ += div(jump, 33) * 8 + div(mod(jump, 33), 4)
            jp = jm
        }
        var n = jy - jp
        leapJ += div(n, 33) * 8 + div(mod(n, 33) + 3, 4)
        if (mod(jump, 33) == 4 && jump - n == 4) leapJ += 1
        val leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150
        val march = 20 + leapJ - leapG
        if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33
        var leap = mod(mod(n + 1, 33) - 1, 4)
        if (leap == -1) leap = 4
        return Cal(leap, gy, march)
    }

    private fun g2d(gy: Int, gm: Int, gd: Int): Int {
        var d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4) +
            div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408
        d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752
        return d
    }

    private fun d2g(jdn: Int): Triple<Int, Int, Int> {
        var j = 4 * jdn + 139361631
        j += div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
        val i = div(mod(j, 1461), 4) * 5 + 308
        val gd = div(mod(i, 153), 5) + 1
        val gm = mod(div(i, 153), 12) + 1
        val gy = div(j, 1461) - 100100 + div(8 - gm, 6)
        return Triple(gy, gm, gd)
    }

    private fun j2d(jy: Int, jm: Int, jd: Int): Int {
        val r = jalCal(jy)
        return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1
    }

    private fun d2j(jdn: Int): JDate {
        val gy = d2g(jdn).first
        var jy = gy - 621
        val r = jalCal(jy)
        val jdn1f = g2d(gy, 3, r.march)
        var k = jdn - jdn1f
        if (k >= 0) {
            if (k <= 185) return JDate(jy, 1 + div(k, 31), mod(k, 31) + 1)
            k -= 186
        } else {
            jy -= 1
            k += 179
            if (r.leap == 1) k += 1
        }
        return JDate(jy, 7 + div(k, 30), mod(k, 30) + 1)
    }

    fun toJalali(date: LocalDate): JDate =
        d2j(g2d(date.year, date.monthValue, date.dayOfMonth))

    fun toGregorian(jy: Int, jm: Int, jd: Int): LocalDate {
        val (gy, gm, gd) = d2g(j2d(jy, jm, jd))
        return LocalDate.of(gy, gm, gd)
    }

    fun isLeapJalali(jy: Int): Boolean = jalCal(jy).leap == 0

    /** طول ماه جلالی: ۶ ماه اول ۳۱، ۵ ماه بعد ۳۰، اسفند ۲۹ یا ۳۰ (کبیسه). */
    fun monthLength(jy: Int, jm: Int): Int =
        if (jm <= 6) 31
        else if (jm <= 11) 30
        else if (isLeapJalali(jy)) 30 else 29

    fun isValidJalali(jy: Int, jm: Int, jd: Int): Boolean =
        jy in 1300..1500 && jm in 1..12 && jd in 1..monthLength(jy, jm)

    /** تاریخ شمسی معتبر → میلادی؛ نامعتبر → null (برای ورودی فرم مرخصی). */
    fun parse(jy: Int, jm: Int, jd: Int): LocalDate? =
        if (isValidJalali(jy, jm, jd)) toGregorian(jy, jm, jd) else null

    fun previousMonth(jy: Int, jm: Int): Pair<Int, Int> =
        if (jm > 1) jy to (jm - 1) else (jy - 1) to 12

    // ------------------------------------------------------------- نام‌ها

    private val MONTH_NAMES = listOf(
        "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
        "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
    )

    fun monthName(jm: Int): String = MONTH_NAMES[jm - 1]

    fun weekDayName(date: LocalDate): String = when (date.dayOfWeek) {
        DayOfWeek.SATURDAY -> "شنبه"
        DayOfWeek.SUNDAY -> "یکشنبه"
        DayOfWeek.MONDAY -> "دوشنبه"
        DayOfWeek.TUESDAY -> "سه‌شنبه"
        DayOfWeek.WEDNESDAY -> "چهارشنبه"
        DayOfWeek.THURSDAY -> "پنجشنبه"
        DayOfWeek.FRIDAY -> "جمعه"
    }

    // -------------------------------------------------------- قالب‌بندی

    /** ارقام لاتین → فارسی. */
    fun faDigits(s: String): String = buildString(s.length) {
        for (c in s) append(if (c in '0'..'9') ('۰' + (c - '0')) else c)
    }

    /** ارقام فارسی/عربی ورودی کاربر → لاتین (برای فیلدهای عددی فرم). */
    fun latinDigits(s: String): String = buildString(s.length) {
        for (c in s) append(
            when (c) {
                in '۰'..'۹' -> ('0' + (c - '۰'))
                in '٠'..'٩' -> ('0' + (c - '٠'))
                else -> c
            },
        )
    }

    /** ۱۴۰۵/۰۸/۰۲ */
    fun formatJalali(date: LocalDate): String {
        val j = toJalali(date)
        return faDigits("%04d/%02d/%02d".format(j.jy, j.jm, j.jd))
    }

    /** شنبه ۲ آبان ۱۴۰۵ */
    fun formatJalaliLong(date: LocalDate): String {
        val j = toJalali(date)
        return "${weekDayName(date)} ${faDigits(j.jd.toString())} ${monthName(j.jm)} ${faDigits(j.jy.toString())}"
    }
}
