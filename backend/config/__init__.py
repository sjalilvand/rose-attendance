"""
Rose Attendance — Django package init.

The Celery application is imported here so that `@shared_task` decorators
register against the right app in every process (web, worker, beat).
"""
from .celery import app as celery_app

__all__ = ("celery_app",)
