"""Root URL configuration — /api/v1 contract (section 26 of the document)."""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.attendance.api import (
    AttendanceEventViewSet,
    AttendanceSessionViewSet,
    DailyBoardViewSet,
    OvertimeProposalViewSet,
    ReviewQueueViewSet,
)
from apps.leaves.api import (
    LeaveLedgerViewSet,
    LeaveTypeViewSet,
    LedgerImportView,
    LedgerTemplateView,
    RequestQueueViewSet,
    RequestsViewSet,
)
from apps.orgs.api import BranchViewSet, RegionViewSet
from apps.people.management_api import (
    ManagementPersonnelCreateUserView,
    ManagementPersonnelDetail,
    ManagementPersonnelListCreate,
    ManagementSeedDemoView,
    ManagementUserDetail,
    ManagementUserSetPassword,
    ManagementUsersList,
)
from apps.people.rose_sso import RoseSSOView
from apps.people.api import (
    MeView,
    PersonnelImportTemplateView,
    PersonnelImportView,
    TokenObtainPairWithLockoutView,
    TokenRefreshView,
)
from apps.reports.api import (
    AnnualReportExcelView,
    DisciplinaryReportExcelView,
    ManagerBoardViewSet,
    MonthlyReportExcelView,
    MonthlyReportPreviewView,
    MonthlySummaryViewSet,
    YearTrendPreviewView,
)
from apps.messaging.api import (
    ConversationViewSet,
    MessagePartnerViewSet,
    NotificationViewSet,
)
from apps.ops.api import HealthView
from apps.scheduling.api import ShiftViewSet

router = DefaultRouter()
router.register("attendance/events", AttendanceEventViewSet, basename="attendance-events")
router.register("attendance/sessions", AttendanceSessionViewSet, basename="attendance-sessions")
router.register("attendance/daily", DailyBoardViewSet, basename="attendance-daily")
router.register("attendance/overtime", OvertimeProposalViewSet, basename="attendance-overtime")
router.register("attendance/review-queue", ReviewQueueViewSet, basename="review-queue")
router.register("reports/monthly-summaries", MonthlySummaryViewSet, basename="monthly-summaries")
router.register("reports/manager-board", ManagerBoardViewSet, basename="manager-board")
router.register("requests", RequestsViewSet, basename="requests")
router.register("requests/queue", RequestQueueViewSet, basename="request-queue")
router.register("leave-types", LeaveTypeViewSet, basename="leave-types")
router.register("org/regions", RegionViewSet, basename="org-regions")
router.register("org/branches", BranchViewSet, basename="org-branches")
router.register("scheduling/shifts", ShiftViewSet, basename="scheduling-shifts")
router.register("leaves/ledger", LeaveLedgerViewSet, basename="leave-ledger")
router.register("messages/partners", MessagePartnerViewSet, basename="msg-partners")
router.register("messages/conversations", ConversationViewSet, basename="msg-conversations")
router.register("messages/notifications", NotificationViewSet, basename="msg-notifications")

api_v1 = [
    path("auth/token/", TokenObtainPairWithLockoutView.as_view(), name="token-obtain-pair"),
    # ورود یکپارچه (SSO) با رز هاب — Rose Hub
    path("auth/rose-sso/", RoseSSOView.as_view(), name="rose-sso"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", MeView.as_view(), name="me"),
    path("people/import/", PersonnelImportView.as_view(), name="people-import"),
    path("people/import/template/", PersonnelImportTemplateView.as_view(), name="people-import-template"),
    path("reports/monthly/preview/", MonthlyReportPreviewView.as_view(), name="reports-monthly-preview"),
    path("reports/monthly/excel/", MonthlyReportExcelView.as_view(), name="reports-monthly-excel"),
    path("reports/annual/preview/", YearTrendPreviewView.as_view(), name="reports-annual-preview"),
    path("reports/annual/excel/", AnnualReportExcelView.as_view(), name="reports-annual-excel"),
    path("reports/disciplinary/excel/", DisciplinaryReportExcelView.as_view(), name="reports-disciplinary-excel"),
    path("leaves/ledger/template/", LedgerTemplateView.as_view(), name="leave-ledger-template"),
    path("leaves/ledger/import/", LedgerImportView.as_view(), name="leave-ledger-import"),
    path("health/", HealthView.as_view(), name="health"),
    # مدیریت پرسنل و کاربران خارج از پنل ادمین (فقط HR/ADMIN/superuser)
    path("management/personnel/", ManagementPersonnelListCreate.as_view(), name="mgmt-personnel"),
    path("management/personnel/<int:employee_id>/", ManagementPersonnelDetail.as_view(), name="mgmt-personnel-detail"),
    path("management/personnel/<int:employee_id>/create-user/", ManagementPersonnelCreateUserView.as_view(), name="mgmt-personnel-create-user"),
    path("management/users/", ManagementUsersList.as_view(), name="mgmt-users"),
    path("management/users/<int:user_id>/", ManagementUserDetail.as_view(), name="mgmt-user-detail"),
    path("management/users/<int:user_id>/set-password/", ManagementUserSetPassword.as_view(), name="mgmt-user-password"),
    path("management/seed-demo/", ManagementSeedDemoView.as_view(), name="mgmt-seed-demo"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/v1/", include(router.urls)),
]
