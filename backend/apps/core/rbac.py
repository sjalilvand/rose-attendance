"""Role-based access helpers shared by manager-facing APIs.

Scope contract (roles seeded in people.0002_seed_roles):
- superuser / HR / ADMIN / REGION_MANAGER → global scope (None = all branches)
- BRANCH_MANAGER → ids of their active branch assignments
- anyone else → no managerial scope ([])
"""
from __future__ import annotations

from apps.people.models import User

MANAGER_ROLES = ("BRANCH_MANAGER", "REGION_MANAGER", "HR", "ADMIN")
GLOBAL_ROLES = ("REGION_MANAGER", "HR", "ADMIN")


def is_manager(user: User) -> bool:
    return user.is_superuser or any(user.has_role(role) for role in MANAGER_ROLES)


def scoped_branch_ids(user: User) -> list[int] | None:
    """None → unrestricted (global); [] → no managerial access at all."""
    if user.is_superuser or any(user.has_role(role) for role in GLOBAL_ROLES):
        return None
    return list(
        user.role_assignments.filter(role__code="BRANCH_MANAGER").values_list("branch_id", flat=True)
    )
