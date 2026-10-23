package ir.rose.attendance.data

import android.annotation.SuppressLint
import android.content.Context
import com.google.android.gms.location.CurrentLocationRequest
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import java.time.OffsetDateTime
import kotlinx.coroutines.tasks.await

/** یک ثبات موقعیت برای ثبت تردد. */
data class LocationFix(
    val latitude: Double,
    val longitude: Double,
    val accuracyM: Double,
    val fixedAt: String,
)

/**
 * گام ۲ — FusedLocationProvider با اولویت دقت بالا و مهلت کوتاه.
 *
 * قرارداد مصوب §34: ثبت تردد هرگز به GPS مشروط نیست؛ اگر مجوز رد شده باشد
 * یا موقعیت در مهلت تعیین‌شده نرسد، null برمی‌گردد و رویداد بدون مختصات
 * ثبت می‌شود (سمت سرور برچسب UNAVAILABLE می‌خورد، نه رد).
 */
class LocationSource(context: Context) {

    private val client = LocationServices.getFusedLocationProviderClient(context)

    /**
     * @param timeoutMs سقف انتظار برای یک fixed تازه؛ خطا/انقضا → null
     * (caller پیش از این‌جا مجوز را چک می‌کند — SecurityException هم null است)
     */
    @SuppressLint("MissingPermission")
    suspend fun currentFix(timeoutMs: Long = 8_000L): LocationFix? = try {
        val request = CurrentLocationRequest.Builder()
            .setPriority(Priority.PRIORITY_HIGH_ACCURACY)
            .setDurationMillis(timeoutMs)
            .build()
        val location = client.getCurrentLocation(request, null).await()
        location?.let {
            LocationFix(
                latitude = it.latitude,
                longitude = it.longitude,
                accuracyM = it.accuracy.toDouble(),
                fixedAt = OffsetDateTime.now().toString(),
            )
        }
    } catch (_: Exception) {
        // SecurityException (مجوز رد شده)، ApiException (GPS خاموش)، انقضا و …
        null
    }
}
