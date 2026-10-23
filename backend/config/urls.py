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

api_v1 = [
    path("auth/token/", TokenObtainPairWithLockoutView.as_view(), name="token-obtain-pair"),
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
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/v1/", include(router.urls)),
]
