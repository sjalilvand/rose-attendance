package ir.rose.attendance.data

import kotlinx.serialization.Serializable

/**
 * DTO قرارداد /api/v1 — دقیقاً همان فیلدهایی که PWA مصرف می‌کند
 * (frontend/src/lib/api.ts). Json با ignoreUnknownKeys خوانده می‌شود تا
 * افزودن فیلد سمت سرور اپ را نشکند.
 */

@Serializable
data class LoginRequest(
    val username: String,
    val password: String,
    val platform: String = "ANDROID",
)

@Serializable
data class TokenResponse(
    val access: String,
    val refresh: String,
    val personnel_code: String? = null,
    val full_name: String? = null,
    val roles: List<String> = emptyList(),
)

@Serializable
data class RefreshResponse(
    val access: String,
    val refresh: String? = null,
)

@Serializable
data class EmployeeInfo(
    val id: Long = 0,
    val personnel_code: String = "",
    val first_name: String? = null,
    val last_name: String? = null,
    val full_name: String? = null,
    val employment_status: String? = null,
    val home_branch_id: Long? = null,
)

@Serializable
data class BranchInfo(
    val id: Long = 0,
    val code: String,
    val name: String,
    val is_home: Boolean = false,
)

@Serializable
data class MeInfo(
    val username: String,
    val server_time: String? = null,
    val employee: EmployeeInfo? = null,
    val roles: List<String> = emptyList(),
    val branches: List<BranchInfo> = emptyList(),
)

@Serializable
data class DayRow(
    val shift_date: String? = null,
    val branch: Long? = null, // شناسهٔ شعبه (تاریخچه: یک سطر به‌ازای هر روز×شعبه)
    val shift_code: String? = null,
    val is_workday: Boolean = false,
    val is_holiday: Boolean = false,
    val required_minutes: Int = 0,
    val valid_presence_minutes: Int = 0,
    val accepted_work_minutes: Int = 0,
    val late_minutes: Int = 0,
    val early_leave_minutes: Int = 0,
    val overtime_approved_minutes: Int = 0,
    val absence_minutes: Int = 0,
    val leave_minutes_by_type: Map<String, Int> = emptyMap(),
    val mission_minutes: Int = 0,
    val incomplete_sessions: Int = 0,
    val first_in: String? = null,
    val last_out: String? = null,
)

@Serializable
data class TodayEvent(
    val event_uuid: String = "",
    val event_type: String = "",
    val branch: String = "",
    val effective_time: String? = null,
    val event_status: String = "",
    val location_status: String = "",
)

@Serializable
data class OpenSession(
    val id: Long = 0,
    val branch: String = "",
    val check_in_at: String? = null,
    val shift_date: String? = null,
)

@Serializable
data class TodayCard(
    val today: DayRow? = null,
    val events: List<TodayEvent> = emptyList(),
    val open_session: OpenSession? = null,
)

@Serializable
data class PunchRequest(
    val event_uuid: String,
    val event_type: String, // CHECK_IN / CHECK_OUT
    val branch_code: String,
    val channel: String = "ANDROID",
    val device_time: String,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val location_accuracy_m: Double? = null,
    val location_fixed_at: String? = null,
    val clock_offset_minutes: Double? = null,
)

@Serializable
data class PunchResult(
    val event_uuid: String = "",
    val created: Boolean = false,
    val event_type: String = "",
    val event_status: String = "",
    val location_status: String = "",
    val location_reason: String = "",
    val effective_time: String? = null,
)

@Serializable
data class LeaveBalanceRow(
    val leave_type: String,
    val leave_type_name: String = "",
    val is_hourly: Boolean = false,
    val tracked: Boolean = false,
    val balance_minutes: Int? = null,
    val entries: Int = 0,
    val last_basis_date: String? = null,
)

@Serializable
data class BalancesResp(
    val balances: List<LeaveBalanceRow> = emptyList(),
)

// ------------------------------------------------ گام ۳ — تاریخچهٔ کارکرد

/** پاسخ /attendance/daily/ — سطرهای محاسبه‌شدهٔ روزانه در بازهٔ درخواستی. */
@Serializable
data class DailyListResp(
    val count: Int = 0,
    val results: List<DayRow> = emptyList(),
)

// ------------------------------------------------------ گام ۳ — درخواست مرخصی

/** گزینه‌های /leave-types/ برای فهرست انتخاب نوع مرخصی. */
@Serializable
data class LeaveTypeRow(
    val code: String,
    val name: String,
    val is_hourly: Boolean = false,
    val is_paid: Boolean = true,
    val requires_attachment: Boolean = false,
)

@Serializable
data class LeaveTypesResp(
    val count: Int = 0,
    val results: List<LeaveTypeRow> = emptyList(),
)

/** وضعیت هر پاره (شعبه) از درخواست — تقسیم خودکار بازه بین شعب. */
@Serializable
data class RequestSegmentRow(
    val id: Long = 0,
    val branch: String = "",
    val branch_name: String = "",
    val starts_at: String? = null,
    val ends_at: String? = null,
    val computed_minutes: Int = 0,
    val status: String = "",
)

/** سطر فهرست /requests/ — مرخصی یا مأموریت (فیلد اختصاصی هرکدام nullable). */
@Serializable
data class MyRequestRow(
    val kind: String = "LEAVE",
    val id: Long = 0,
    val leave_type: String? = null,
    val leave_type_name: String? = null,
    val description: String? = null,
    val subject: String? = null,
    val destination: String? = null,
    val status: String = "",
    val starts_at: String? = null,
    val ends_at: String? = null,
    val computed_minutes: Int = 0,
    val created_at: String? = null,
    val segments: List<RequestSegmentRow> = emptyList(),
)

@Serializable
data class RequestsResp(
    val count: Int = 0,
    val results: List<MyRequestRow> = emptyList(),
)

@Serializable
data class LeaveSubmitReq(
    val leave_type: String,
    val starts_at: String,
    val ends_at: String,
    val description: String = "",
)

@Serializable
data class CancelReq(
    val kind: String,
    val id: Long,
)
