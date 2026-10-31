"""People domain — employees, users, roles, dated role assignments, sessions.

Schema.sql tables: employees, users, roles, permissions, role_permissions,
role_assignments, sessions. Password hashing is Argon2id (section 6).
"""
from __future__ import annotations

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.enums import Channel, EmploymentStatus, RoleCode
from apps.core.models import TimeStampedModel


class Employee(TimeStampedModel):
    """Personnel file (section 5). personnel_code keeps leading zeros."""

    personnel_code = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    mobile = models.CharField(max_length=15, blank=True)
    national_id = models.CharField(max_length=10, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    employment_status = models.CharField(
        max_length=12,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.ACTIVE,
    )
    hired_on = models.DateField(null=True, blank=True)
    terminated_on = models.DateField(null=True, blank=True)
    home_branch = models.ForeignKey(
        "orgs.Branch", on_delete=models.PROTECT, related_name="home_employees"
    )
    manager = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports"
    )

    class Meta:
        db_table = "employees"
        verbose_name = "پرسنل"
        verbose_name_plural = "پرسنل"
        indexes = [models.Index(fields=["home_branch"])]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.personnel_code} — {self.full_name}"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, username: str, password: str | None, **extra):
        if not username:
            raise ValueError("username is required")
        user = self.model(username=username, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username: str, password: str, **extra):
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_active", True)
        if extra["is_superuser"] is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(username, password, **extra)


class User(PermissionsMixin, AbstractBaseUser, TimeStampedModel):
    """Login account bound 1:1 to an employee (sections 3 and 6).

    System accounts (e.g. the initial superuser created with createsuperuser)
    may have no personnel file — employee is nullable for them; every business
    API continues to require an employee for attendance/leave flows.
    """

    employee = models.OneToOneField(
        Employee,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="user_account",
        help_text="پروندهٔ پرسنلی؛ برای کاربران سیستمی مثل superuser می‌تواند تهی باشد",
    )
    username = models.CharField(max_length=60, unique=True)
    # AbstractBaseUser's password column renamed to password_hash per schema.
    password = models.CharField(max_length=255, db_column="password_hash")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="دسترسی پنل ادمین")
    # فاز ۶۵ — مشخصات منتقل‌شده از رز هاب در ورود یکپارچه (SSO)؛
    # منبع حقیقت رز هاب است و در هر ورود بروزرسانی می‌شود.
    full_name = models.CharField(max_length=200, blank=True, help_text="نام و نام خانوادگی (رز هاب)")
    mobile = models.CharField(max_length=20, blank=True, help_text="موبایل (رز هاب)")
    national_id = models.CharField(max_length=15, blank=True, help_text="کد ملی — نام کاربری رز هاب")
    province = models.CharField(max_length=80, blank=True, help_text="استان")
    province_code = models.CharField(max_length=10, blank=True, help_text="کد استان")
    clinic = models.CharField(max_length=200, blank=True, help_text="کلینک محل خدمت")
    failed_attempts = models.PositiveIntegerField(
        default=0, validators=[MinValueValidator(0)]
    )
    locked_until = models.DateTimeField(null=True, blank=True)
    # AbstractBaseUser's last_login column renamed per schema.
    last_login = models.DateTimeField(null=True, blank=True, db_column="last_login_at")

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    def register_failed_attempt(self, max_attempts: int, lock_minutes: int) -> None:
        self.failed_attempts = models.F("failed_attempts") + 1
        self.save(update_fields=["failed_attempts"])
        self.refresh_from_db(fields=["failed_attempts"])
        if self.failed_attempts >= max_attempts:
            self.locked_until = timezone.now() + timezone.timedelta(minutes=lock_minutes)
            self.failed_attempts = 0
            self.save(update_fields=["locked_until", "failed_attempts"])

    def reset_failed_attempts(self) -> None:
        if self.failed_attempts or self.locked_until:
            self.failed_attempts = 0
            self.locked_until = None
            self.save(update_fields=["failed_attempts", "locked_until"])

    def active_role_codes(self, branch_id: int | None = None) -> list[str]:
        today = timezone.localdate()
        qs = self.role_assignments.filter(
            models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=today),
            valid_from__lte=today,
        ).select_related("role")
        if branch_id is not None:
            qs = qs.filter(models.Q(branch__isnull=True) | models.Q(branch_id=branch_id))
        return sorted({ra.role.code for ra in qs})

    def has_role(self, code: str, branch_id: int | None = None) -> bool:
        return code in self.active_role_codes(branch_id=branch_id)

    def __str__(self) -> str:  # pragma: no cover
        return self.username


class Role(models.Model):
    code = models.CharField(max_length=30, unique=True, choices=RoleCode.choices)
    name = models.CharField(max_length=120)

    class Meta:
        db_table = "roles"
        verbose_name = "نقش"
        verbose_name_plural = "نقش‌ها"

    def __str__(self) -> str:  # pragma: no cover
        return self.code


class Permission(models.Model):
    code = models.CharField(max_length=60, unique=True)
    area = models.CharField(max_length=20)  # ATTENDANCE / REQUESTS / REPORTS / SETTINGS
    level = models.CharField(max_length=10)  # NONE / VIEW / ACT

    class Meta:
        db_table = "permissions"
        verbose_name = "مجوز"
        verbose_name_plural = "مجوزها"

    def __str__(self) -> str:  # pragma: no cover
        return self.code


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="+")

    class Meta:
        db_table = "role_permissions"
        verbose_name = "مجوز نقش"
        verbose_name_plural = "مجوزهای نقش"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="uq_role_permission"),
        ]


class RoleAssignment(TimeStampedModel):
    """Dated role assignment; branch-scoped roles carry branch_id."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    branch = models.ForeignKey(
        "orgs.Branch", null=True, blank=True, on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "role_assignments"
        verbose_name = "تخصیص نقش"
        verbose_name_plural = "تخصیص‌های نقش"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=models.F("valid_from")),
                name="chk_role_period",
            ),
        ]
        indexes = [models.Index(fields=["user", "valid_from", "valid_to"])]


class SSOIdentity(TimeStampedModel):
    """External single-sign-on identity linked to a local user (section 6).

    One user may keep identities from several providers, but one provider must
    never map to two users — hence the unique (provider, subject) constraint.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sso_identities")
    provider = models.CharField(max_length=255, help_text="issuer URL تنظیم‌شده در SSO_ISSUER")
    subject = models.CharField(max_length=255, help_text="claim `sub` شناسهٔ ثابت کاربر نزد ارائه‌دهنده")
    email = models.CharField(max_length=254, blank=True)

    class Meta:
        db_table = "sso_identities"
        verbose_name = "هویت ورود یکپارچه"
        verbose_name_plural = "هویت‌های ورود یکپارچه"
        constraints = [
            models.UniqueConstraint(fields=["provider", "subject"], name="uq_sso_provider_subject"),
        ]
        indexes = [models.Index(fields=["user"])]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.user.username} ← {self.provider}"


class SSOLoginState(models.Model):
    """Single-use CSRF state for the SSO authorization-code round-trip.

    Stored in the DB (not the cache) so every gunicorn worker validates the
    same state; rows are deleted on consumption and swept opportunistically.
    """

    state = models.CharField(max_length=128, unique=True)
    redirect_to = models.CharField(max_length=255)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "sso_login_states"
        verbose_name = "وضعیت ورود یکپارچه"
        verbose_name_plural = "وضعیت‌های ورود یکپارچه"

    @classmethod
    def sweep(cls) -> None:
        cls.objects.filter(expires_at__lt=timezone.now()).delete()

    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()


class SSOUsedToken(models.Model):
    """Registry of consumed one-time SSO tokens (replay protection).

    Stores only the SHA-256 of the raw token, so a leaked DB dump cannot
    resurrect anything. Rows older than ~15 minutes are swept on access.
    """

    token_hash = models.CharField(max_length=128, unique=True)
    provider = models.CharField(max_length=64, default="rose-hub")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "sso_used_tokens"
        verbose_name = "توکن مصرف‌شدهٔ SSO"
        verbose_name_plural = "توکن‌های مصرف‌شدهٔ SSO"

    @classmethod
    def try_consume(cls, raw_token: str, provider: str = "rose-hub") -> bool:
        """Returns True on first consumption, False if already used."""
        import hashlib

        from django.db import IntegrityError, transaction

        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        cls.objects.filter(
            provider=provider,
            created_at__lt=timezone.now() - timezone.timedelta(minutes=15),
        ).delete()
        try:
            # atomic داخلی = savepoint؛ خطای یکتایی، تراکنش بیرونی را خراب نمی‌کند
            with transaction.atomic():
                cls.objects.create(token_hash=digest, provider=provider)
            return True
        except IntegrityError:
            return False


class DeviceSession(TimeStampedModel):
    """Refresh/session registry — retention >= 90 days (section 6)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_sessions")
    refresh_token_hash = models.CharField(max_length=128, unique=True)
    device_label = models.CharField(max_length=120, blank=True)
    platform = models.CharField(max_length=10, choices=Channel.choices)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sessions"
        verbose_name = "نشست دستگاه"
        verbose_name_plural = "نشست‌های دستگاه"
        indexes = [
            models.Index(
                fields=["user"],
                condition=models.Q(revoked_at__isnull=True),
                name="idx_sessions_user_active",
            ),
        ]
