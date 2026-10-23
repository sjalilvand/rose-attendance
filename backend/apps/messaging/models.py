"""Messaging domain — conversations, messages (3-month retention), notifications.

Schema.sql section 12. client_message_uuid makes offline re-sends idempotent.
Channels WebSocket transport arrives with the messaging increment.
"""
from __future__ import annotations

import uuid

from django.db import models


class Conversation(models.Model):
    kind = models.CharField(max_length=10, default="DIRECT")  # DIRECT / GROUP
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conversations"
        verbose_name = "گفتگو"
        verbose_name_plural = "گفتگوها"


class ConversationParticipant(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    employee = models.ForeignKey("people.Employee", on_delete=models.CASCADE, related_name="conversations")

    class Meta:
        db_table = "conversation_participants"
        verbose_name = "عضو گفتگو"
        verbose_name_plural = "اعضای گفتگو"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "employee"], name="uq_conversation_participant"
            ),
        ]


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        "people.Employee", on_delete=models.PROTECT, related_name="messages",
        db_column="sender_employee_id",
    )
    body = models.TextField()
    client_message_uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "messages"
        verbose_name = "پیام"
        verbose_name_plural = "پیام‌ها"
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="idx_messages_conv_time"),
            models.Index(fields=["created_at"], name="idx_messages_purge"),
        ]


class Notification(models.Model):
    recipient = models.ForeignKey(
        "people.Employee", on_delete=models.CASCADE, related_name="notifications",
        db_column="recipient_employee_id",
    )
    kind = models.CharField(max_length=40)
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        verbose_name = "اعلان"
        verbose_name_plural = "اعلان‌ها"
        indexes = [
            models.Index(fields=["recipient", "created_at"], name="idx_notifications_recipient"),
            models.Index(fields=["created_at"], name="idx_notifications_purge"),
        ]
