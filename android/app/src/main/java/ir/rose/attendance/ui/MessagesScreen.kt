package ir.rose.attendance.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ir.rose.attendance.data.ChatMessageRow
import ir.rose.attendance.data.ConversationRow
import ir.rose.attendance.data.Jalali
import ir.rose.attendance.data.LiveSocket
import ir.rose.attendance.data.OpenConvReq
import ir.rose.attendance.data.PartnerRow
import ir.rose.attendance.data.Repository
import ir.rose.attendance.data.SendBody
import java.util.UUID
import kotlinx.coroutines.launch

/**
 * گام ۵ — پیام‌ها در اپ (§12 v1): گفتگوی دوطرفهٔ کارمند با مدیر/HR.
 *
 * سوکت زنده فقط در حین فعال بودن صفحه باز می‌ماند (همان الگوی HomeScreen)؛
 * MESSAGE_NEW رشتهٔ باز و فهرست گفتگوها را تازه می‌کند. واکشی رشته، پیام‌های
 * طرف مقابل را «خوانده‌شده» علامت می‌زند (قرارداد سرور).
 */
@Composable
fun MessagesScreen(repo: Repository, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val live = remember { LiveSocket(repo) }
    var conversations by remember { mutableStateOf<List<ConversationRow>>(emptyList()) }
    var partners by remember { mutableStateOf<List<PartnerRow>>(emptyList()) }
    var active by remember { mutableStateOf<ConversationRow?>(null) }
    var thread by remember { mutableStateOf<List<ChatMessageRow>>(emptyList()) }
    var body by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var showPartnerPicker by remember { mutableStateOf(false) }
    val notifications by live.notifications.collectAsState()
    val listState = rememberLazyListState()

    fun refreshConversations() {
        scope.launch {
            conversations = try {
                repo.call { repo.api.conversations() }.results
            } catch (e: Exception) {
                message = friendlyError(e)
                emptyList()
            }
        }
    }

    fun openThread(convId: Long) {
        scope.launch {
            busy = true
            try {
                val resp = repo.call { repo.api.thread(convId) }
                active = resp.conversation
                thread = resp.results
                message = null
                refreshConversations()
            } catch (e: Exception) {
                message = friendlyError(e)
            } finally {
                busy = false
            }
        }
    }

    fun startWith(partner: PartnerRow) {
        scope.launch {
            busy = true
            try {
                val conv = repo.call { repo.api.openConversation(OpenConvReq(partner.id)) }
                refreshConversations()
                openThread(conv.id)
            } catch (e: Exception) {
                message = friendlyError(e)
            } finally {
                busy = false
            }
        }
    }

    fun send() {
        val conv = active ?: return
        val text = body.trim()
        if (text.isEmpty() || busy) return
        scope.launch {
            busy = true
            try {
                repo.call { repo.api.sendMessage(conv.id, SendBody(body = text, client_uuid = UUID.randomUUID().toString())) }
                body = ""
                openThread(conv.id)
            } catch (e: Exception) {
                message = friendlyError(e)
            } finally {
                busy = false
            }
        }
    }

    LaunchedEffect(Unit) {
        refreshConversations()
        try {
            partners = repo.call { repo.api.partners() }.results
        } catch (e: Exception) {
            message = friendlyError(e)
        }
    }

    DisposableEffect(Unit) {
        live.start()
        onDispose { live.stop() }
    }

    // پیام جدید زنده → تازه‌سازی فهرست + رشتهٔ باز
    LaunchedEffect(Unit) {
        live.notifications.collect { list ->
            val latest = list.firstOrNull() ?: return@collect
            when (latest.kind) {
                "MESSAGE_NEW" -> {
                    refreshConversations()
                    val cid = latest.payload?.get("conversation_id")?.toString()?.toLongOrNull()
                    if (cid != null && cid == active?.id) openThread(cid)
                }
                "MESSAGE_READ" -> refreshConversations()
            }
        }
    }

    // اسکرول خودکار به آخرین پیام
    LaunchedEffect(thread.size) {
        if (thread.isNotEmpty()) listState.scrollToItem(thread.size - 1)
    }

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("پیام‌ها", style = MaterialTheme.typography.titleLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { showPartnerPicker = true }) { Text("گفتگوی جدید") }
                TextButton(onClick = onBack) { Text("بازگشت") }
            }
        }

        message?.let { Text(it, color = MaterialTheme.colorScheme.primary, fontSize = 13.sp) }

        // رشتهٔ فعال — یا راهنمای انتخاب
        if (active == null) {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("گفتگویی باز نیست.", style = MaterialTheme.typography.titleMedium)
                    Text("«گفتگوی جدید» را بزنید و مخاطب مجاز (مدیر شعبه/منابع انسانی) را انتخاب کنید.")
                }
            }
        } else {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text(
                        active?.partner?.full_name ?: "—",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        active?.partner?.branch_name ?: "",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            LazyColumn(
                state = listState,
                modifier = Modifier.fillMaxSize().weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(thread, key = { it.id }) { m ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = if (m.mine) Arrangement.End else Arrangement.Start,
                    ) {
                        Box(
                            modifier = Modifier
                                .widthIn(max = 300.dp)
                                .background(
                                    if (m.mine) MaterialTheme.colorScheme.secondaryContainer
                                    else MaterialTheme.colorScheme.surfaceVariant,
                                    RoundedCornerShape(
                                        topStart = 12.dp, topEnd = 12.dp,
                                        bottomStart = if (m.mine) 12.dp else 2.dp,
                                        bottomEnd = if (m.mine) 2.dp else 12.dp,
                                    ),
                                )
                                .padding(10.dp),
                        ) {
                            Column {
                                Text(m.body, fontSize = 14.sp)
                                Text(
                                    buildString {
                                        append(jalaliDateTime(m.created_at))
                                        if (m.mine) append(if (m.read_at != null) " · خوانده شد" else " · ارسال شد")
                                    },
                                    fontSize = 10.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = body,
                    onValueChange = { body = it },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("متن پیام…") },
                    enabled = !busy,
                )
                Button(onClick = { send() }, enabled = !busy && body.isNotBlank()) {
                    if (busy) CircularProgressIndicator(Modifier.padding(end = 6.dp))
                    Text("ارسال")
                }
            }
        }

        // فهرست گفتگوهای موجود
        if (conversations.isNotEmpty()) {
            Text("گفتگوهای اخیر", style = MaterialTheme.typography.titleMedium)
            LazyColumn(modifier = Modifier.fillMaxWidth().weight(0.6f, fill = false)) {
                items(conversations, key = { it.id }) { conv ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { openThread(conv.id) }
                            .padding(vertical = 8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(conv.partner?.full_name ?: "—", style = MaterialTheme.typography.bodyLarge)
                            Text(
                                conv.last_message?.let { (if (it.mine) "شما: " else "") + it.body } ?: "گفتگوی جدید",
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                            )
                        }
                        if (conv.unread_count > 0) {
                            Text(
                                Jalali.faDigits(conv.unread_count.toString()),
                                color = MaterialTheme.colorScheme.primary,
                                style = MaterialTheme.typography.titleMedium,
                            )
                        }
                    }
                    HorizontalDivider()
                }
            }
        }
    }

    if (showPartnerPicker) {
        AlertDialog(
            onDismissRequest = { showPartnerPicker = false },
            confirmButton = {
                TextButton(onClick = { showPartnerPicker = false }) { Text("بستن") }
            },
            title = { Text("انتخاب مخاطب") },
            text = {
                LazyColumn(modifier = Modifier.fillMaxWidth()) {
                    items(partners, key = { it.id }) { p ->
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    showPartnerPicker = false
                                    startWith(p)
                                }
                                .padding(vertical = 10.dp),
                        ) {
                            Text(p.full_name, style = MaterialTheme.typography.bodyLarge)
                            Text(
                                "${p.job_title.ifBlank { "پرسنل" }} — ${p.branch_name}",
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        HorizontalDivider()
                    }
                }
            },
        )
    }
}
