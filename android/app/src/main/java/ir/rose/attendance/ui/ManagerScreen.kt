package ir.rose.attendance.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ir.rose.attendance.data.DecideReq
import ir.rose.attendance.data.Jalali
import ir.rose.attendance.data.OvertimeApproveReq
import ir.rose.attendance.data.OvertimeItemRow
import ir.rose.attendance.data.QueueItemRow
import ir.rose.attendance.data.Repository
import ir.rose.attendance.data.ReviewApproveReq
import ir.rose.attendance.data.ReviewItemRow
import ir.rose.attendance.data.ReviewRejectReq
import java.time.LocalDateTime
import java.time.OffsetDateTime
import kotlinx.coroutines.launch

/**
 * رسیدگی مدیران (گام ۴) — همان جریان تصمیم‌گیری صفحهٔ «رسیدگی» PWA داخل اپ:
 *
 *  ۱) درخواست‌ها     — پاره‌های PENDING مرخصی/مأموریت در محدودهٔ مدیر
 *                      (GET /requests/queue/ + POST /requests/queue/decide/)
 *  ۲) تردد نیازمند رسیدگی — رویدادهای NEEDS_REVIEW با ثبت زمان مؤثر
 *                      اصلاح‌شده (TIME_FIX) یا رد با دلیل (VOID §۸)
 *  ۳) اضافه‌کاری      — پیشنهادهای PENDING و تأیید §۷.۳
 *
 * ورود به این صفحه فقط برای نقش‌های BRANCH_MANAGER/REGION_MANAGER/HR/ADMIN
 * از صفحهٔ خانه نشان داده می‌شود؛ خود اندپوینت‌ها هم سمت سرور محافظت‌شده‌اند.
 * محدودهٔ دسترسی (شعبه‌های خود مدیر یا کل سازمان) را سرور تعیین می‌کند و
 * اپ فقط پاسخ را نمایش می‌دهد. تاریخ‌ها همه شمسی و منطقهٔ زمانی تهران است.
 */

private enum class ReviewTab(val label: String) {
    REQUESTS("درخواست‌ها"),
    PUNCHES("تردد نیازمند رسیدگی"),
    OVERTIME("اضافه‌کاری"),
}

/** ISO سرور → LocalDateTime به وقت تهران (پیش‌فرض فیلد زمان مؤثر). */
private fun tehranLocal(iso: String?): LocalDateTime? = runCatching {
    OffsetDateTime.parse(iso).atZoneSameInstant(TEHRAN).toLocalDateTime()
}.getOrNull()

private fun prefillDate(iso: String?): String =
    tehranLocal(iso)?.let { Jalali.formatJalali(it.toLocalDate()) } ?: ""

private fun prefillTime(iso: String?): String = tehranLocal(iso)?.let {
    Jalali.faDigits("%02d:%02d".format(it.hour, it.minute))
} ?: ""

@Composable
fun ManagerScreen(repo: Repository, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()

    var tabName by rememberSaveable { mutableStateOf(ReviewTab.REQUESTS.name) }
    val tab = remember(tabName) { ReviewTab.valueOf(tabName) }

    var queue by remember { mutableStateOf<List<QueueItemRow>>(emptyList()) }
    var punches by remember { mutableStateOf<List<ReviewItemRow>>(emptyList()) }
    var overtime by remember { mutableStateOf<List<OvertimeItemRow>>(emptyList()) }

    // فیلدهای رسیدگی تردد — به‌ازای هر event_uuid
    var comments by remember { mutableStateOf<Map<Long, String>>(emptyMap()) }
    var punchDates by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var punchTimes by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var punchReasons by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var rejectTarget by remember { mutableStateOf<ReviewItemRow?>(null) }

    var loading by remember { mutableStateOf(true) }
    var busyKey by remember { mutableStateOf<String?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun loadQueue() {
        queue = repo.call { repo.api.requestQueue() }.results
    }

    suspend fun loadPunches() {
        val rows = repo.call { repo.api.reviewQueue() }.results
        punches = rows
        // پیش‌فرض زمان مؤثر = زمان دستگاه رویداد به وقت تهران
        rows.forEach { item ->
            if (item.event_uuid !in punchDates) {
                punchDates = punchDates + (item.event_uuid to prefillDate(item.device_time ?: item.effective_time))
                punchTimes = punchTimes + (item.event_uuid to prefillTime(item.device_time ?: item.effective_time))
            }
        }
    }

    suspend fun loadOvertime() {
        overtime = repo.call { repo.api.overtime("PENDING") }.results
    }

    suspend fun reloadAll() {
        loading = true
        error = null
        try {
            loadQueue()
            loadPunches()
            loadOvertime()
        } catch (e: Exception) {
            error = friendlyError(e)
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { reloadAll() }

    /** تازه‌سازی فقط زبانهٔ فعال — پس از هر تصمیم. */
    fun refreshCurrent() {
        scope.launch {
            try {
                when (tab) {
                    ReviewTab.REQUESTS -> loadQueue()
                    ReviewTab.PUNCHES -> loadPunches()
                    ReviewTab.OVERTIME -> loadOvertime()
                }
            } catch (e: Exception) {
                error = friendlyError(e)
            }
        }
    }

    fun decide(item: QueueItemRow, action: String) {
        if (busyKey != null) return
        busyKey = "q${item.segment_id}"
        notice = null
        error = null
        scope.launch {
            try {
                val res = repo.call {
                    repo.api.decideSegment(
                        DecideReq(
                            segment_id = item.segment_id,
                            action = action,
                            comment = (comments[item.segment_id] ?: "").take(500),
                        ),
                    )
                }
                notice = if (action == "APPROVE")
                    "بخش تأیید شد — وضعیت کل درخواست: ${requestStatusLabel(res.overall_status)}"
                else "بخش رد شد."
                loadQueue()
            } catch (e: Exception) {
                error = friendlyError(e)
            } finally {
                busyKey = null
            }
        }
    }

    fun reviewPunch(item: ReviewItemRow, approve: Boolean) {
        if (busyKey != null) return
        val reason = (punchReasons[item.event_uuid] ?: "").trim()
        if (approve) {
            val date = parseJalaliText(punchDates[item.event_uuid])
            val time = parseHmText(punchTimes[item.event_uuid])
            if (date == null) {
                error = "تاریخ مؤثر را به شکل ۱۴۰۵/۰۸/۰۲ وارد کنید."
                return
            }
            if (time == null) {
                error = "ساعت مؤثر را به شکل ۰۹:۰۰ وارد کنید."
                return
            }
            busyKey = "p${item.event_uuid}"
            notice = null
            error = null
            scope.launch {
                try {
                    val corrected = LocalDateTime.of(date, time).atZone(TEHRAN).toOffsetDateTime().toString()
                    repo.call {
                        repo.api.approveReviewPunch(
                            ReviewApproveReq(
                                event_uuid = item.event_uuid,
                                corrected_time = corrected,
                                reason = reason.take(500),
                            ),
                        )
                    }
                    notice = "تردد رسیدگی شد و زمان مؤثر ثبت گردید."
                    loadPunches()
                } catch (e: Exception) {
                    error = friendlyError(e)
                } finally {
                    busyKey = null
                }
            }
        } else {
            if (reason.length < 3) {
                error = "برای رد رویداد، ذکر دلیل الزامی است."
                return
            }
            busyKey = "p${item.event_uuid}"
            notice = null
            error = null
            scope.launch {
                try {
                    repo.call {
                        repo.api.rejectReviewPunch(ReviewRejectReq(event_uuid = item.event_uuid, reason = reason))
                    }
                    notice = "رویداد رد شد؛ در سوابق با برچسب «رد فنی» حفظ می‌شود."
                    loadPunches()
                } catch (e: Exception) {
                    error = friendlyError(e)
                } finally {
                    busyKey = null
                }
            }
        }
    }

    fun approveOvertime(item: OvertimeItemRow) {
        if (busyKey != null) return
        busyKey = "o${item.id}"
        notice = null
        error = null
        scope.launch {
            try {
                val res = repo.call { repo.api.approveOvertime(OvertimeApproveReq(item.id)) }
                notice = "اضافه‌کاری تأیید شد (${minutesToHM(res.approved_minutes)})."
                loadOvertime()
            } catch (e: Exception) {
                error = friendlyError(e)
            } finally {
                busyKey = null
            }
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
            Text("رسیدگی مدیر", style = MaterialTheme.typography.titleLarge)
            Row {
                TextButton(onClick = { refreshCurrent() }) { Text("بارگذاری مجدد") }
                TextButton(onClick = onBack) { Text("بازگشت") }
            }
        }

        // زبانه‌ها با شمارندهٔ هر صف
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
        ) {
            ReviewTab.entries.forEach { t ->
                val count = when (t) {
                    ReviewTab.REQUESTS -> queue.size
                    ReviewTab.PUNCHES -> punches.size
                    ReviewTab.OVERTIME -> overtime.size
                }
                val label = "${t.label} (${Jalali.faDigits(count.toString())})"
                OutlinedButton(
                    onClick = { tabName = t.name },
                    enabled = tab != t,
                ) {
                    Text(
                        if (tab == t) "✓ $label" else label,
                        fontWeight = if (tab == t) FontWeight.Bold else null,
                    )
                }
            }
        }

        if (loading) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
            ) { CircularProgressIndicator() }
        }

        notice?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

        when (tab) {
            ReviewTab.REQUESTS -> {
                if (!loading && queue.isEmpty()) {
                    Text("صف درخواست‌ها خالی است. ✓", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                queue.forEach { item ->
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
                                    fontWeight = FontWeight.Bold,
                                )
                                Text(
                                    item.branch_name,
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Text(
                                "${item.employee.personnel_code} — ${item.employee.full_name}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                            Text(
                                "${jalaliDateTime(item.starts_at)} تا ${jalaliDateTime(item.ends_at)}" +
                                    " · ${minutesToHM(item.computed_minutes)}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                            item.employee_balance_minutes?.let { bal ->
                                val short = bal < item.computed_minutes
                                Text(
                                    "ماندهٔ پرسنل: ${minutesToHM(bal)}" +
                                        (if (short) " — کسری مانده؛ پس از تأیید منفی می‌شود" else ""),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = if (short) MaterialTheme.colorScheme.error
                                    else MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            item.destination?.takeIf { it.isNotBlank() }?.let {
                                Text(
                                    "مقصد: $it",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            item.description?.takeIf { it.isNotBlank() }?.let {
                                Text(
                                    "توضیح: $it",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            OutlinedTextField(
                                value = comments[item.segment_id] ?: "",
                                onValueChange = { comments = comments + (item.segment_id to it.take(500)) },
                                label = { Text("توضیح تصمیم (اختیاری)") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(
                                    onClick = { decide(item, "APPROVE") },
                                    enabled = busyKey == null,
                                ) {
                                    if (busyKey == "q${item.segment_id}") {
                                        CircularProgressIndicator(Modifier.padding(end = 8.dp))
                                    }
                                    Text("تأیید")
                                }
                                OutlinedButton(
                                    onClick = { decide(item, "REJECT") },
                                    enabled = busyKey == null,
                                    colors = ButtonDefaults.outlinedButtonColors(
                                        contentColor = MaterialTheme.colorScheme.error,
                                    ),
                                ) { Text("رد") }
                            }
                        }
                    }
                }
            }

            ReviewTab.PUNCHES -> {
                if (!loading && punches.isEmpty()) {
                    Text(
                        "تردد نیازمند رسیدگی وجود ندارد. ✓",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                punches.forEach { item ->
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
                                    "${if (item.event_type == "CHECK_IN") "ورود" else "خروج"} — ${item.employee.full_name}",
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.Bold,
                                )
                                Text(
                                    "نیازمند رسیدگی",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                            Text(
                                "${item.employee.personnel_code} · ${item.branch} · ${jalaliDateTime(item.effective_time)}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                            if (item.flags.isNotEmpty()) {
                                Text(
                                    "نشان‌ها: ${item.flags.joinToString("، ")}",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Text(
                                "زمان مؤثر (اصلاح‌شده) — پیش‌فرض زمان دستگاه",
                                style = MaterialTheme.typography.labelMedium,
                            )
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedTextField(
                                    value = punchDates[item.event_uuid] ?: "",
                                    onValueChange = { punchDates = punchDates + (item.event_uuid to it) },
                                    label = { Text("تاریخ ۱۴۰۵/۰۸/۰۲") },
                                    singleLine = true,
                                    modifier = Modifier.weight(1.6f),
                                )
                                OutlinedTextField(
                                    value = punchTimes[item.event_uuid] ?: "",
                                    onValueChange = { punchTimes = punchTimes + (item.event_uuid to it) },
                                    label = { Text("ساعت ۰۹:۰۰") },
                                    singleLine = true,
                                    modifier = Modifier.weight(1f),
                                )
                            }
                            parseJalaliText(punchDates[item.event_uuid])?.let {
                                Text(
                                    Jalali.formatJalaliLong(it),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            OutlinedTextField(
                                value = punchReasons[item.event_uuid] ?: "",
                                onValueChange = { punchReasons = punchReasons + (item.event_uuid to it.take(500)) },
                                label = { Text("دلیل تصمیم (برای رد الزامی)") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(
                                    onClick = { reviewPunch(item, approve = true) },
                                    enabled = busyKey == null,
                                ) {
                                    if (busyKey == "p${item.event_uuid}") {
                                        CircularProgressIndicator(Modifier.padding(end = 8.dp))
                                    }
                                    Text("ثبت رسیدگی")
                                }
                                OutlinedButton(
                                    onClick = { rejectTarget = item },
                                    enabled = busyKey == null,
                                    colors = ButtonDefaults.outlinedButtonColors(
                                        contentColor = MaterialTheme.colorScheme.error,
                                    ),
                                ) { Text("رد رویداد") }
                            }
                        }
                    }
                }
            }

            ReviewTab.OVERTIME -> {
                if (!loading && overtime.isEmpty()) {
                    Text(
                        "پیشنهاد اضافه‌کاری در انتظاری وجود ندارد. ✓",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                overtime.forEach { item ->
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
                                    item.employee.full_name,
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.Bold,
                                )
                                Text(
                                    minutesToHM(item.proposed_minutes),
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                            Text(
                                "${item.employee.personnel_code} · ${item.branch} · ${jalaliDayLong(item.shift_date)}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                            item.reason?.takeIf { it.isNotBlank() }?.let {
                                Text(
                                    "دلیل: $it",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Button(
                                onClick = { approveOvertime(item) },
                                enabled = busyKey == null,
                            ) {
                                if (busyKey == "o${item.id}") {
                                    CircularProgressIndicator(Modifier.padding(end = 8.dp))
                                }
                                Text("تأیید اضافه‌کاری")
                            }
                        }
                    }
                }
            }
        }
    }

    // تأیید رد رویداد تردد — دلیل از فیلد همان کارت خوانده می‌شود
    rejectTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { rejectTarget = null },
            title = { Text("رد رویداد تردد") },
            text = {
                Text(
                    "این رویداد رد شود؟ رویداد از محاسبهٔ کارکرد خارج و با برچسب «رد فنی» در سوابق حفظ می‌شود؛ دلیل رد الزامی است.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    val item = target
                    rejectTarget = null
                    reviewPunch(item, approve = false)
                }) { Text("بله، رد شود") }
            },
            dismissButton = {
                TextButton(onClick = { rejectTarget = null }) { Text("انصراف") }
            },
        )
    }
}
