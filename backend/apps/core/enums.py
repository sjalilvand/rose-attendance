"""Shared enumeration values — exact match with schema.sql (data model §10)."""
from django.db import models


class EventType(models.TextChoices):
    CHECK_IN = "CHECK_IN", "ورود"
    CHECK_OUT = "CHECK_OUT", "خروج"


class Channel(models.TextChoices):
    ANDROID = "ANDROID", "اپ اندروید"
    PWA = "PWA", "وب‌اپ"


class ConnectionMode(models.TextChoices):
    ONLINE = "ONLINE", "آنلاین"
    OFFLINE_SYNC = "OFFLINE_SYNC", "همگام‌سازی آفلاین"


class LocationStatus(models.TextChoices):
    IN_RANGE = "IN_RANGE", "در محدوده"
    OUT_OF_RANGE = "OUT_OF_RANGE", "خارج از محدوده"
    UNAVAILABLE = "UNAVAILABLE", "بدون موقعیت"
    LOW_ACCURACY = "LOW_ACCURACY", "دقت پایین"


class EventStatus(models.TextChoices):
    ACCEPTED = "ACCEPTED", "پذیرفته‌شده"
    NEEDS_REVIEW = "NEEDS_REVIEW", "در انتظار رسیدگی"
    REJECTED_TECHNICAL = "REJECTED_TECHNICAL", "رد فنی"


class SessionState(models.TextChoices):
    COMPLETE = "COMPLETE", "کامل"
    OPEN = "OPEN", "باز"
    INVALID_SEQUENCE = "INVALID_SEQUENCE", "ترتیب نامعتبر"


class AdjustmentKind(models.TextChoices):
    TIME_FIX = "TIME_FIX", "اصلاح زمان"
    BRANCH_FIX = "BRANCH_FIX", "اصلاح شعبه"
    PAIRING = "PAIRING", "اصلاح جفت‌سازی"
    SESSION_SPLIT = "SESSION_SPLIT", "تفکیک بازه"
    VOID = "VOID", "ابطال"


class EmploymentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "شاغل"
    SUSPENDED = "SUSPENDED", "تعلیق"
    TERMINATED = "TERMINATED", "خاتمه همکاری"


class RestMode(models.TextChoices):
    FIXED = "FIXED", "کسر کامل"
    DEDUCT_IF_SHORT = "DEDUCT_IF_SHORT", "کسر در کارکرد کوتاه"
    NONE = "NONE", "بدون کسر"


class ShiftSource(models.TextChoices):
    PATTERN = "PATTERN", "الگوی چرخشی"
    MANUAL = "MANUAL", "دستی"
    OVERRIDE = "OVERRIDE", "استثنایی"


class RequestStatus(models.TextChoices):
    DRAFT = "DRAFT", "پیش‌نویس"
    PENDING = "PENDING", "در انتظار"
    APPROVED = "APPROVED", "تأییدشده"
    REJECTED = "REJECTED", "ردشده"
    CANCELLED = "CANCELLED", "لغوشده"


class SegmentStatus(models.TextChoices):
    PENDING = "PENDING", "در انتظار"
    APPROVED = "APPROVED", "تأییدشده"
    REJECTED = "REJECTED", "ردشده"
    CANCELLED = "CANCELLED", "لغوشده"


class ApprovalAction(models.TextChoices):
    APPROVE = "APPROVE", "تأیید"
    REJECT = "REJECT", "رد"
    CANCEL = "CANCEL", "لغو"
    RETURN = "RETURN", "برگشت"


class LeaveEntryKind(models.TextChoices):
    OPENING = "OPENING", "مانده اولیه"
    ACCRUAL = "ACCRUAL", "استحقاق"
    DEDUCTION = "DEDUCTION", "کسر"
    RESTORE = "RESTORE", "بازگشت مانده"
    ADJUST = "ADJUST", "تعدیل"


class RuleKind(models.TextChoices):
    LATE = "LATE", "تأخیر"
    EARLY_LEAVE = "EARLY_LEAVE", "تعجیل"
    REST = "REST", "استراحت"
    OVERTIME = "OVERTIME", "اضافه‌کاری"
    HOLIDAY = "HOLIDAY", "تعطیلات"
    ABSENCE = "ABSENCE", "غیبت"


class RuleScope(models.TextChoices):
    GLOBAL = "GLOBAL", "سراسری"
    REGION = "REGION", "منطقه"
    BRANCH = "BRANCH", "شعبه"


class RuleStatus(models.TextChoices):
    DRAFT = "DRAFT", "پیش‌نویس"
    ACTIVE = "ACTIVE", "فعال"
    RETIRED = "RETIRED", "بازنشسته"


class SummaryState(models.TextChoices):
    PROVISIONAL = "PROVISIONAL", "موقت"
    FINAL = "FINAL", "قطعی"
    ADJUSTED = "ADJUSTED", "اصلاح‌شده"


class RoleCode(models.TextChoices):
    EMPLOYEE = "EMPLOYEE", "پرسنل"
    BRANCH_MANAGER = "BRANCH_MANAGER", "مدیر شعبه"
    REGION_MANAGER = "REGION_MANAGER", "مدیر منطقه"
    HR = "HR", "منابع انسانی"
    ADMIN = "ADMIN", "ادمین"
    AUDITOR = "AUDITOR", "حسابرس"
