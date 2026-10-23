"""Django admin — operational visibility for HR/IT (read-mostly usage)."""
from django.contrib import admin

from apps.attendance.models import AttendanceAdjustment, AttendanceEvent, AttendanceSession
from apps.leaves.models import LeaveRequest, RequestSegment
from apps.messaging.models import Message, Notification
from apps.ops.models import AuditLog, CleanupRun, ImportJob
from apps.orgs.models import Branch, EmployeeBranchAssignment, Region
from apps.people.models import DeviceSession, Employee, Role, RoleAssignment, User
from apps.reports.models import MonthlyClosure, MonthlySummary
from apps.rules.models import RuleSet
from apps.scheduling.models import ScheduledShift, Shift


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "region", "geo_radius_m", "is_active")
    list_filter = ("region", "is_active")
    search_fields = ("code", "name")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("personnel_code", "first_name", "last_name", "home_branch", "employment_status")
    list_filter = ("employment_status", "home_branch")
    search_fields = ("personnel_code", "first_name", "last_name", "national_id")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "employee", "is_active", "failed_attempts", "locked_until")
    search_fields = ("username",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "branch", "valid_from", "valid_to")
    list_filter = ("role",)


@admin.register(DeviceSession)
class DeviceSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "last_seen_at", "expires_at", "revoked_at")


@admin.register(AttendanceEvent)
class AttendanceEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_type", "employee", "branch", "effective_time", "connection_mode",
        "location_status", "event_status",
    )
    list_filter = ("event_status", "location_status", "connection_mode", "branch")
    search_fields = ("event_uuid",)


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "branch", "shift_date", "session_state", "work_minutes")
    list_filter = ("session_state", "branch")


@admin.register(AttendanceAdjustment)
class AdjustmentAdmin(admin.ModelAdmin):
    list_display = ("id", "adjustment_kind", "target_event", "decided_by", "decided_at")
    list_filter = ("adjustment_kind",)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "leave_type", "starts_at", "overall_status")
    list_filter = ("overall_status",)


@admin.register(RequestSegment)
class SegmentAdmin(admin.ModelAdmin):
    list_display = ("id", "request_kind", "branch", "starts_at", "segment_status")
    list_filter = ("segment_status", "request_kind")


@admin.register(RuleSet)
class RuleSetAdmin(admin.ModelAdmin):
    list_display = ("rule_kind", "scope", "scope_id", "effective_from", "status")
    list_filter = ("rule_kind", "scope", "status")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "starts_at", "ends_at", "crosses_midnight", "rest_minutes")


@admin.register(ScheduledShift)
class ScheduledShiftAdmin(admin.ModelAdmin):
    list_display = ("employee", "branch", "work_date", "shift", "source")
    list_filter = ("source",)


@admin.register(MonthlySummary)
class SummaryAdmin(admin.ModelAdmin):
    list_display = (
        "employee", "branch", "period_year", "period_month",
        "accepted_work_minutes", "summary_state",
    )
    list_filter = ("summary_state",)


@admin.register(MonthlyClosure)
class ClosureAdmin(admin.ModelAdmin):
    list_display = ("period_year", "period_month", "scope", "scope_branch", "state", "closed_at")


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "job_kind", "status", "total_rows", "ok_rows", "error_rows")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action_code", "entity_type", "entity_id", "actor", "created_at")


@admin.register(CleanupRun)
class CleanupRunAdmin(admin.ModelAdmin):
    list_display = ("id", "started_at", "dry_run", "deleted_events", "status")


admin.site.register(EmployeeBranchAssignment)
admin.site.register(Message)
admin.site.register(Notification)
