-- ============================================================================
-- رز سفید — اسکلت DDL پایگاه داده (فاز ۱، نسخه ۰٫۱)
-- مبتنی بر: docs/analysis/01-data-model.md و سند جامع نیازمندی‌ها نسخه ۲٫۱ (مصوب)
-- موتور: PostgreSQL 16 + PostGIS
-- وضعیت: اسکلت برای تثبیت در فاز ۲؛ این فایل معادل Migrationهای Django خواهد شد
-- نکته: همه زمان‌ها TIMESTAMPTZ و مدت‌ها به دقیقه؛ تقویم دوره‌ها شمسی سازمان است
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- ----------------------------------------------------------------------------
-- Enumها (مطابق بخش ۱۰ سند مدل داده)
-- ----------------------------------------------------------------------------
CREATE TYPE event_type_enum       AS ENUM ('CHECK_IN', 'CHECK_OUT');
CREATE TYPE channel_enum          AS ENUM ('ANDROID', 'PWA');
CREATE TYPE connection_enum       AS ENUM ('ONLINE', 'OFFLINE_SYNC');
CREATE TYPE location_status_enum  AS ENUM ('IN_RANGE', 'OUT_OF_RANGE', 'UNAVAILABLE', 'LOW_ACCURACY');
CREATE TYPE event_status_enum     AS ENUM ('ACCEPTED', 'NEEDS_REVIEW', 'REJECTED_TECHNICAL');
CREATE TYPE session_state_enum    AS ENUM ('COMPLETE', 'OPEN', 'INVALID_SEQUENCE');
CREATE TYPE adjustment_kind_enum  AS ENUM ('TIME_FIX', 'BRANCH_FIX', 'PAIRING', 'SESSION_SPLIT', 'VOID');
CREATE TYPE employment_status_enum AS ENUM ('ACTIVE', 'SUSPENDED', 'TERMINATED');
CREATE TYPE rest_mode_enum        AS ENUM ('FIXED', 'DEDUCT_IF_SHORT', 'NONE');
CREATE TYPE shift_source_enum     AS ENUM ('PATTERN', 'MANUAL', 'OVERRIDE');
CREATE TYPE request_status_enum   AS ENUM ('DRAFT', 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED');
CREATE TYPE segment_status_enum   AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED');
CREATE TYPE approval_action_enum  AS ENUM ('APPROVE', 'REJECT', 'CANCEL', 'RETURN');
CREATE TYPE leave_entry_kind_enum AS ENUM ('OPENING', 'ACCRUAL', 'DEDUCTION', 'RESTORE', 'ADJUST');
CREATE TYPE rule_kind_enum        AS ENUM ('LATE', 'EARLY_LEAVE', 'REST', 'OVERTIME', 'HOLIDAY', 'ABSENCE');
CREATE TYPE rule_scope_enum       AS ENUM ('GLOBAL', 'REGION', 'BRANCH');
CREATE TYPE rule_status_enum      AS ENUM ('DRAFT', 'ACTIVE', 'RETIRED');
CREATE TYPE summary_state_enum    AS ENUM ('PROVISIONAL', 'FINAL', 'ADJUSTED');

-- ----------------------------------------------------------------------------
-- حوزه سازمانی
-- ----------------------------------------------------------------------------
CREATE TABLE regions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        VARCHAR(20)  NOT NULL UNIQUE,
    name        VARCHAR(120) NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE branches (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                 VARCHAR(20)  NOT NULL UNIQUE,
    name                 VARCHAR(160) NOT NULL,
    region_id            BIGINT       NOT NULL REFERENCES regions(id),
    province             VARCHAR(80),
    city                 VARCHAR(80),
    address              TEXT,
    phone                VARCHAR(20),
    manager_employee_id  BIGINT,      -- FK به employees پس از تعریف آن (ALTER در انتهای فایل)
    delegate_employee_id BIGINT,
    geo_latitude         DOUBLE PRECISION,
    geo_longitude        DOUBLE PRECISION,
    -- شعاع مصوب نسخه ۲٫۱: پیش‌فرض ۱۵۰ متر شهری / ۳۰۰ متر کلینیک، بازه مجاز ۵۰ تا ۱٬۰۰۰
    geo_radius_m         INT          NOT NULL DEFAULT 150 CHECK (geo_radius_m BETWEEN 50 AND 1000),
    work_calendar_id     BIGINT,
    is_active            BOOLEAN      NOT NULL DEFAULT true,
    active_from          DATE,
    active_to            DATE,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_branch_geo CHECK (
        (geo_latitude IS NULL AND geo_longitude IS NULL) OR
        (geo_latitude IS NOT NULL AND geo_longitude IS NOT NULL)
    )
);

-- توسعه آینده: چند نقطه مجاز برای هر شعبه (بخش ۴ سند)
CREATE TABLE branch_geo_points (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id   BIGINT       NOT NULL REFERENCES branches(id),
    label       VARCHAR(80)  NOT NULL,
    geom        geography(POINT, 4326) NOT NULL,
    radius_m    INT          NOT NULL CHECK (radius_m BETWEEN 50 AND 1000),
    is_active   BOOLEAN      NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_geo_points_branch ON branch_geo_points(branch_id) WHERE is_active;

CREATE TABLE employees (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    personnel_code  VARCHAR(20)  NOT NULL UNIQUE,   -- حفظ صفر ابتدایی با نوع رشته‌ای
    first_name      VARCHAR(80)  NOT NULL,
    last_name       VARCHAR(80)  NOT NULL,
    mobile          VARCHAR(15),
    national_id     VARCHAR(10),
    job_title       VARCHAR(120),
    employment_status employment_status_enum NOT NULL DEFAULT 'ACTIVE',
    hired_on        DATE,
    terminated_on   DATE,
    home_branch_id  BIGINT       NOT NULL REFERENCES branches(id),
    manager_employee_id BIGINT REFERENCES employees(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_employees_home_branch ON employees(home_branch_id);

ALTER TABLE branches
    ADD CONSTRAINT fk_branch_manager   FOREIGN KEY (manager_employee_id)   REFERENCES employees(id),
    ADD CONSTRAINT fk_branch_delegate  FOREIGN KEY (delegate_employee_id)  REFERENCES employees(id);

-- ارتباط تاریخ‌دار فرد و شعبه (بخش ۵ سند)
CREATE TABLE employee_branch_assignments (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES employees(id),
    branch_id   BIGINT NOT NULL REFERENCES branches(id),
    valid_from  DATE   NOT NULL,
    valid_to    DATE,                      -- NULL = بدون تاریخ پایان
    is_allowed  BOOLEAN NOT NULL DEFAULT true,
    created_by  BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_assignment_period CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CONSTRAINT uq_assignment UNIQUE (employee_id, branch_id, valid_from)
);
CREATE INDEX idx_assignment_employee_date ON employee_branch_assignments(employee_id, valid_from, valid_to);
CREATE INDEX idx_assignment_branch_date   ON employee_branch_assignments(branch_id, valid_from, valid_to);

-- حساب‌ها و دسترسی (بخش‌های ۳ و ۶ سند)
CREATE TABLE users (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id     BIGINT      NOT NULL UNIQUE REFERENCES employees(id),
    username        VARCHAR(60) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,          -- Argon2id (پیشنهاد بخش ۶ سند)
    is_active       BOOLEAN     NOT NULL DEFAULT true,
    failed_attempts INT         NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE roles (
    id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code VARCHAR(30)  NOT NULL UNIQUE,   -- EMPLOYEE / BRANCH_MANAGER / REGION_MANAGER / HR / ADMIN / AUDITOR
    name VARCHAR(120) NOT NULL
);

CREATE TABLE permissions (
    id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code  VARCHAR(60) NOT NULL UNIQUE,
    area  VARCHAR(20) NOT NULL,             -- ATTENDANCE / REQUESTS / REPORTS / SETTINGS
    level VARCHAR(10) NOT NULL              -- NONE / VIEW / ACT
);

CREATE TABLE role_permissions (
    role_id       BIGINT NOT NULL REFERENCES roles(id),
    permission_id BIGINT NOT NULL REFERENCES permissions(id),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE role_assignments (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    role_id     BIGINT NOT NULL REFERENCES roles(id),
    branch_id   BIGINT REFERENCES branches(id),   -- برای نقش‌های شعبه‌محور
    valid_from  DATE   NOT NULL,
    valid_to    DATE,
    assigned_by BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_role_period CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX idx_role_assign_user ON role_assignments(user_id, valid_from, valid_to);

-- نشست‌ها؛ نگهداری حداقل ۹۰ روز (پیشنهاد بخش ۶ سند)
CREATE TABLE sessions (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id            BIGINT       NOT NULL REFERENCES users(id),
    refresh_token_hash VARCHAR(128) NOT NULL UNIQUE,
    device_label       VARCHAR(120),
    platform           channel_enum NOT NULL,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ  NOT NULL,
    revoked_at         TIMESTAMPTZ
);
CREATE INDEX idx_sessions_user_active ON sessions(user_id) WHERE revoked_at IS NULL;

-- ----------------------------------------------------------------------------
-- حوزه زمان‌بندی (بخش ۱۰ سند)
-- ----------------------------------------------------------------------------
CREATE TABLE work_calendars (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       VARCHAR(120) NOT NULL,
    is_default BOOLEAN      NOT NULL DEFAULT false
);

CREATE TABLE calendar_holidays (
    calendar_id  BIGINT      NOT NULL REFERENCES work_calendars(id),
    holiday_date DATE        NOT NULL,
    title        VARCHAR(160),
    kind         VARCHAR(10) NOT NULL DEFAULT 'FULL',  -- FULL / HALF
    PRIMARY KEY (calendar_id, holiday_date)
);

CREATE TABLE shifts (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code             VARCHAR(20)  NOT NULL UNIQUE,
    name             VARCHAR(120) NOT NULL,
    starts_at        TIME         NOT NULL,
    ends_at          TIME         NOT NULL,
    crosses_midnight BOOLEAN      NOT NULL DEFAULT false,   -- شیفت شب
    rest_minutes     INT          NOT NULL DEFAULT 0 CHECK (rest_minutes >= 0),
    rest_mode        rest_mode_enum NOT NULL DEFAULT 'FIXED',
    grace_minutes    INT          NOT NULL DEFAULT 0 CHECK (grace_minutes >= 0),
    valid_from       DATE,
    valid_to         DATE,
    scope_branch_id  BIGINT REFERENCES branches(id)          -- NULL = دامنه عمومی
);

CREATE TABLE shift_patterns (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code             VARCHAR(20)  NOT NULL UNIQUE,
    name             VARCHAR(120) NOT NULL,
    cycle_length_days INT         NOT NULL CHECK (cycle_length_days BETWEEN 1 AND 60),
    start_on_date    DATE         NOT NULL,
    branch_id        BIGINT REFERENCES branches(id),
    valid_from       DATE,
    valid_to         DATE
);

CREATE TABLE shift_pattern_items (
    pattern_id BIGINT NOT NULL REFERENCES shift_patterns(id),
    day_index  INT    NOT NULL CHECK (day_index >= 1),
    shift_id   BIGINT REFERENCES shifts(id),   -- NULL = روز استراحت
    PRIMARY KEY (pattern_id, day_index)
);

-- تخصیص شیفت؛ شیفت شب با work_date (تاریخ شروع) مدیریت می‌شود
CREATE TABLE scheduled_shifts (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id   BIGINT NOT NULL REFERENCES employees(id),
    branch_id     BIGINT NOT NULL REFERENCES branches(id),
    work_date     DATE   NOT NULL,
    shift_id      BIGINT REFERENCES shifts(id),              -- NULL = استراحت/برنامه‌ریزی‌نشده
    source        shift_source_enum NOT NULL DEFAULT 'PATTERN',
    planned_start TIMESTAMPTZ,
    planned_end   TIMESTAMPTZ,
    pattern_id    BIGINT REFERENCES shift_patterns(id),
    note          VARCHAR(200),
    created_by    BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_scheduled_shift UNIQUE (employee_id, branch_id, work_date)
);
CREATE INDEX idx_scheduled_branch_date ON scheduled_shifts(branch_id, work_date);
CREATE INDEX idx_scheduled_employee_date ON scheduled_shifts(employee_id, work_date);

-- ----------------------------------------------------------------------------
-- حوزه تردد (بخش‌های ۷، ۸ و ۹ سند)
-- ----------------------------------------------------------------------------
CREATE TABLE attendance_events (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_uuid        UUID        NOT NULL UNIQUE,          -- تولیدشده روی دستگاه؛ کلید تکرارپذیری
    employee_id       BIGINT      NOT NULL REFERENCES employees(id),
    branch_id         BIGINT      NOT NULL REFERENCES branches(id),
    event_type        event_type_enum NOT NULL,
    device_time       TIMESTAMPTZ NOT NULL,
    server_received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_time    TIMESTAMPTZ,                          -- زمان مؤثر برای محاسبه و نگهداری
    channel           channel_enum      NOT NULL,
    connection_mode   connection_enum   NOT NULL,
    latitude          DOUBLE PRECISION,
    longitude         DOUBLE PRECISION,
    location_accuracy_m DOUBLE PRECISION,
    location_fixed_at TIMESTAMPTZ,
    location_status   location_status_enum NOT NULL DEFAULT 'UNAVAILABLE',
    location_reason   VARCHAR(40),
    event_status      event_status_enum    NOT NULL DEFAULT 'ACCEPTED',
    flags             TEXT[]      NOT NULL DEFAULT '{}',    -- CLOCK_SKEW / STALE_OFFLINE
    local_seq         BIGINT,                               -- فقط برای تحلیل، نه جفت‌سازی
    app_version       VARCHAR(20),
    last_synced_device_at TIMESTAMPTZ,
    client_request_id VARCHAR(64),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_event_geo CHECK (
        (latitude IS NULL AND longitude IS NULL) OR
        (latitude IS NOT NULL AND longitude IS NOT NULL)
    )
);
-- ایندکس‌های حداقلی سند (بخش ۱۶) + صف رسیدگی + عمر نگهداری بر مبنای زمان مؤثر
CREATE INDEX idx_events_emp_eff   ON attendance_events(employee_id, effective_time);
CREATE INDEX idx_events_branch_eff ON attendance_events(branch_id, effective_time);
CREATE INDEX idx_events_review    ON attendance_events(branch_id, event_status, effective_time)
    WHERE event_status = 'NEEDS_REVIEW';
CREATE INDEX idx_events_purge     ON attendance_events(effective_time);

-- بازه‌های حضور؛ واحد پاکسازی (بخش ۱۵ سند) — بدون حذف نرم
CREATE TABLE attendance_sessions (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id        BIGINT      NOT NULL REFERENCES employees(id),
    branch_id          BIGINT      NOT NULL REFERENCES branches(id),
    check_in_event_id  BIGINT      UNIQUE REFERENCES attendance_events(id),
    check_out_event_id BIGINT      UNIQUE REFERENCES attendance_events(id),
    shift_date         DATE        NOT NULL,               -- تاریخ شروع شیفت مرجع
    scheduled_shift_id BIGINT      REFERENCES scheduled_shifts(id),
    session_state      session_state_enum NOT NULL DEFAULT 'OPEN',
    work_minutes       INT,
    is_purged          BOOLEAN     NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_emp_date  ON attendance_sessions(employee_id, shift_date);
CREATE INDEX idx_sessions_branch_date ON attendance_sessions(branch_id, shift_date);
CREATE INDEX idx_sessions_open      ON attendance_sessions(branch_id, session_state)
    WHERE session_state <> 'COMPLETE';

-- اصلاح به‌مثابه لایه تصمیم؛ رویداد اصلی بازنویسی نمی‌شود (بخش ۸ سند)
CREATE TABLE attendance_adjustments (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id             BIGINT REFERENCES attendance_sessions(id),
    target_event_id        BIGINT REFERENCES attendance_events(id),
    adjustment_kind        adjustment_kind_enum NOT NULL,
    original_value         JSONB  NOT NULL,
    corrected_value        JSONB  NOT NULL,
    reason                 TEXT   NOT NULL,
    decided_by             BIGINT NOT NULL REFERENCES users(id),
    decided_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    applies_to_summary_id  BIGINT
);
CREATE INDEX idx_adjustments_session ON attendance_adjustments(session_id, decided_at);

-- ----------------------------------------------------------------------------
-- حوزه درخواست‌ها (بخش ۱۱ سند + تصمیم مصوب چندشعبه‌ای)
-- ----------------------------------------------------------------------------
CREATE TABLE leave_types (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                VARCHAR(30)  NOT NULL UNIQUE,
    name                VARCHAR(120) NOT NULL,
    is_hourly           BOOLEAN      NOT NULL DEFAULT false,
    is_paid             BOOLEAN      NOT NULL DEFAULT true,
    requires_attachment BOOLEAN      NOT NULL DEFAULT false,
    is_active           BOOLEAN      NOT NULL DEFAULT true
);

CREATE TABLE leave_requests (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id      BIGINT NOT NULL REFERENCES employees(id),
    leave_type_id    BIGINT NOT NULL REFERENCES leave_types(id),
    starts_at        TIMESTAMPTZ NOT NULL,
    ends_at          TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
    computed_minutes INT    NOT NULL CHECK (computed_minutes >= 0),
    description      TEXT,
    attachment_file_id BIGINT,
    overall_status   request_status_enum NOT NULL DEFAULT 'DRAFT',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_leave_requests_status_date ON leave_requests(overall_status, starts_at);
CREATE INDEX idx_leave_requests_employee ON leave_requests(employee_id, starts_at);

CREATE TABLE mission_requests (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id          BIGINT      NOT NULL REFERENCES employees(id),
    destination_branch_id BIGINT     REFERENCES branches(id),
    destination_text     VARCHAR(200),
    subject              VARCHAR(200) NOT NULL,
    starts_at            TIMESTAMPTZ NOT NULL,
    ends_at              TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
    computed_minutes     INT         NOT NULL CHECK (computed_minutes >= 0),
    overall_status       request_status_enum NOT NULL DEFAULT 'DRAFT',
    end_report           TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- تفکیک بخش‌های درخواست چندشعبه‌ای؛ وضعیت کلی = ترکیب بخش‌ها (تصویب نسخه ۲٫۱)
CREATE TABLE request_segments (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_kind       VARCHAR(10)  NOT NULL CHECK (request_kind IN ('LEAVE', 'MISSION')),
    leave_request_id   BIGINT REFERENCES leave_requests(id),
    mission_request_id BIGINT REFERENCES mission_requests(id),
    branch_id          BIGINT NOT NULL REFERENCES branches(id),
    starts_at          TIMESTAMPTZ NOT NULL,
    ends_at            TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
    scheduled_shift_id BIGINT REFERENCES scheduled_shifts(id),
    computed_minutes   INT    NOT NULL CHECK (computed_minutes >= 0),
    segment_status     segment_status_enum NOT NULL DEFAULT 'PENDING',
    CONSTRAINT chk_segment_source CHECK (
        (request_kind = 'LEAVE'   AND leave_request_id IS NOT NULL AND mission_request_id IS NULL) OR
        (request_kind = 'MISSION' AND mission_request_id IS NOT NULL AND leave_request_id IS NULL)
    )
);
-- یکتایی بخش‌ها با ایندکس پارشیال؛ UNIQUE ساده روی ستون‌های NULLable رفتار NULL-distinct دارد
CREATE UNIQUE INDEX uq_segment_leave   ON request_segments(leave_request_id, branch_id, starts_at) WHERE request_kind = 'LEAVE';
CREATE UNIQUE INDEX uq_segment_mission ON request_segments(mission_request_id, branch_id, starts_at) WHERE request_kind = 'MISSION';
CREATE INDEX idx_segments_pending ON request_segments(branch_id, segment_status)
    WHERE segment_status = 'PENDING';

CREATE TABLE approval_actions (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id               BIGINT NOT NULL REFERENCES request_segments(id),
    action                   approval_action_enum NOT NULL,
    decided_by_user_id       BIGINT NOT NULL REFERENCES users(id),
    on_behalf_of_employee_id BIGINT REFERENCES employees(id),  -- ثبت جانشین‌گری
    comment                  TEXT,
    decided_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_approval_segment ON approval_actions(segment_id, decided_at);

-- گردش مانده مرخصی؛ بدون حذف نرم، تراکنشی و تکرارپذیر امن (بخش ۱۶ سند)
CREATE TABLE leave_ledger (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id           BIGINT NOT NULL REFERENCES employees(id),
    leave_type_id         BIGINT NOT NULL REFERENCES leave_types(id),
    entry_kind            leave_entry_kind_enum NOT NULL,
    minutes               INT    NOT NULL,
    balance_after_minutes INT    NOT NULL,
    basis_date            DATE   NOT NULL,
    source_type           VARCHAR(30),
    source_id             BIGINT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ledger_emp_type ON leave_ledger(employee_id, leave_type_id, basis_date);

-- ----------------------------------------------------------------------------
-- پیام‌رسانی و اعلان (بخش ۱۲ سند)
-- ----------------------------------------------------------------------------
CREATE TABLE conversations (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind       VARCHAR(10) NOT NULL DEFAULT 'DIRECT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversation_participants (
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    employee_id     BIGINT NOT NULL REFERENCES employees(id),
    PRIMARY KEY (conversation_id, employee_id)
);

CREATE TABLE messages (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id     BIGINT NOT NULL REFERENCES conversations(id),
    sender_employee_id  BIGINT NOT NULL REFERENCES employees(id),
    body                TEXT   NOT NULL,
    client_message_uuid UUID   NOT NULL UNIQUE,   -- ارسال مجدد بدون اثر تکراری
    delivered_at        TIMESTAMPTZ,
    read_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_conv_time ON messages(conversation_id, created_at);
CREATE INDEX idx_messages_purge     ON messages(created_at);   -- نگهداری سه‌ماهه

CREATE TABLE notifications (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipient_employee_id BIGINT NOT NULL REFERENCES employees(id),
    kind                 VARCHAR(40) NOT NULL,
    payload              JSONB       NOT NULL DEFAULT '{}',
    read_at              TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_notifications_recipient ON notifications(recipient_employee_id, created_at);
CREATE INDEX idx_notifications_purge     ON notifications(created_at);

-- ----------------------------------------------------------------------------
-- محاسبه، بستن دوره و عملیات (بخش‌های ۱۰، ۱۳، ۱۵ سند)
-- ----------------------------------------------------------------------------
-- قواعد نسخه‌دار داده‌ای (تصمیم مصوب نسخه ۲٫۱)
CREATE TABLE rule_sets (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rule_kind      rule_kind_enum  NOT NULL,
    scope          rule_scope_enum NOT NULL DEFAULT 'GLOBAL',
    scope_id       BIGINT,                      -- region_id یا branch_id
    payload        JSONB           NOT NULL,
    effective_from DATE            NOT NULL,
    effective_to   DATE,
    status         rule_status_enum NOT NULL DEFAULT 'DRAFT',
    published_by   BIGINT,
    published_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ     NOT NULL DEFAULT now()
);
CREATE INDEX idx_rule_sets_lookup ON rule_sets(rule_kind, scope, scope_id, effective_from, status);

-- خلاصه ماهانه در سطح پرسنل ـ شعبه ـ ماه؛ تقویم شمسی سازمان (تصویب نسخه ۲٫۱)
CREATE TABLE monthly_summaries (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id            BIGINT NOT NULL REFERENCES employees(id),
    branch_id              BIGINT NOT NULL REFERENCES branches(id),
    period_year            SMALLINT NOT NULL,   -- سال شمسی
    period_month           SMALLINT NOT NULL CHECK (period_month BETWEEN 1 AND 12),
    required_minutes       INT NOT NULL DEFAULT 0,
    valid_presence_minutes INT NOT NULL DEFAULT 0,
    accepted_work_minutes  INT NOT NULL DEFAULT 0,
    late_minutes           INT NOT NULL DEFAULT 0,
    early_leave_minutes    INT NOT NULL DEFAULT 0,
    absence_minutes        INT NOT NULL DEFAULT 0,
    shortage_minutes       INT NOT NULL DEFAULT 0,
    overtime_minutes       INT NOT NULL DEFAULT 0,
    leave_minutes_by_type  JSONB NOT NULL DEFAULT '{}',
    mission_minutes        INT NOT NULL DEFAULT 0,
    incomplete_session_count INT NOT NULL DEFAULT 0,
    no_location_count      INT NOT NULL DEFAULT 0,
    out_of_range_count     INT NOT NULL DEFAULT 0,
    rule_set_ids           BIGINT[] NOT NULL DEFAULT '{}',
    summary_state          summary_state_enum NOT NULL DEFAULT 'PROVISIONAL',
    closure_id             BIGINT,
    finalized_at           TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_monthly_summary UNIQUE (employee_id, branch_id, period_year, period_month)
);

CREATE TABLE monthly_closures (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_year SMALLINT    NOT NULL,
    period_month SMALLINT   NOT NULL,
    scope       VARCHAR(10) NOT NULL DEFAULT 'GLOBAL' CHECK (scope IN ('GLOBAL', 'BRANCH')),
    scope_id    BIGINT REFERENCES branches(id),
    state       VARCHAR(12) NOT NULL DEFAULT 'IN_PROGRESS' CHECK (state IN ('IN_PROGRESS', 'CLOSED')),
    closed_by   BIGINT,
    closed_at   TIMESTAMPTZ,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- UNIQUE ساده روی scope_id(NULL برای سراسری) کافی نیست؛ ایندکس تابعی جایگزین می‌شود
CREATE UNIQUE INDEX uq_closure ON monthly_closures(period_year, period_month, scope, COALESCE(scope_id, 0));
ALTER TABLE monthly_summaries
    ADD CONSTRAINT fk_summary_closure FOREIGN KEY (closure_id) REFERENCES monthly_closures(id);

-- بارگذاری Excel (بخش ۱۴ سند؛ سقف پیشنهادی ۱۰MB / ۵۰٬۰۰۰ سطر)
CREATE TABLE import_jobs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_kind    VARCHAR(20) NOT NULL,   -- BRANCHES / EMPLOYEES / ASSIGNMENTS / SHIFTS / SCHEDULE / LEAVE_OPENING
    uploaded_by BIGINT      NOT NULL REFERENCES users(id),
    file_name   VARCHAR(255) NOT NULL,
    mode        VARCHAR(10) NOT NULL DEFAULT 'ADD' CHECK (mode IN ('ADD', 'UPSERT')),
    status      VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED')),
    total_rows  INT NOT NULL DEFAULT 0,
    ok_rows     INT NOT NULL DEFAULT 0,
    error_rows  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE import_errors (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    import_job_id BIGINT      NOT NULL REFERENCES import_jobs(id),
    row_number    INT         NOT NULL,
    column_name   VARCHAR(60),
    error_code    VARCHAR(40) NOT NULL,
    raw_value     TEXT,
    message       TEXT        NOT NULL
);
CREATE INDEX idx_import_errors_job ON import_errors(import_job_id, row_number);

-- حسابرسی؛ بدون متن پیام و مختصات کامل (بخش ۲۷ سند)
CREATE TABLE audit_logs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id BIGINT,
    actor_role    VARCHAR(30),
    action_code   VARCHAR(60) NOT NULL,
    entity_type   VARCHAR(60) NOT NULL,
    entity_id     BIGINT,
    before_value  JSONB,
    after_value   JSONB,
    ip            INET,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id, created_at);
CREATE INDEX idx_audit_actor  ON audit_logs(actor_user_id, created_at);

-- نتیجه هر اجرای پاکسازی (بخش ۱۵ سند)
CREATE TABLE cleanup_runs (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at         TIMESTAMPTZ NOT NULL,
    finished_at        TIMESTAMPTZ,
    dry_run            BOOLEAN     NOT NULL DEFAULT false,
    scoped_periods     JSONB       NOT NULL DEFAULT '[]',
    deleted_events     INT NOT NULL DEFAULT 0,
    deleted_messages   INT NOT NULL DEFAULT 0,
    deleted_notifications INT NOT NULL DEFAULT 0,
    skipped_sessions   INT NOT NULL DEFAULT 0,
    status             VARCHAR(10) NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
    details            JSONB NOT NULL DEFAULT '{}'
);

-- ----------------------------------------------------------------------------
-- یادداشت‌های اجرایی
-- ----------------------------------------------------------------------------
-- ۱) آستانه‌های مصوب نسخه ۲٫۱ از متغیرهای محیطی خوانده می‌شوند و در استارتاپ اعتبارسنجی
--    می‌گردند: CLOCK_SKEW_MINUTES=5، آستانه آفلاین ۷ روز، RETENTION_SUMMARY_MONTHS=24،
--    SYNC_MAX_BATCH=100، UPLOAD_MAX_MB=10.
-- ۲) پارتیشن‌بندی ماهانه attendance_events فعلاً لازم نیست (حدود ۱۷ هزار رویداد در روز
--    کاری بر اساس سند)؛ تصمیم پس از پایلوت با داده واقعی گرفته می‌شود.
-- ۳) این اسکلت در فاز ۲ به Migrationهای Django ترجمه می‌شود و نام‌گذاری آن حفظ خواهد شد.
