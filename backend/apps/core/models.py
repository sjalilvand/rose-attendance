"""Abstract base models shared by all apps."""
from django.db import models


class TimeStampedModel(models.Model):
    """created_at / updated_at bookkeeping (schema.sql convention)."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
