package ir.rose.attendance.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import ir.rose.attendance.data.Jalali
import java.time.LocalDate

/**
 * تقویم شمسی (گام ۴) — تقویم ماهانهٔ جلالی برای انتخاب تاریخ.
 *
 * هفتهٔ ایرانی از شنبه شروع می‌شود و چیدمان کل اپ RTL است، پس ستون شنبه
 * سمت راست می‌نشیند (چیدمان مرسوم تقویم ایران). سلول‌های خالی ابتدای ماه
 * با Spacer هم‌وزن پر می‌شوند تا ستون‌ها هم‌تراز بمانند. روز امروز کادری
 * برجسته و روز انتخاب‌شده پرشدهٔ رنگ اصلی دارد. روزها با ارقام فارسی.
 */

private val WEEK_DAYS = listOf("ش", "ی", "د", "س", "چ", "پ", "ج")

/** ایندکس ستون هفتهٔ ایرانی از شنبه = ۰ (شنبه ۶ → ۰، یکشنبه ۷ → ۱، …). */
private fun weekColumn(date: LocalDate): Int = (date.dayOfWeek.value + 1) % 7

@Composable
fun JalaliCalendar(
    selected: LocalDate?,
    onPick: (LocalDate) -> Unit,
    modifier: Modifier = Modifier,
) {
    val today = remember { LocalDate.now() }
    val todayJ = remember { Jalali.toJalali(today) }
    var jy by remember { mutableStateOf(selected?.let { Jalali.toJalali(it).jy } ?: todayJ.jy) }
    var jm by remember { mutableStateOf(selected?.let { Jalali.toJalali(it).jm } ?: todayJ.jm) }

    Column(modifier = modifier) {
        // ناوبری ماه
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = androidx.compose.foundation.layout.Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = { val (y, m) = Jalali.previousMonth(jy, jm); jy = y; jm = m }) {
                Text("ماه قبل")
            }
            Text(
                "${Jalali.monthName(jm)} ${Jalali.faDigits(jy.toString())}",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
            )
            TextButton(onClick = { val (y, m) = Jalali.nextMonth(jy, jm); jy = y; jm = m }) {
                Text("ماه بعد")
            }
        }

        // سطر نام روزهای هفته (شنبه راست‌ترین)
        Row(modifier = Modifier.fillMaxWidth()) {
            WEEK_DAYS.forEach { d ->
                Text(
                    d,
                    modifier = Modifier.weight(1f),
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        val lead = weekColumn(Jalali.toGregorian(jy, jm, 1))
        val len = Jalali.monthLength(jy, jm)
        val cells: List<LocalDate?> = List(lead) { null } + (1..len).map { Jalali.toGregorian(jy, jm, it) }
        cells.chunked(7).forEach { week ->
            Row(modifier = Modifier.fillMaxWidth()) {
                week.forEach { day ->
                    DayCell(
                        day = day,
                        selected = selected,
                        today = today,
                        onPick = onPick,
                        modifier = Modifier.weight(1f),
                    )
                }
                repeat(7 - week.size) { Spacer(modifier = Modifier.weight(1f)) }
            }
        }
    }
}

@Composable
private fun DayCell(
    day: LocalDate?,
    selected: LocalDate?,
    today: LocalDate,
    onPick: (LocalDate) -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .heightIn(min = 34.dp)
            .padding(1.dp),
        contentAlignment = Alignment.Center,
    ) {
        if (day != null) {
            val isSel = day == selected
            val isToday = day == today
            val background = when {
                isSel -> MaterialTheme.colorScheme.primary
                isToday -> MaterialTheme.colorScheme.secondaryContainer
                else -> MaterialTheme.colorScheme.surface
            }
            Text(
                text = Jalali.faDigits(Jalali.toJalali(day).jd.toString()),
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(background)
                    .clickable { onPick(day) }
                    .padding(vertical = 6.dp, horizontal = 2.dp),
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.bodySmall,
                fontWeight = if (isSel || isToday) FontWeight.Bold else null,
                color = when {
                    isSel -> MaterialTheme.colorScheme.onPrimary
                    isToday -> MaterialTheme.colorScheme.onSecondaryContainer
                    else -> MaterialTheme.colorScheme.onSurface
                },
            )
        }
    }
}
