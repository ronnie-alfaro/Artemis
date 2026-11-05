"""Compatibility names for the webhook adapter's shared notification contracts."""

from app.domain.notifications import (
    NotificationEvent as WebhookEvent,
)
from app.domain.notifications import (
    NotificationPayload as WebhookPayload,
)
from app.domain.notifications import (
    NotificationReceipt as WebhookReceipt,
)

__all__ = ["WebhookEvent", "WebhookPayload", "WebhookReceipt"]
