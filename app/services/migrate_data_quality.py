#!/usr/bin/env python3
"""
Migration script to create the data_quality_issues table.

This table tracks data quality issues found during sync and their resolutions.
Tracks:
- Album/track mismatches (album name equals track name)
- Auto-corrections made
- Issues requiring manual review

Usage:
    python -m app.services.migrate_data_quality
"""
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


def migrate():
    """Create the data_quality_issues table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)

    try:
        cursor = conn.cursor()

        # Check if table already exists
        cursor.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='data_quality_issues'
            """
        )
        if cursor.fetchone():
            print("Table 'data_quality_issues' already exists.")
            # Check if columns exist, add them if not
            cols = [r["name"] for r in cursor.execute("PRAGMA table_info(data_quality_issues)").fetchall()]
            if "resolved_at" not in cols:
                cursor.execute("ALTER TABLE data_quality_issues ADD COLUMN resolved_at TIMESTAMP")
                print("Added resolved_at column")
            if "auto_corrected" not in cols:
                cursor.execute("ALTER TABLE data_quality_issues ADD COLUMN auto_corrected BOOLEAN DEFAULT 0")
                print("Added auto_corrected column")
            conn.commit()
            return

        # Create the table
        cursor.execute(
            """
            CREATE TABLE data_quality_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_type TEXT NOT NULL,
                artist_name TEXT NOT NULL,
                album_name TEXT NOT NULL,
                track_name TEXT,
                correct_album_name TEXT,
                confidence INTEGER,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                auto_corrected BOOLEAN DEFAULT 0,
                notes TEXT
            )
            """
        )

        # Create indexes for common queries
        cursor.execute(
            """
            CREATE INDEX idx_dq_status ON data_quality_issues(status)
            """
        )

        cursor.execute(
            """
            CREATE INDEX idx_dq_artist ON data_quality_issues(artist_name)
            """
        )

        cursor.execute(
            """
            CREATE INDEX idx_dq_type ON data_quality_issues(issue_type)
            """
        )

        conn.commit()
        print("Successfully created 'data_quality_issues' table and indexes.")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
