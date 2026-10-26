package ir.rose.attendance.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import ir.rose.attendance.data.BalancesResp
import ir.rose.attendance.data.LiveSocket
import ir.rose.attendance.data.LocationFix
import ir.rose.attendance.data.LocationSource
import ir.rose.attendance.data.MeInfo
import ir.rose.attendance.data.PunchRequest
import ir.rose.attendance.data.Repository
import ir.rose.attendance.data.TodayCard
import ir.rose.attendance.data.UnreadBadge
import ir.rose.attendance.data.Jalali
import java.time.OffsetDateTime
import java.util.UUID
import kotlinx.coroutines.launch

/**
 * خانهٔ گام ۳: کارت امروز + ثبت ورود/خروج با موقعیت مکانی + ماندهٔ مرخصی
 * + اعلان‌های زندهٔ WebSocket + ورود به تاریخچهٔ کارکرد و درخواست مرخصی.
 *
 * قرارداد مصوب §34: ثبت تردد بدون GPS ممکن است — اگر مجوز رد شود یا موقعیت
 * در مهلت کوتاه نیاید، رویداد بدون مختصات می‌رود و سرور برچسب UNAVAILABLE
 * می‌زند (رسیدگی، نه رد). چینش RTL در MainActivity قفل شده است.
 */

private val REVIEW_KINDS = setOf("REVIEW_RESOLVED", "REVIEW_REJECTED", "OVERTIME_DECISION")

private fun locationLabel(status: String, reason: String): String = when (status) {
    "IN_RANGE" -> "موقعیت: در محدوده ✓"
    "OUT_OF_RANGE" -> "موقعیت: خارج از محدوده ($reason)"
    "LOW_ACCURACY" -> "موقعیت: دقت پایین ($reason)"
    "UNAVAILABLE" -> if (reason == "NO_COORDINATES") "موقعیت: ارسال نشد — در صف رسیدگی" else "موقعیت: نامشخص ($reason)"
    else -> "موقعیت: $status"
}

@Composable
fun HomeScreen(
    repo: Repository,
    onLoggedOut: () -> Unit,
    onOpenHistory: () -> Unit = {},
    onOpenLeave: () -> Unit = {},
    onOpenReview: () -> Unit = {},
    onOpenMessages: () -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val location = remember { LocationSource(context) }
    val live = remember { LiveSocket(repo) }
    var me by remember { mutableStateOf<MeInfo?>(null) }
    var today by remember { mutableStateOf<TodayCard?>(null) }
    var balances by remember { mutableStateOf<BalancesResp?>(null) }
    var unread by remember { mutableStateOf<UnreadBadge?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var pendingPunch by remember { mutableStateOf<String?>(null) }
    val notifications by live.notifications.collectAsState()

    /** تازه‌سازی کارت امروز از یک callback غیر-suspend (پس از punch/مجوز). */
    fun refreshToday() {
        scope.launch {
            today = try {
                repo.call { repo.api.today() }
            } catch (_: Exception) {
                null
            }
        }
    }

    val hasLocationPermission = remember {
        mutableStateOf(checkLocationPermission(context))
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { grants ->
        hasLocationPermission.value = grants.values.any { it }
        pendingPunch?.let { type ->
            pendingPunch = null
            doPunch(repo, scope, location, hasLocationPermission.value, type) { msg, reloadToday ->
                message = msg
                if (reloadToday) refreshToday()
                busy = false
            }
        }
    }

    suspend fun reload() {
        me = repo.meInfo()
        today = try {
            repo.call { repo.api.today() }
        } catch (_: Exception) {
            null // پرسنل بدون شعبهٔ مجاز ممکن است today نداشته باشد
        }
        balances = try {
            repo.call { repo.api.balances() }
        } catch (_: Exception) {
            null
        }
        unread = try {
            repo.call { repo.api.unreadBadge() }
        } catch (_: Exception) {
            null // بدون پروندهٔ پرسنلی بج ندارد
        }
    }

    LaunchedEffect(Unit) {
        try {
            reload()
        } catch (e: Exception) {
            onLoggedOut() // نشست از دست رفته
        }
    }

    // سوکت زنده فقط در حین فعال بودن صفحهٔ خانه باز می‌ماند.
    DisposableEffect(Unit) {
        live.start()
        onDispose { live.stop() }
    }

    // پیام جدید → بج نخوانده تازه شود
    LaunchedEffect(Unit) {
        live.notifications.collect { list ->
            val latest = list.firstOrNull() ?: return@collect
            if (latest.kind in REVIEW_KINDS) {
                today = try { repo.call { repo.api.today() } } catch (_: Exception) { null }
            }
            if (latest.kind in setOf("MESSAGE_NEW", "MESSAGE_READ")) {
                unread = try { repo.call { repo.api.unreadBadge() } } catch (_: Exception) { null }
            }
        }
    }

    fun punch(eventType: String) {
        if (busy) return
        val branchCode = me?.branches?.firstOrNull { it.is_home }?.code
            ?: me?.branches?.firstOrNull()?.code
        if (branchCode == null) {
            message = "شعبه‌ای برای ثبت تردد تعریف نشده است."
            return
        }
        busy = true
        message = null
        if (!hasLocationPermission.value) {
            pendingPunch = eventType
            permissionLauncher.launch(locationPermissions())
            return // ادامه پس از پاسخ مجوز (busy تا آن‌جا روشن می‌ماند)
        }
        doPunch(repo, scope, location, true, eventType) { msg, reloadToday ->
            message = msg
            if (reloadToday) refreshToday()
            busy = false
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
            Text(
                me?.employee?.full_name ?: me?.username ?: "رز سفید",
                style = MaterialTheme.typography.titleLarge,
            )
            TextButton(onClick = {
                repo.logout()
                onLoggedOut()
            }) { Text("خروج") }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("امروز", style = MaterialTheme.typography.titleMedium)
                val day = today?.today
                if (day == null) {
                    Text("اطلاعاتی برای امروز ثبت نشده است.")
                } else {
                    Text("ورود اول: ${day.first_in ?: "—"}   خروج آخر: ${day.last_out ?: "—"}")
                    Text("کار پذیرفته: ${day.accepted_work_minutes} دقیقه")
                    Text("تأخیر: ${day.late_minutes} دقیقه — غیبت: ${day.absence_minutes} دقیقه")
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(
                onClick = { punch("CHECK_IN") },
                enabled = !busy && today?.open_session == null,
            ) {
                if (busy) CircularProgressIndicator(Modifier.padding(end = 8.dp))
                Text("ثبت ورود")
            }
            OutlinedButton(
                onClick = { punch("CHECK_OUT") },
                enabled = !busy && today?.open_session != null,
            ) { Text("ثبت خروج") }
        }

        message?.let { Text(it, color = MaterialTheme.colorScheme.primary) }

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedButton(onClick = onOpenHistory) { Text("تاریخچهٔ کارکرد") }
            OutlinedButton(onClick = onOpenLeave) { Text("درخواست مرخصی") }
        }

        // گام ۵ — پیام‌ها با بج نخوانده
        OutlinedButton(onClick = onOpenMessages) {
            val count = unread?.messages ?: 0
            Text(if (count > 0) "پیام‌ها (${Jalali.faDigits(count.toString())} نخوانده)" else "پیام‌ها")
        }

        // گام ۴ — رسیدگی مدیران؛ فقط برای نقش‌های تصمیم‌گیر نشان داده می‌شود
        if (hasManagerRole(me?.roles)) {
            OutlinedButton(onClick = onOpenReview) {
                Text("رسیدگی مدیر (درخواست‌ها و ترددها)")
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("اعلان‌های زنده", style = MaterialTheme.typography.titleMedium)
                val items = notifications.take(5)
                if (items.isEmpty()) {
                    Text("اعلانی نیست؛ تصمیم‌های رسیدگی و اضافه‌کاری همین‌جا می‌آید.")
                } else {
                    items.forEach { n ->
                        Text("• ${n.title}")
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("ماندهٔ مرخصی", style = MaterialTheme.typography.titleMedium)
                val rows = balances?.balances.orEmpty().filter { it.tracked }
                if (rows.isEmpty()) {
                    Text("ماندهٔ ردیابی‌شده‌ای ثبت نشده است.")
                } else {
                    rows.forEach { row ->
                        Text(
                            "${row.leave_type_name} (${row.leave_type}): " +
                                "${row.balance_minutes ?: 0} دقیقه",
                        )
                    }
                }
            }
        }
    }
}

private fun checkLocationPermission(context: android.content.Context): Boolean =
    locationPermissions().any {
        ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
    }

private fun locationPermissions(): Array<String> = arrayOf(
    Manifest.permission.ACCESS_FINE_LOCATION,
    Manifest.permission.ACCESS_COARSE_LOCATION,
)

/** جریان ثبت تردد: (در صورت مجوز) گرفتن موقعیت با مهلت کوتاه، سپس punch. */
private fun doPunch(
    repo: Repository,
    scope: kotlinx.coroutines.CoroutineScope,
    location: LocationSource,
    withLocation: Boolean,
    eventType: String,
    onDone: (message: String, reloadToday: Boolean) -> Unit,
) {
    scope.launch {
        try {
            var fix: LocationFix? = null
            if (withLocation) {
                fix = location.currentFix()
            }
            val info = repo.meInfo()
            val branchCode = info.branches.firstOrNull { it.is_home }?.code
                ?: info.branches.firstOrNull()?.code
            if (branchCode == null) {
                onDone("شعبه‌ای برای ثبت تردد تعریف نشده است.", false)
                return@launch
            }
            val result = repo.call {
                repo.api.punch(
                    PunchRequest(
                        event_uuid = UUID.randomUUID().toString(),
                        event_type = eventType,
                        branch_code = branchCode,
                        device_time = OffsetDateTime.now().toString(),
                        latitude = fix?.latitude,
                        longitude = fix?.longitude,
                        location_accuracy_m = fix?.accuracyM,
                        location_fixed_at = fix?.fixedAt,
                        clock_offset_minutes = repo.clockOffsetMinutes,
                    ),
                )
            }
            val verb = if (result.created) "ثبت شد (${result.event_type})" else "رویداد تکراری بود"
            onDone("$verb — ${locationLabel(result.location_status, result.location_reason)}", true)
        } catch (e: Exception) {
            onDone("ثبت ناموفق بود — دوباره تلاش کنید.", false)
        }
    }
}
