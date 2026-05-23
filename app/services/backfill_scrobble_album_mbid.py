#!/usr/bin/env python3
"""
Backfill album_mbid in scrobble table.

Updates scrobbles missing album_mbid by looking up the MBID from:
1. The album_art table (matching on artist + album)
2. Other scrobbles with the same artist + album that already have album_mbid
3. MusicBrainz API lookup for remaining missing MBIDs
"""

import argparse
import re
import sqlite3
import time
from pathlib import Path

from app.services.fetch_artist_mbid import fetch_album_mbid, MB_SLEEP_SECONDS


def get_db_path() -> str:
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    if db_path.exists():
        return str(db_path)
    raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")


def get_conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _clean_album_name(name: str) -> list[str]:
    """Generate simplified album name variants for MusicBrainz search fallback."""
    seen = set()
    variants = []

    def _add(v):
        if v and v not in seen:
            seen.add(v)
            variants.append(v)

    _add(name)
    # Strip parenthetical suffixes like "(Blue Album)", "(Black Album)"
    _add(re.sub(r'\s*\([^)]+\)\s*$', '', name).strip())
    # Replace en/em dashes and special hyphens with regular hyphens, arrows with >
    normalized = name.replace('–', '-').replace('—', '-').replace('→', '>')
    _add(normalized)
    # Strip parenthetical AND normalize dashes
    _add(re.sub(r'\s*\([^)]+\)\s*$', '', normalized).strip())
    # Normalize apostrophes
    no_curly = name.replace('‘', "'").replace('’', "'")
    _add(no_curly)
    # Take part before " - " as shorthand (e.g. "Gold - Greatest Hits" -> "Gold")
    _add(name.split(' - ')[0].strip())
    # Strip trailing "!" and spaces
    _add(re.sub(r'\s*!+\s*$', '', name).strip())
    # Strip apostrophes (replace with space), collapse spaced dashes
    no_apostrophe = re.sub(r"['‘’]", " ", name)
    collapse_dash = re.sub(r'\s+-\s+', '-', no_apostrophe)
    _add(collapse_dash)
    # Convert digit-digit hyphens to > (e.g. 86-98 -> 86>98)
    _add(re.sub(r'(\d)-(\d)', r'\1>\2', collapse_dash))
    return variants


def backfill_from_album_art(conn: sqlite3.Connection) -> int:
    """Backfill album_mbid from album_art table."""
    album_art_mbids = conn.execute(
        """
        SELECT artist, album, album_mbid
        FROM album_art
        WHERE album_mbid IS NOT NULL AND album_mbid != ''
        """
    ).fetchall()

    print(f"Found {len(album_art_mbids)} albums with MBIDs in album_art table")
    updated = 0

    for row in album_art_mbids:
        cursor = conn.execute(
            """
            UPDATE scrobble
            SET album_mbid = ?
            WHERE artist = ? AND album = ?
              AND (album_mbid IS NULL OR album_mbid = '')
            """,
            (row["album_mbid"], row["artist"], row["album"]),
        )
        updated += cursor.rowcount

    conn.commit()
    print(f"Updated {updated} scrobbles from album_art table")
    return updated


def backfill_from_scrobbles(conn: sqlite3.Connection) -> int:
    """Backfill album_mbid from other scrobbles with the same artist + album."""
    distinct_albums = conn.execute(
        """
        SELECT DISTINCT s.artist, s.album
        FROM scrobble s
        WHERE (s.album_mbid IS NULL OR s.album_mbid = '')
          AND NOT EXISTS (
              SELECT 1 FROM album_art aa
              WHERE aa.artist = s.artist AND aa.album = s.album
                AND aa.album_mbid IS NOT NULL AND aa.album_mbid != ''
          )
        """
    ).fetchall()

    print(f"Found {len(distinct_albums)} distinct albums still missing MBID (not in album_art)")
    updated = 0

    for row in distinct_albums:
        scrobble_row = conn.execute(
            """
            SELECT album_mbid
            FROM scrobble
            WHERE artist = ? AND album = ?
              AND album_mbid IS NOT NULL AND album_mbid != ''
            LIMIT 1
            """,
            (row["artist"], row["album"]),
        ).fetchone()

        if scrobble_row:
            cursor = conn.execute(
                """
                UPDATE scrobble
                SET album_mbid = ?
                WHERE artist = ? AND album = ?
                  AND (album_mbid IS NULL OR album_mbid = '')
                """,
                (scrobble_row["album_mbid"], row["artist"], row["album"]),
            )
            updated += cursor.rowcount

    conn.commit()
    print(f"Updated {updated} scrobbles from other scrobbles")
    return updated


def backfill_from_musicbrainz(conn: sqlite3.Connection, dry_run: bool = False, limit: int = 0) -> int:
    """Backfill album_mbid from MusicBrainz API for remaining missing albums."""
    missing = conn.execute(
        """
        SELECT s.artist, s.album,
               COALESCE(s.artist_mbid, '') as artist_mbid,
               COUNT(*) as cnt
        FROM scrobble s
        WHERE (s.album_mbid IS NULL OR s.album_mbid = '')
        GROUP BY s.artist, s.album
        ORDER BY cnt DESC, s.artist, s.album
        """
    ).fetchall()

    print(f"Found {len(missing)} distinct albums still missing MBID")
    if limit:
        missing = missing[:limit]
        print(f"Processing first {limit} albums")

    updated = 0
    found = 0
    not_found = 0

    for i, row in enumerate(missing, 1):
        artist = row["artist"]
        album = row["album"]
        artist_mbid = row["artist_mbid"] if row["artist_mbid"] else None
        print(f"  [{i}/{len(missing)}] {artist} - {album} ... ", end="", flush=True)

        mbid = None
        for variant in _clean_album_name(album):
            mbid = fetch_album_mbid(artist, variant, artist_mbid=artist_mbid)
            if mbid:
                break
            time.sleep(MB_SLEEP_SECONDS)

        if mbid:
            found += 1
            count = conn.execute(
                "SELECT COUNT(*) as c FROM scrobble WHERE artist = ? AND album = ? AND (album_mbid IS NULL OR album_mbid = '')",
                (artist, album),
            ).fetchone()["c"]

            if not dry_run:
                conn.execute(
                    "UPDATE scrobble SET album_mbid = ? WHERE artist = ? AND album = ? AND (album_mbid IS NULL OR album_mbid = '')",
                    (mbid, artist, album),
                )
                conn.commit()
                updated += count

            print(f"found {mbid} ({count} scrobbles){' [DRY RUN]' if dry_run else ''}")
        else:
            not_found += 1
            print("not found")

        time.sleep(MB_SLEEP_SECONDS)

    print(f"\nMusicBrainz results: {found} found, {not_found} not found")
    print(f"Updated {updated} scrobbles from MusicBrainz API")
    return updated


def print_stats(conn: sqlite3.Connection, label: str) -> None:
    total = conn.execute("SELECT COUNT(*) as c FROM scrobble").fetchone()["c"]
    with_mbid = conn.execute(
        "SELECT COUNT(*) as c FROM scrobble WHERE album_mbid IS NOT NULL AND album_mbid != ''"
    ).fetchone()["c"]
    without_mbid = total - with_mbid
    pct = 100 * with_mbid // total if total else 0
    print(f"\n{label}")
    print(f"  Total scrobbles: {total}")
    print(f"  With album_mbid: {with_mbid} ({pct}%)")
    print(f"  Without album_mbid: {without_mbid}")


def main():
    parser = argparse.ArgumentParser(description="Backfill album_mbid in scrobble table")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without making updates")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of MusicBrainz API lookups (0 = all)")
    parser.add_argument("--skip-passes", action="store_true", help="Skip Pass 1 & 2, go straight to MusicBrainz API")
    args = parser.parse_args()

    print("Starting scrobble album_mbid backfill...\n")

    conn = get_conn()
    print_stats(conn, "Current state:")

    updated_aa = 0
    updated_scrobbles = 0

    if not args.skip_passes:
        print("\n--- Pass 1: From album_art table ---")
        updated_aa = backfill_from_album_art(conn)

        print("\n--- Pass 2: From other scrobbles ---")
        updated_scrobbles = backfill_from_scrobbles(conn)

    print("\n--- Pass 3: From MusicBrainz API ---")
    updated_mb = backfill_from_musicbrainz(conn, dry_run=args.dry_run, limit=args.limit)

    print_stats(conn, "\nFinal state:")

    total_updated = updated_aa + updated_scrobbles + updated_mb
    print(f"\nTotal scrobbles updated: {total_updated}")
    print("Backfill complete!")

    conn.close()


if __name__ == "__main__":
    main()
