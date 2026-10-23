package ir.rose.attendance.ui

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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import ir.rose.attendance.data.BalancesResp
import ir.rose.attendance.data.MeInfo
import ir.rose.attendance.data.PunchRequest
import ir.rose.attendance.data.Repository
import ir.rose.attendance.data.TodayCard
import kotlinx.coroutines.launch
import java.time.OffsetDateTime
import java.util.UUID

/**
 * خانهٔ اسکلت: کارت امروز + ثبت ورود/خروج + ماندهٔ مرخصی.
 * مطابق مصوبهٔ §34 ثبت تردد بدون GPS ممکن است — رویداد بدون موقعیت به صف
 * رسیدگی (NEEDS_REVIEW) می‌رود و این رفتار عمدی سرور است.
 */
@Composable
fun HomeScreen(repo: Repository, onLoggedOut: () -> Unit) {
    val scope = rememberCoroutineScope()
    var me by remember { mutableStateOf<MeInfo?>(null) }
    var today by remember { mutableStateOf<TodayCard?>(null) }
    var balances by remember { mutableStateOf<BalancesResp?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    suspend fun reload() {
        me = repo.call { repo.api.me() }
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
    }

    LaunchedEffect(Unit) {
        try {
            reload()
        } catch (e: Exception) {
            onLoggedOut() // نشست از دست رفته
        }
    }

    fun punch(eventType: String) {
        val branchCode = me?.branches?.firstOrNull { it.is_home }?.code
            ?: me?.branches?.firstOrNull()?.code
        if (branchCode == null || busy) {
            message = "شعبه‌ای برای ثبت تردد تعریف نشده است."
            return
        }
        busy = true
        message = null
        scope.launch {
            try {
                val result = repo.call {
                    repo.api.punch(
                        PunchRequest(
                            event_uuid = UUID.randomUUID().toString(),
                            event_type = eventType,
                            branch_code = branchCode,
                            device_time = OffsetDateTime.now().toString(),
                        )
                    )
                }
                message = if (result.created) "ثبت شد (${result.event_type})"
                else "رویداد تکراری بود"
                today = try { repo.call { repo.api.today() } } catch (_: Exception) { null }
            } catch (e: Exception) {
                message = "ثبت ناموفق بود — دوباره تلاش کنید."
            } finally {
                busy = false
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
