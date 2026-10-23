package ir.rose.attendance.data

import android.content.Context
import ir.rose.attendance.BuildConfig
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import java.util.concurrent.TimeUnit

/** Endpoints مصرفی اسکلت — همان قرارداد /api/v1 سرور. */
interface RoseApi {
    @POST("api/v1/auth/token/")
    suspend fun login(@Body body: LoginRequest): TokenResponse

    @POST("api/v1/auth/token/refresh/")
    suspend fun refresh(@Body body: RefreshBody): RefreshResponse

    @GET("api/v1/me/")
    suspend fun me(): MeInfo

    @GET("api/v1/attendance/daily/today/")
    suspend fun today(): TodayCard

    @POST("api/v1/attendance/events/punch/")
    suspend fun punch(@Body body: PunchRequest): PunchResult

    @GET("api/v1/leaves/ledger/balances/")
    suspend fun balances(): BalancesResp
}

@kotlinx.serialization.Serializable
data class RefreshBody(val refresh: String)

/**
 * مستر سروریس اپ — Retrofit + برچسب دستی توکن + refresh خودکار روی 401.
 * (به‌جای Authenticator تودرتوی OkHttp، همین پوشندهٔ ساده retry یک‌باره است.)
 */
class Repository(context: Context) {

    val store = TokenStore(context)

    private val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
    }

    private val baseClient: OkHttpClient by lazy {
        val builder = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
        if (BuildConfig.DEBUG) {
            builder.addInterceptor(HttpLoggingInterceptor().apply {
                level = HttpLoggingInterceptor.Level.BASIC
            })
        }
        builder.build()
    }

    private val authedClient: OkHttpClient by lazy {
        baseClient.newBuilder().addInterceptor { chain ->
            val token = store.access
            val request = if (token.isNullOrBlank()) chain.request()
            else chain.request().newBuilder()
                .header("Authorization", "Bearer $token")
                .build()
            chain.proceed(request)
        }.build()
    }

    val api: RoseApi by lazy {
        Retrofit.Builder()
            .baseUrl(BuildConfig.API_BASE)
            .client(authedClient)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(RoseApi::class.java)
    }

    suspend fun login(username: String, password: String): TokenResponse {
        val token = api.login(LoginRequest(username, password))
        store.access = token.access
        store.refresh = token.refresh
        return token
    }

    fun logout() = store.clear()

    /** refresh یک‌باره روی 401؛ اگر نشد 401 اصلی پرتاب می‌شود (خروج به Login). */
    private suspend fun refreshSession(): Boolean {
        val refresh = store.refresh ?: return false
        return try {
            val refreshed = api.refresh(RefreshBody(refresh))
            store.access = refreshed.access
            refreshed.refresh?.let { store.refresh = it }
            true
        } catch (_: HttpException) {
            false
        }
    }

    suspend fun <T> call(block: suspend () -> T): T = try {
        block()
    } catch (e: HttpException) {
        if (e.code() == 401 && refreshSession()) block() else throw e
    }
}
