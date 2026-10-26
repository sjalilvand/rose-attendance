package ir.rose.attendance.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ir.rose.attendance.data.DayRow
import ir.rose.attendance.data.Jalali
import ir.rose.attendance.data.MeInfo
import ir.rose.attendance.data.Repository
import java.time.LocalDate

/**
 * تاریخچهٔ کارکرد (گام ۳) — سطرهای روزانهٔ محاسبه‌شده از /attendance/daily/
 * با سه بازهٔ آمادهٔ شمسی (ماه جاری / ماه گذشته / ۴۵ روز اخیر).
 *
 * سرور سطرها را مرتب نزولی می‌دهد؛ برای پرسنل چندشعبه‌ای یک سطر به‌ازای
 * هر (روز × شعبه) می‌آید که نام شعبه از پاسخ /me/ نگاشت می‌شود.
 * پنجرهٔ سرور: حداکثر ۴۵ روز، داخل ۳ ماه شمسی اخیر (تصمیم #۲ §۳۴).
 */

private enum class RangePreset(val label: String) {
    THIS_MONTH("این ماه شمسی"),
    LAST_MONTH("ماه گذشتهٔ شمسی"),
    LAST_45("۴۵ روز اخیر"),
}

private fun computeRange(preset: RangePreset, today: LocalDate): Pair<LocalDate, LocalDate> =
    when (preset) {
        RangePreset.THIS_MONTH -> {
            val j = Jalali.toJalali(today)
            Jalali.toGregorian(j.jy, j.jm, 1) to today
        }
        RangePreset.LAST_MONTH -> {
            val j = Jalali.toJalali(today)
            val (py, pm) = Jalali.previousMonth(j.jy, j.jm)
            val last = Jalali.monthLength(py, pm)
            Jalali.toGregorian(py, pm, 1) to Jalali.toGregorian(py, pm, last)
        }
        RangePreset.LAST_45 -> today.minusDays(44) to today
    }

@Composable
fun HistoryScreen(repo: Repository, onBack: () -> Unit) {
    var me by remember { mutableStateOf<MeInfo?>(null) }
    var rows by remember { mutableStateOf<List<DayRow>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var presetName by rememberSaveable { mutableStateOf(RangePreset.THIS_MONTH.name) }
    val preset = remember(presetName) { RangePreset.valueOf(presetName) }
    val today = remember { LocalDate.now() }
    val (from, to) = remember(preset) { computeRange(preset, today) }

    LaunchedEffect(from, to) {
        loading = true
        error = null
        try {
            me = repo.meInfo()
            rows = repo.call { repo.api.daily(from.toString(), to.toString()) }.results
        } catch (e: Exception) {
            error = friendlyError(e)
        } finally {
            loading = false
        }
    }

    // پرسنل چندشعبه‌ای: شناسهٔ شعبهٔ سطر روزانه ← نام شعبه از /me/
    fun branchName(id: Long?): String? {
        if (id == null) return null
        val names = me?.branches?.filter { it.id == id }?.map { it.name }
        return when (names?.size) {
            null, 0 -> null
            1 -> names.first()
            else -> names.first() // شعبه تکراری در /me/ (اصلی+مجاز) — یک نام کافی است
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("تاریخچهٔ کارکرد", style = MaterialTheme.typography.titleLarge)
            TextButton(onClick = onBack) { Text("بازگشت") }
        }

        // بازه‌های آماده
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            RangePreset.entries.forEach { p ->
                OutlinedButton(
                    onClick = { presetName = p.name },
                    enabled = preset != p && !loading,
                ) { Text(p.label) }
            }
        }

        Text(
            "از ${Jalali.formatJalali(from)} تا ${Jalali.formatJalali(to)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        when {
            loading -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
            ) { CircularProgressIndicator() }

            error != null -> Card(Modifier.fillMaxWidth()) {
                Text(
                    error!!,
                    modifier = Modifier.padding(16.dp),
                    color = MaterialTheme.colorScheme.error,
                )
            }

            rows.isEmpty() -> Card(Modifier.fillMaxWidth()) {
                Text(
                    "در این بازه ترددی ثبت نشده است.",
                    modifier = Modifier.padding(16.dp),
                )
            }

            else -> {
                val totalWork = rows.sumOf { it.accepted_work_minutes }
                val totalLate = rows.sumOf { it.late_minutes }
                val lateDays = rows.count { it.late_minutes > 0 }
                val absenceDays = rows.count { it.absence_minutes > 0 }
                val totalLeave = rows.sumOf { it.leave_minutes_by_type.values.sum() }
                Card(Modifier.fillMaxWidth()) {
                    Column(
                        Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text("خلاصهٔ بازه", style = MaterialTheme.typography.titleMedium)
                        Text("کار پذیرفته: ${minutesToHM(totalWork)}")
                        Text(
                            "تأخیر: ${minutesToHM(totalLate)}" +
                                (if (lateDays > 0) " در ${Jalali.faDigits(lateDays.toString())} روز" else "") +
                                " — غیبت: ${Jalali.faDigits(absenceDays.toString())} روز",
                        )
                        if (totalLeave > 0) Text("مرخصی: ${minutesToHM(totalLeave)}")
                    }
                }

                rows.forEach { row ->
                    val date = runCatching { LocalDate.parse(row.shift_date) }.getOrNull()
                    Card(Modifier.fillMaxWidth()) {
                        Column(
                            Modifier.padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(
                                    date?.let { Jalali.formatJalaliLong(it) } ?: (row.shift_date ?: "—"),
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.Bold,
                                )
                                if (row.is_holiday) {
                                    Text(
                                        "تعطیل",
                                        color = MaterialTheme.colorScheme.error,
                                        style = MaterialTheme.typography.labelMedium,
                                    )
                                }
                            }
                            branchName(row.branch)?.let {
                                Text(
                                    "شعبه: $it",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Text(
                                "ورود: ${timeHM(row.first_in)} — خروج: ${timeHM(row.last_out)}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                            val chips = buildList {
                                if (row.accepted_work_minutes > 0) add("کار: ${minutesToHM(row.accepted_work_minutes)}")
                                if (row.late_minutes > 0) add("تأخیر: ${minutesToHM(row.late_minutes)}")
                                if (row.early_leave_minutes > 0) add("خروج قبل از موعد: ${minutesToHM(row.early_leave_minutes)}")
                                if (row.overtime_approved_minutes > 0) add("اضافه‌کاری: ${minutesToHM(row.overtime_approved_minutes)}")
                                val leaveMin = row.leave_minutes_by_type.values.sum()
                                if (leaveMin > 0) add("مرخصی: ${minutesToHM(leaveMin)}")
                                if (row.mission_minutes > 0) add("مأموریت: ${minutesToHM(row.mission_minutes)}")
                                if (row.absence_minutes > 0) add("غیبت: ${minutesToHM(row.absence_minutes)}")
                                if (row.incomplete_sessions > 0) add("جلسهٔ باز: ${Jalali.faDigits(row.incomplete_sessions.toString())}")
                            }
                            if (chips.isEmpty()) {
                                Text(
                                    "بدون رویداد قابل محاسبه",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            } else {
                                Text(chips.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }
        }
    }
}
