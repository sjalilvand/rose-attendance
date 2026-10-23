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
from apps.people.api import MeView, TokenObtainPairWithLockoutView, TokenRefreshView
from apps.reports.api import MonthlySummaryViewSet
from apps.ops.api import HealthView

router = DefaultRouter()
router.register("attendance/events", AttendanceEventViewSet, basename="attendance-events")
router.register("attendance/sessions", AttendanceSessionViewSet, basename="attendance-sessions")
router.register("attendance/daily", DailyBoardViewSet, basename="attendance-daily")
router.register("attendance/overtime", OvertimeProposalViewSet, basename="attendance-overtime")
router.register("attendance/review-queue", ReviewQueueViewSet, basename="review-queue")
router.register("reports/monthly-summaries", MonthlySummaryViewSet, basename="monthly-summaries")

api_v1 = [
    path("auth/token/", TokenObtainPairWithLockoutView.as_view(), name="token-obtain-pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", MeView.as_view(), name="me"),
    path("health/", HealthView.as_view(), name="health"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/v1/", include(router.urls)),
]
