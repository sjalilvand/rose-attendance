package ir.rose.attendance.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import ir.rose.attendance.data.BalancesResp
import ir.rose.attendance.data.CancelReq
import ir.rose.attendance.data.Jalali
import ir.rose.attendance.data.LeaveSubmitReq
import ir.rose.attendance.data.LeaveTypeRow
import ir.rose.attendance.data.MyRequestRow
import ir.rose.attendance.data.Repository
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import kotlinx.coroutines.launch

/**
 * درخواست مرخصی (گام ۳) — همان قرارداد POST /requests/leave/ که PWA مصرف
 * می‌کند: نوع مرخصی فعال، بازهٔ شروع/پایان ISO با منطقهٔ زمانی تهران
 * (Asia/Tehran) و توضیح اختیاری؛ سرور بازه را خودکار بین شعب تقسیم و
 * ماندهٔ کافی را کنترل می‌کند. لغو درخواست PENDING هم اینجاست.
 *
 * تاریخ‌ها با ورودی عددی جلالی گرفته می‌شوند (سال/ماه/روز) تا کاربر
 * ایرانی با تقویم میلادی سردرگم نشود؛ اعتبار روز با طول واقعی ماه
 * (۲۹/۳۰/۳۱) کنترل و کنار فرم به شکل بلند نمایش داده می‌شود.
 */

private fun parseJalaliDate(y: String, m: String, d: String): LocalDate? {
    val iy = Jalali.latinDigits(y.trim()).toIntOrNull() ?: return null
    val im = Jalali.latinDigits(m.trim()).toIntOrNull() ?: return null
    val id = Jalali.latinDigits(d.trim()).toIntOrNull() ?: return null
    return Jalali.parse(iy, im, id)
}

@Composable
fun LeaveScreen(repo: Repository, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()

    var types by remember { mutableStateOf<List<LeaveTypeRow>>(emptyList()) }
    var requests by remember { mutableStateOf<List<MyRequestRow>>(emptyList()) }
    var balances by remember { mutableStateOf<BalancesResp?>(null) }

    var selectedCode by remember { mutableStateOf<String?>(null) }
    val todayJ = remember { Jalali.toJalali(LocalDate.now()) }
    var startY by remember { mutableStateOf(todayJ.jy.toString()) }
    var startM by remember { mutableStateOf(todayJ.jm.toString()) }
    var startD by remember { mutableStateOf(todayJ.jd.toString()) }
    var startTime by remember { mutableStateOf("09:00") }
    var endY by remember { mutableStateOf(todayJ.jy.toString()) }
    var endM by remember { mutableStateOf(todayJ.jm.toString()) }
    var endD by remember { mutableStateOf(todayJ.jd.toString()) }
    var endTime by remember { mutableStateOf("17:00") }
    var description by remember { mutableStateOf("") }
    // تقویم شمسی (گام ۴) — انتخاب بصری تاریخ در کنار ورودی عددی
    var showStartCal by remember { mutableStateOf(false) }
    var showEndCal by remember { mutableStateOf(false) }

    var loading by remember { mutableStateOf(true) }
    var busy by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var cancelTarget by remember { mutableStateOf<MyRequestRow?>(null) }

    suspend fun reloadAll() {
        types = repo.call { repo.api.leaveTypes() }.results
        if (selectedCode == null) selectedCode = types.firstOrNull()?.code
        requests = repo.call { repo.api.myRequests() }.results
        balances = runCatching { repo.call { repo.api.balances() } }.getOrNull()
    }

    LaunchedEffect(Unit) {
        try {
            reloadAll()
        } catch (e: Exception) {
            error = friendlyError(e)
        } finally {
            loading = false
        }
    }

    fun submit() {
        if (busy || selectedCode == null) return
        val startDate = parseJalaliDate(startY, startM, startD)
        val endDate = parseJalaliDate(endY, endM, endD)
        val st = parseHmText(startTime)
        val et = parseHmText(endTime)
        if (startDate == null) { error = "تاریخ شروع نامعتبر است (روز را با طول ماه چک کنید)."; return }
        if (endDate == null) { error = "تاریخ پایان نامعتبر است."; return }
        if (st == null) { error = "ساعت شروع را به شکل ۰۹:۰۰ وارد کنید."; return }
        if (et == null) { error = "ساعت پایان را به شکل ۱۷:۰۰ وارد کنید."; return }
        val startLdt = LocalDateTime.of(startDate, st)
        val endLdt = LocalDateTime.of(endDate, et)
        if (!endLdt.isAfter(startLdt)) { error = "پایان باید بعد از شروع باشد."; return }
        busy = true
        notice = null
        error = null
        scope.launch {
            try {
                repo.call {
                    repo.api.submitLeave(
                        LeaveSubmitReq(
                            leave_type = selectedCode!!,
                            starts_at = startLdt.atZone(TEHRAN).toOffsetDateTime().toString(),
                            ends_at = endLdt.atZone(TEHRAN).toOffsetDateTime().toString(),
                            description = description.take(2000),
                        ),
                    )
                }
                notice = "درخواست ثبت شد و برای رسیدگی به مدیر شعبه ارسال گردید."
                description = ""
                reloadAll()
            } catch (e: Exception) {
                error = friendlyError(e)
            } finally {
                busy = false
            }
        }
    }

    fun doCancel(target: MyRequestRow) {
        cancelTarget = null
        busy = true
        notice = null
        error = null
        scope.launch {
            try {
                repo.call { repo.api.cancelRequest(CancelReq(kind = target.kind, id = target.id)) }
                notice = "درخواست لغو شد."
                reloadAll()
            } catch (e: Exception) {
                error = friendlyError(e)
            } finally {
                busy = false
            }
        }
    }

    val selected = types.firstOrNull { it.code == selectedCode }
    val selectedBalance = balances?.balances?.firstOrNull { it.leave_type == selectedCode && it.tracked }

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
            Text("درخواست مرخصی", style = MaterialTheme.typography.titleLarge)
            TextButton(onClick = onBack) { Text("بازگشت") }
        }

        if (loading) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
            ) { CircularProgressIndicator() }
        } else {
            // ------------------------------------------------ فرم درخواست
            Card(Modifier.fillMaxWidth()) {
                Column(
                    Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("فرم درخواست", style = MaterialTheme.typography.titleMedium)

                    if (types.isEmpty()) {
                        Text(
                            "نوع مرخصی فعالی تعریف نشده است.",
                            color = MaterialTheme.colorScheme.error,
                        )
                    } else {
                        Text("نوع مرخصی", style = MaterialTheme.typography.labelMedium)
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.horizontalScroll(rememberScrollState()),
                        ) {
                            types.forEach { t ->
                                OutlinedButton(
                                    onClick = { selectedCode = t.code },
                                    enabled = !busy,
                                ) {
                                    Text(
                                        if (t.code == selectedCode) "✓ ${t.name}" else t.name,
                                        fontWeight = if (t.code == selectedCode)
                                            androidx.compose.ui.text.font.FontWeight.Bold
                                        else null,
                                    )
                                }
                            }
                        }
                        selected?.let {
                            Text(
                                if (it.is_hourly) "ساعتی — بازهٔ دقیق شروع تا پایان" +
                                    (if (it.requires_attachment) " · پیوست الزامی است" else "")
                                else "روزانه — کل بازهٔ انتخابی محاسبه می‌شود",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        selectedBalance?.let {
                            Text(
                                "ماندهٔ فعلی: ${minutesToHM(it.balance_minutes ?: 0)}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }

                    // شروع
                    Text("از", style = MaterialTheme.typography.labelMedium)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = startY, onValueChange = { startY = it },
                            label = { Text("سال") }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1.4f),
                        )
                        OutlinedTextField(
                            value = startM, onValueChange = { startM = it },
                            label = { Text("ماه") }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = startD, onValueChange = { startD = it },
                            label = { Text("روز") }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = startTime, onValueChange = { startTime = it },
                            label = { Text("ساعت") }, singleLine = true,
                            modifier = Modifier.weight(1.3f),
                        )
                    }
                    parseJalaliDate(startY, startM, startD)?.let {
                        Text(
                            Jalali.formatJalaliLong(it),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    TextButton(
                        onClick = { showStartCal = !showStartCal; showEndCal = false },
                        enabled = !busy,
                    ) { Text(if (showStartCal) "بستن تقویم" else "انتخاب از تقویم شمسی") }
                    if (showStartCal) {
                        JalaliCalendar(
                            selected = parseJalaliDate(startY, startM, startD),
                            onPick = { picked ->
                                val j = Jalali.toJalali(picked)
                                startY = j.jy.toString()
                                startM = j.jm.toString()
                                startD = j.jd.toString()
                                showStartCal = false
                            },
                        )
                    }

                    // پایان
                    Text("تا", style = MaterialTheme.typography.labelMedium)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = endY, onValueChange = { endY = it },
                            label = { Text("سال") }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1.4f),
                        )
                        OutlinedTextField(
                            value = endM, onValueChange = { endM = it },
                            label = { Text("ماه") }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = endD, onValueChange = { endD = it },
                            label = { Text("روز") }, singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = endTime, onValueChange = { endTime = it },
                            label = { Text("ساعت") }, singleLine = true,
                            modifier = Modifier.weight(1.3f),
                        )
                    }
                    parseJalaliDate(endY, endM, endD)?.let {
                        Text(
                            Jalali.formatJalaliLong(it),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    TextButton(
                        onClick = { showEndCal = !showEndCal; showStartCal = false },
                        enabled = !busy,
                    ) { Text(if (showEndCal) "بستن تقویم" else "انتخاب از تقویم شمسی") }
                    if (showEndCal) {
                        JalaliCalendar(
                            selected = parseJalaliDate(endY, endM, endD),
                            onPick = { picked ->
                                val j = Jalali.toJalali(picked)
                                endY = j.jy.toString()
                                endM = j.jm.toString()
                                endD = j.jd.toString()
                                showEndCal = false
                            },
                        )
                    }

                    OutlinedTextField(
                        value = description, onValueChange = { description = it.take(2000) },
                        label = { Text("توضیح (اختیاری)") }, singleLine = false,
                        maxLines = 3, modifier = Modifier.fillMaxWidth(),
                    )

                    Button(onClick = { submit() }, enabled = !busy && selectedCode != null) {
                        if (busy) CircularProgressIndicator(Modifier.padding(end = 8.dp))
                        Text("ثبت درخواست")
                    }
                }
            }

            notice?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

            // ------------------------------------------------ فهرست درخواست‌ها
            Text(
                "درخواست‌های من (${Jalali.faDigits(requests.size.toString())})",
                style = MaterialTheme.typography.titleMedium,
            )
            if (requests.isEmpty()) {
                Text(
                    "درخواستی ثبت نکرده‌اید.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            requests.forEach { item ->
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
                                if (item.kind == "LEAVE")
                                    "مرخصی — ${item.leave_type_name ?: item.leave_type ?: ""}"
                                else "مأموریت — ${item.subject ?: ""}",
                                style = MaterialTheme.typography.titleSmall,
                            )
                            Text(
                                requestStatusLabel(item.status),
                                color = if (item.status == "PENDING")
                                    MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Text(
                            "${jalaliDateTime(item.starts_at)} تا ${jalaliDateTime(item.ends_at)}" +
                                " · ${minutesToHM(item.computed_minutes)}",
                            style = MaterialTheme.typography.bodySmall,
                        )
                        if (item.segments.size > 1) {
                            Text(
                                item.segments.joinToString(" · ") {
                                    "${it.branch_name}: ${requestStatusLabel(it.status)}"
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        if (item.status == "PENDING") {
                            TextButton(
                                onClick = { cancelTarget = item },
                                enabled = !busy,
                            ) { Text("لغو درخواست") }
                        }
                    }
                }
            }
        }
    }

    // تأیید لغو
    cancelTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { cancelTarget = null },
            title = { Text("لغو درخواست") },
            text = {
                Text(
                    "این درخواست لغو شود؟ فقط درخواست‌های «در انتظار» قابل لغو هستند.",
                )
            },
            confirmButton = {
                TextButton(onClick = { doCancel(target) }) { Text("بله، لغو شود") }
            },
            dismissButton = {
                TextButton(onClick = { cancelTarget = null }) { Text("انصراف") }
            },
        )
    }
}
