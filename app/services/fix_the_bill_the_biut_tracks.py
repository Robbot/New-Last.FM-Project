#!/usr/bin/env python3
"""Canonicalize The Bill's ``The Biut`` scrobbles and track entities.

The correction is deliberately album-scoped for scrobble text. Track entities
that already belong to the canonical album track list are reused, and obsolete
accentless entities are removed only after all references have been repointed.

Usage:
    python -m app.services.fix_the_bill_the_biut_tracks --dry-run
    python -m app.services.fix_the_bill_the_biut_tracks
"""

import argparse
import sqlite3
from pathlib import Path


ARTIST = "The Bill"
ALBUM = "The Biut"
RENAMES = (
    ("Bunt Szarego", "Buntszarego", 25515, 31757),
    ("Palac", "Pałac", 25514, 31756),
    ("My Nie Jestesmy Z Wami", "My Nie Jesteśmy Z Wami", 28426, 28426),
    ("Piosenka O Wisle", "Piosenka O Wiśle", 25516, 25516),
    ("Piosenka o Wiśle", "Piosenka O Wiśle", 25516, 25516),
    ("Szara Szarosc", "Szara szarość", 25517, 25517),
)


def run(dry_run: bool = False) -> None:
    db_path = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for old, canonical, old_id, canonical_id in RENAMES:
            target = conn.execute(
                "SELECT title FROM track WHERE track_id = ?", (canonical_id,)
            ).fetchone()
            if target is None:
                raise RuntimeError(f"Missing canonical track_id {canonical_id}")

            if old_id == canonical_id:
                changed = conn.execute(
                    """UPDATE scrobble SET track = ?, track_id = ?
                       WHERE artist = ? AND album = ? AND track = ?""",
                    (canonical, canonical_id, ARTIST, ALBUM, old),
                ).rowcount
            else:
                changed = conn.execute(
                    """UPDATE scrobble SET track = ?, track_id = ?
                       WHERE artist = ? AND album = ?
                         AND (track = ? OR track_id = ?)""",
                    (canonical, canonical_id, ARTIST, ALBUM, old, old_id),
                ).rowcount

            conn.execute(
                "UPDATE track SET title = ? WHERE track_id = ?",
                (canonical, canonical_id),
            )

            if old_id != canonical_id:
                conn.execute(
                    "UPDATE album_tracks SET track_id = ? WHERE track_id = ?",
                    (canonical_id, old_id),
                )
                conn.execute(
                    "UPDATE track_alias SET track_id = ? WHERE track_id = ?",
                    (canonical_id, old_id),
                )
                refs = sum(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE track_id = ?", (old_id,)
                    ).fetchone()[0]
                    for table in ("scrobble", "album_tracks", "track_alias")
                )
                if refs == 0:
                    conn.execute("DELETE FROM track WHERE track_id = ?", (old_id,))

            print(f"{old!r} -> {canonical!r}: {changed} scrobble(s)")

        remaining = conn.execute(
            """SELECT COUNT(*) FROM scrobble
               WHERE artist = ? AND album = ?
                 AND track NOT IN (
                   SELECT track FROM album_tracks WHERE artist = ? AND album = ?
                 )""",
            (ARTIST, ALBUM, ARTIST, ALBUM),
        ).fetchone()[0]
        print(f"Non-canonical album scrobbles remaining: {remaining}")
        if remaining:
            raise RuntimeError("The Biut still has non-canonical scrobble titles")

        if dry_run:
            conn.rollback()
            print("Dry run rolled back")
        else:
            conn.commit()
            print("Changes committed")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.dry_run)


if __name__ == "__main__":
    main()
