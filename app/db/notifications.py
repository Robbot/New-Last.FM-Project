"""
Notification database operations.

Manages admin notifications for sync issues, skipped inserts,
and other system events that require administrator attention.
"""
import json
import sqlite3
import time
from typing import Optional, List, Dict, Any
from .connections import get_db_connection


def create_notification(
    notification_type: str,
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    severity: str = "info"
) -> int:
    """
    Create a new notification.

    Args:
        notification_type: Type of notification ('sync_skip', 'sync_error', 'discrepancy', 'warning')
        title: Notification title
        message: Notification message
        details: Optional dictionary with additional context (will be JSON serialized)
        severity: Severity level ('info', 'warning', 'error', 'critical')

    Returns:
        The ID of the created notification
    """
    details_json = json.dumps(details) if details else None
    created_at = int(time.time())

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO notifications (type, title, message, details, created_at, severity)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (notification_type, title, message, details_json, created_at, severity)
        )
        conn.commit()
        return cur.lastrowid


def get_notifications(
    include_dismissed: bool = False,
    limit: int = 50,
    severity_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get notifications from the database.

    Args:
        include_dismissed: Whether to include dismissed notifications
        limit: Maximum number of notifications to return
        severity_filter: Optional severity filter ('info', 'warning', 'error', 'critical')

    Returns:
        List of notification dictionaries
    """
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Build query with optional filters
        query = "SELECT * FROM notifications"
        conditions = []
        params = []

        if not include_dismissed:
            conditions.append("dismissed_at IS NULL")

        if severity_filter:
            conditions.append("severity = ?")
            params.append(severity_filter)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()

    # Convert rows to dictionaries and parse JSON details
    notifications = []
    for row in rows:
        notification = dict(row)
        if notification.get("details"):
            try:
                notification["details"] = json.loads(notification["details"])
            except json.JSONDecodeError:
                notification["details"] = None
        notifications.append(notification)

    return notifications


def dismiss_notification(notification_id: int) -> bool:
    """
    Mark a notification as dismissed.

    Args:
        notification_id: The ID of the notification to dismiss

    Returns:
        True if the notification was found and dismissed, False otherwise
    """
    dismissed_at = int(time.time())

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE notifications SET dismissed_at = ? WHERE id = ?",
            (dismissed_at, notification_id)
        )
        conn.commit()
        return cur.rowcount > 0


def dismiss_all_notifications() -> int:
    """
    Mark all active notifications as dismissed.

    Returns:
        The number of notifications that were dismissed
    """
    dismissed_at = int(time.time())

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE notifications SET dismissed_at = ? WHERE dismissed_at IS NULL",
            (dismissed_at,)
        )
        conn.commit()
        return cur.rowcount


def get_unread_count() -> int:
    """
    Get the count of active (undismissed) notifications.

    Returns:
        The number of undismissed notifications
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM notifications WHERE dismissed_at IS NULL")
        count = cur.fetchone()[0]
        return count


def get_unread_count_by_severity() -> Dict[str, int]:
    """
    Get the count of undismissed notifications grouped by severity.

    Returns:
        Dictionary with severity as key and count as value
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT severity, COUNT(*) as count
            FROM notifications
            WHERE dismissed_at IS NULL
            GROUP BY severity
            """
        )
        return {row["severity"]: row["count"] for row in cur.fetchall()}


def delete_old_notifications(days_to_keep: int = 30) -> int:
    """
    Delete old dismissed notifications.

    Args:
        days_to_keep: Number of days to keep dismissed notifications (default: 30)

    Returns:
        The number of notifications deleted
    """
    cutoff_time = int(time.time()) - (days_to_keep * 24 * 60 * 60)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM notifications WHERE dismissed_at IS NOT NULL AND dismissed_at < ?",
            (cutoff_time,)
        )
        conn.commit()
        return cur.rowcount


def ensure_notifications_table() -> None:
    """
    Create the notifications table if it doesn't exist.
    Should be called during app initialization.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT,
                created_at INTEGER NOT NULL,
                dismissed_at INTEGER,
                severity TEXT NOT NULL DEFAULT 'info'
            )
            """
        )

        # Create indexes for better query performance
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_active
            ON notifications(dismissed_at)
            WHERE dismissed_at IS NULL
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_created
            ON notifications(created_at DESC)
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_severity
            ON notifications(severity)
            """
        )

        conn.commit()
