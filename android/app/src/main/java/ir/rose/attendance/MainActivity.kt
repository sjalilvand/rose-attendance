package ir.rose.attendance

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import ir.rose.attendance.data.Repository
import ir.rose.attendance.ui.HistoryScreen
import ir.rose.attendance.ui.HomeScreen
import ir.rose.attendance.ui.LeaveScreen
import ir.rose.attendance.ui.LoginScreen
import ir.rose.attendance.ui.ManagerScreen
import ir.rose.attendance.ui.MessagesScreen
import ir.rose.attendance.ui.theme.RoseTheme

/**
 * نقطهٔ ورود اپ — اسکلت فاز ۱ (فاز ۲ گام ۶ مخزن).
 * جهت چیدمان روی RTL قفل شده چون کل UI فارسی است، مستقل از زبان دستگاه.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            RoseTheme {
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
                    Surface(modifier = Modifier.fillMaxSize()) {
                        AppRoot()
                    }
                }
            }
        }
    }
}

@Composable
private fun AppRoot() {
    // خواندن LocalContext بیرون remember — فراخوانی Composable داخل محاسبهٔ remember مجاز نیست
    val context = LocalContext.current
    val repo = remember { Repository(context) }
    // وضعیت ورود از توکن ذخیره‌شده؛ rememberSaveable برای چرخش صفحه
    var loggedIn by rememberSaveable { mutableStateOf(repo.store.hasSession) }
    // روتر سادهٔ چهارصفحه‌ای — بدون کتابخانهٔ navigation (اسکلت سبک)
    var screen by rememberSaveable { mutableStateOf("home") }

    if (loggedIn) {
        when (screen) {
            "history" -> HistoryScreen(repo = repo, onBack = { screen = "home" })
            "leave" -> LeaveScreen(repo = repo, onBack = { screen = "home" })
            "review" -> ManagerScreen(repo = repo, onBack = { screen = "home" })
            "messages" -> MessagesScreen(repo = repo, onBack = { screen = "home" })
            else -> HomeScreen(
                repo = repo,
                onLoggedOut = { loggedIn = false },
                onOpenHistory = { screen = "history" },
                onOpenLeave = { screen = "leave" },
                onOpenReview = { screen = "review" },
                onOpenMessages = { screen = "messages" },
            )
        }
    } else {
        LoginScreen(repo = repo, onLoggedIn = { loggedIn = true })
    }
}
