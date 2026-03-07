#!/usr/bin/env python3
"""
Fix New Order Peel Sessions tracks.

These tracks are incorrectly tagged as being from "Power, Corruption and Lies"
but should be from "The John Peel Sessions" with the " - Peel Session" suffix
removed from track names.

Affected tracks:
- 5 8 6 - Peel Session -> 5 8 6
- Too Late - Peel Session -> Too Late
- Turn the Heater on - Peel Session -> Turn the Heater on
"""

import sqlite3
from pathlib import Path
import shutil


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

ARTIST = "New Order"
OLD_ALBUM = "Power, Corruption and Lies"
NEW_ALBUM = "The John Peel Sessions"

PEEL_TRACKS = [
    "5 8 6 - Peel Session",
    "Too Late - Peel Session",
    "Turn the Heater on - Peel Session",
]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def main():
    print("Fixing New Order Peel Sessions tracks")
    print(f"Database: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"ERROR: Database file not found at {DB_PATH}")
        return

    # Backup the database before making changes
    backup_path = DB_PATH.with_suffix(".sqlite.backup")
    print(f"\nCreating backup at: {backup_path}")
    shutil.copy2(DB_PATH, backup_path)
    print("Backup created successfully.")

    conn = get_conn()

    try:
        # Show current state
        print("\n--- Current state ---")
        cur = conn.execute(
            """
            SELECT track, album, COUNT(*) as plays
            FROM scrobble
            WHERE artist = ?
              AND album = ?
              AND track LIKE '% - Peel Session'
            GROUP BY track, album
            ORDER BY track
            """,
            (ARTIST, OLD_ALBUM)
        )
        for row in cur.fetchall():
            print(f"  {row['track']:40} | {row['plays']} plays")

        # Update each track
        print("\n--- Updating tracks ---")
        total_updated = 0

        for old_track in PEEL_TRACKS:
            # Remove " - Peel Session" suffix
            new_track = old_track.replace(" - Peel Session", "")

            # Update the scrobbles
            cur = conn.execute(
                """
                UPDATE scrobble
                SET track = ?,
                    album = ?,
                    album_artist = ?
                WHERE artist = ?
                  AND album = ?
                  AND track = ?
                """,
                (new_track, NEW_ALBUM, ARTIST, ARTIST, OLD_ALBUM, old_track)
            )
            updated = cur.rowcount
            total_updated += updated
            if updated > 0:
                print(f"  ✓ '{old_track}' -> '{new_track}' (album: '{NEW_ALBUM}') ({updated} rows)")

        conn.commit()

        # Verify the changes
        print("\n--- Verification: Updated tracks ---")
        cur = conn.execute(
            """
            SELECT track, album, COUNT(*) as plays
            FROM scrobble
            WHERE artist = ? AND album = ?
            GROUP BY track
            ORDER BY track
            """,
            (ARTIST, NEW_ALBUM)
        )
        for row in cur.fetchall():
            print(f"  {row['track']:40} | {row['plays']} plays")

        # Show remaining PCAL tracks
        print("\n--- Remaining Power, Corruption and Lies tracks ---")
        cur = conn.execute(
            """
            SELECT track, COUNT(*) as plays
            FROM scrobble
            WHERE artist = ? AND album = ?
            GROUP BY track
            ORDER BY plays DESC
            """,
            (ARTIST, OLD_ALBUM)
        )
        for row in cur.fetchall():
            print(f"  {row['track']:40} | {row['plays']} plays")

        # Show totals
        cur = conn.execute(
            """
            SELECT COUNT(*) as total
            FROM scrobble
            WHERE artist = ? AND album = ?
            """,
            (ARTIST, OLD_ALBUM)
        )
        pcal_total = cur.fetchone()["total"]

        cur = conn.execute(
            """
            SELECT COUNT(*) as total
            FROM scrobble
            WHERE artist = ? AND album = ?
            """,
            (ARTIST, NEW_ALBUM)
        )
        peel_total = cur.fetchone()["total"]

        print(f"\n--- Totals ---")
        print(f"  Power, Corruption and Lies: {pcal_total} plays")
        print(f"  The John Peel Sessions:     {peel_total} plays")
        print(f"\n✓ Fix complete! Total rows updated: {total_updated}")
        print(f"Backup saved at: {backup_path}")

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        print("\nChanges rolled back. You can restore from backup if needed.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
