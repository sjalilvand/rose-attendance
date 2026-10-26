"""Versioned rule sets — approved decision #7 of §34.

Rules are DATA (payload JSONB) with effective dates and BRANCH > REGION >
GLOBAL precedence; nothing is hard-coded. Publication: DRAFT -> ACTIVE, kept
in audit_logs. The used versions are recorded on monthly summaries via
`rule_set_ids` so every report carries its own calculation-rule version.
"""
from __future__ import annotations

import datetime as dt

from django.db import models
from django.utils import timezone

from apps.core.enums import RuleKind, RuleScope, RuleStatus


class RuleSet(models.Model):
    rule_kind = models.CharField(max_length=12, choices=RuleKind.choices)
    scope = models.CharField(max_length=10, choices=RuleScope.choices, default=RuleScope.GLOBAL)
    scope_id = models.BigIntegerField(
        null=True, blank=True, help_text="region_id یا branch_id بسته به scope"
    )
    payload = models.JSONField(help_text="بدنه قاعده؛ ساختار نمونه در سند محاسبه §۶")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=RuleStatus.choices, default=RuleStatus.DRAFT)
    published_by = models.ForeignKey(
        "people.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="published_rules"
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rule_sets"
        verbose_name = "نسخه قاعده"
        verbose_name_plural = "قواعد نسخه‌دار"
        indexes = [
            models.Index(
                fields=["rule_kind", "scope", "scope_id", "effective_from", "status"],
                name="idx_rule_sets_lookup",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(scope="GLOBAL") | models.Q(scope_id__isnull=True),
                name="chk_rule_global_no_scope",
            ),
            models.CheckConstraint(
                condition=~models.Q(scope__in=["REGION", "BRANCH"]) | models.Q(scope_id__isnull=False),
                name="chk_rule_scoped_has_scope",
            ),
        ]

    def covers(self, date: dt.date) -> bool:
        return self.effective_from <= date and (
            self.effective_to is None or date <= self.effective_to
        )

    @classmethod
    def resolve_for(cls, rule_kind: str, branch, date: dt.date) -> "RuleSet | None":
        """BRANCH > REGION > GLOBAL, ACTIVE + covering the date (§6)."""
        candidates = cls.objects.filter(
            rule_kind=rule_kind, status=RuleStatus.ACTIVE
        )
        for scope, sid in (
            (RuleScope.BRANCH, branch.id),
            (RuleScope.REGION, branch.region_id),
            (RuleScope.GLOBAL, None),
        ):
            rule = (
                candidates.filter(scope=scope, scope_id=sid)
                .order_by("-effective_from")
                .first()
            )
            if rule and rule.covers(date):
                return rule
        return None

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.rule_kind}/{self.scope}#{self.scope_id} from {self.effective_from}"


def publish_rule(rule: "RuleSet", user) -> "RuleSet":
    rule.status = RuleStatus.ACTIVE
    rule.published_by = user
    rule.published_at = timezone.now()
    rule.save(update_fields=["status", "published_by", "published_at"])
    return rule
