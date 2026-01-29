#!/usr/bin/env python3
"""
SQLite Database Backup Script

This script:
1. Checkpoints the WAL file into the main SQLite database
2. Creates a timestamped backup
3. Optionally rotates old backups

Usage:
    python -m app.services.backup_db [--keep N]

    N = number of backups to keep (default: 30)
"""

import sqlite3
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
BACKUP_DIR = BASE_DIR / "files" / "backups"

# Default number of backups to keep
DEFAULT_KEEP = 30


def checkpoint_wal(db_path: Path) -> bool:
    """
    Force SQLite to checkpoint the WAL file into the main database.
    This ensures all data in the WAL is written to the main database file.

    Returns True if successful, False otherwise.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        # PRAGMA wal_checkpoint(TRUNCATE) does:
        # 1. Checkpoints all WAL data to main database
        # 2. Truncates the WAL file to 0 bytes (saves disk space)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        return True
    except sqlite3.Error as e:
        print(f"Error checkpointing WAL: {e}", file=sys.stderr)
        return False


def create_backup(db_path: Path, backup_dir: Path) -> Path | None:
    """
    Create a timestamped backup of the database.
    Returns the path to the backup file, or None on failure.
    """
    try:
        # Ensure backup directory exists
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamped filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"lastfmstats_{timestamp}.sqlite"
        backup_path = backup_dir / backup_name

        # Copy the database file
        shutil.copy2(db_path, backup_path)

        return backup_path
    except (OSError, shutil.Error) as e:
        print(f"Error creating backup: {e}", file=sys.stderr)
        return None


def rotate_backups(backup_dir: Path, keep: int) -> None:
    """
    Remove old backups, keeping only the most recent 'keep' backups.
    """
    if keep <= 0:
        return

    try:
        # Get all backup files sorted by modification time (newest first)
        backups = sorted(
            backup_dir.glob("lastfmstats_*.sqlite"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        # Remove old backups beyond 'keep'
        for old_backup in backups[keep:]:
            old_backup.unlink()
            print(f"Removed old backup: {old_backup.name}")

    except OSError as e:
        print(f"Error rotating backups: {e}", file=sys.stderr)


def verify_backup(backup_path: Path) -> bool:
    """
    Verify that the backup is a valid SQLite database.
    """
    try:
        conn = sqlite3.connect(str(backup_path))
        # Run a simple query to verify integrity
        conn.execute("PRAGMA integrity_check")
        conn.close()
        return True
    except sqlite3.Error:
        return False


def main(keep: int = DEFAULT_KEEP) -> int:
    """
    Main backup function.
    Returns 0 on success, 1 on failure.
    """
    print(f"Starting backup at {datetime.now(timezone.utc).isoformat()}")

    # Verify database exists
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        return 1

    # Step 1: Checkpoint WAL to main database
    print("Checkpointing WAL file...")
    if not checkpoint_wal(DB_PATH):
        print("Failed to checkpoint WAL file", file=sys.stderr)
        return 1
    print("WAL checkpoint complete")

    # Step 2: Create backup
    print("Creating backup...")
    backup_path = create_backup(DB_PATH, BACKUP_DIR)
    if not backup_path:
        print("Failed to create backup", file=sys.stderr)
        return 1

    # Step 3: Verify backup
    print(f"Backup created: {backup_path}")
    print("Verifying backup integrity...")
    if not verify_backup(backup_path):
        print("Warning: Backup verification failed", file=sys.stderr)
        # Don't fail on verification warning

    # Step 4: Rotate old backups
    print(f"Rotating backups (keeping {keep})...")
    rotate_backups(BACKUP_DIR, keep)

    print(f"Backup complete at {datetime.now(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    keep = DEFAULT_KEEP

    # Parse command line arguments
    args = sys.argv[1:]

    for i, arg in enumerate(args):
        if arg in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif arg in ("--keep", "-k"):
            if i + 1 < len(args):
                try:
                    keep = int(args[i + 1])
                except ValueError:
                    print(f"Invalid value for --keep: {args[i + 1]}", file=sys.stderr)
                    sys.exit(1)
            else:
                print("--keep requires a number argument", file=sys.stderr)
                sys.exit(1)

    sys.exit(main(keep))
