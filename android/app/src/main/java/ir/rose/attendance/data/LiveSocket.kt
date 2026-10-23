package ir.rose.attendance.data

import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** اعلان زندهٔ سرور — همان قالب PWA در lib/ws.ts. */
data class LiveNotification(
    val kind: String,
    val title: String,
    val payload: JsonObject?,
    val createdAt: String,
)

@Serializable
private data class WsFrame(
    val type: String = "",
    val kind: String = "",
    val title: String = "",
    val payload: JsonObject? = null,
    @SerialName("created_at") val createdAt: String = "",
)

/**
 * گام ۲ — اعلان زندهٔ WebSocket روی /ws/notifications/?token=…
 *
 * همان قرارداد PWA: احراز با access JWT در query string، اتصال مجدد با
 * backoff نمایی محدود (سقف ۱۵ ثانیه) و یک تلاش refresh توکن پس از هر قطعی
 * ۴۰۱. اعلان‌ها در StateFlow نگه داشته می‌شوند (۲۰ مورد آخر) تا UI جمع کند.
 */
class LiveSocket(private val repository: Repository) {

    private val json = Json { ignoreUnknownKeys = true }
    private var webSocket: WebSocket? = null
    private var attempt = 0
    private var stopped = false

    private val scheduler = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "rose-ws-reconnect").apply { isDaemon = true }
    }

    private val _notifications = MutableStateFlowCompat()
    val notifications = _notifications.flow

    /** سیم‌کشی مجدد پس از لاگین/خروج — وضعیت قبلی پاک می‌شود. */
    @Synchronized
    fun restart() {
        stopped = false
        _notifications.clear()
        webSocket?.close(1000, "restart")
        webSocket = null
        start()
    }

    @Synchronized
    fun start() {
        if (stopped || webSocket != null) return
        val token = repository.store.access ?: return
        val request = Request.Builder().url(repository.webSocketUrl(token)).build()
        webSocket = repository.wsClient.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
                    attempt = 0
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    val frame = runCatching { json.decodeFromString(WsFrame.serializer(), text) }
                        .getOrNull() ?: return
                    if (frame.type != "notification") return
                    _notifications.push(
                        LiveNotification(
                            kind = frame.kind,
                            title = frame.title,
                            payload = frame.payload,
                            createdAt = frame.createdAt,
                        ),
                    )
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: okhttp3.Response?) {
                    this@LiveSocket.webSocket = null
                    // نشست منقضی؟ یک بار تازه‌سازی توکن؛ ترد پس‌زمینه است.
                    if (response?.code == 401 || t.message?.contains("401") == true) {
                        runCatching { repository.refreshSync() }
                    }
                    scheduleReconnect()
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    this@LiveSocket.webSocket = null
                    scheduleReconnect()
                }
            },
        )
    }

    @Synchronized
    fun stop() {
        stopped = true
        webSocket?.close(1000, "bye")
        webSocket = null
        scheduler.shutdownNow()
    }

    private fun scheduleReconnect() {
        if (stopped) return
        attempt = minOf(attempt + 1, 5)
        val delayMs = minOf(15_000L, 500L * (1L shl attempt))
        scheduler.schedule({ runCatching { start() } }, delayMs, TimeUnit.MILLISECONDS)
    }
}

/** پوشش کوچک دور StateFlow برای push/clear داخلی. */
private class MutableStateFlowCompat {
    private val backing = kotlinx.coroutines.flow.MutableStateFlow<List<LiveNotification>>(emptyList())
    val flow: kotlinx.coroutines.flow.StateFlow<List<LiveNotification>> = backing

    fun push(item: LiveNotification) {
        backing.value = listOf(item) + backing.value.take(19)
    }

    fun clear() {
        backing.value = emptyList()
    }
}
