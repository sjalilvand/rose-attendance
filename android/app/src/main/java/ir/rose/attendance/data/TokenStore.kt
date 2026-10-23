package ir.rose.attendance.data

import android.content.Context
import android.content.SharedPreferences

/**
 * نگهداری توکن‌ها در SharedPreferences — ساده و هم‌تراز PWA (localStorage).
 * برای انتشار، مهاجرت به EncryptedSharedPreferences/DataStore در نقشهٔ راه است.
 */
class TokenStore(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("rose.tokens", Context.MODE_PRIVATE)

    var access: String?
        get() = prefs.getString(KEY_ACCESS, null)
        set(value) = prefs.edit().putString(KEY_ACCESS, value).apply()

    var refresh: String?
        get() = prefs.getString(KEY_REFRESH, null)
        set(value) = prefs.edit().putString(KEY_REFRESH, value).apply()

    val hasSession: Boolean
        get() = !access.isNullOrBlank() || !refresh.isNullOrBlank()

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val KEY_ACCESS = "rose.access"
        private const val KEY_REFRESH = "rose.refresh"
    }
}
