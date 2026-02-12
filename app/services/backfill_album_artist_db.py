#!/usr/bin/env python3
"""
Backfill album_artist for compilation albums.

This script identifies compilation albums (albums with tracks by multiple artists)
and sets album_artist to "Various Artists" for all scrobbles from those albums.
"""

import sqlite3
from pathlib import Path


def get_db_path() -> str:
    """Get the path to the SQLite database."""
    # Determine database location (same logic as db.py)
    db_path_env = Path.cwd() / "files" / "lastfmstats.sqlite"
    if db_path_env.exists():
        return str(db_path_env)
    raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")


def get_conn():
    """Get a database connection."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def is_compilation_album(conn: sqlite3.Connection, album: str) -> bool:
    """
    Determine if an album is a compilation by checking if it has
    tracks by multiple artists (excluding some common patterns).

    Args:
        conn: Database connection
        album: Album name to check

    Returns:
        True if the album appears to be a compilation
    """
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT artist) as artist_count
        FROM scrobble
        WHERE album = ?
        """,
        (album,),
    ).fetchone()

    if not row:
        return False

    # If album has 3+ distinct artists, consider it a compilation
    # (Using 3 instead of 2 to avoid false positives from features)
    return row["artist_count"] >= 3


def backfill_album_artist(conn: sqlite3.Connection) -> int:
    """
    Backfill album_artist for all scrobbles from compilation albums.

    Args:
        conn: Database connection

    Returns:
        Number of scrobbles updated
    """
    # First, find all albums that could be compilations
    albums = conn.execute(
        """
        SELECT DISTINCT album
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        """
    ).fetchall()

    compilation_albums = []
    for row in albums:
        album = row["album"]
        if is_compilation_album(conn, album):
            compilation_albums.append(album)

    print(f"Found {len(compilation_albums)} compilation albums")

    if not compilation_albums:
        return 0

    # Update scrobbles from compilation albums
    # Build the query with placeholders for all albums
    placeholders = ",".join(["?" for _ in compilation_albums])
    cursor = conn.execute(
        f"""
        UPDATE scrobble
        SET album_artist = 'Various Artists'
        WHERE album IN ({placeholders})
          AND (album_artist IS NULL OR album_artist = '')
        """,
        compilation_albums,
    )

    updated = cursor.rowcount
    conn.commit()

    return updated


def print_compilation_albums(conn: sqlite3.Connection, limit: int = 20) -> None:
    """Print compilation albums for verification."""
    rows = conn.execute(
        """
        SELECT album, COUNT(DISTINCT artist) as artist_count, COUNT(*) as track_count
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        GROUP BY album
        HAVING artist_count >= 3
        ORDER BY artist_count DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    print(f"\nTop {limit} albums by artist diversity (potential compilations):")
    print("-" * 70)
    for row in rows:
        print(f"{row['album'][:50]:50} | {row['artist_count']:3} artists | {row['track_count']:4} tracks")


def backfill_non_compilations(conn: sqlite3.Connection) -> int:
    """
    For non-compilation albums, set album_artist to the track artist.

    This handles albums where all tracks are by the same artist.
    """
    cursor = conn.execute(
        """
        UPDATE scrobble
        SET album_artist = artist
        WHERE album_artist IS NULL
          AND album IN (
              SELECT album
              FROM scrobble
              WHERE album IS NOT NULL AND album != ''
              GROUP BY album
              HAVING COUNT(DISTINCT artist) < 3
          )
        """
    )

    updated = cursor.rowcount
    conn.commit()

    return updated


def main():
    """Run the backfill process."""
    print("Starting album_artist backfill...")
    print("This may take a moment for large databases.\n")

    conn = get_conn()

    # Show current state
    total_row = conn.execute(
        "SELECT COUNT(*) as total FROM scrobble"
    ).fetchone()
    null_row = conn.execute(
        "SELECT COUNT(*) as null_count FROM scrobble WHERE album_artist IS NULL"
    ).fetchone()
    print(f"Current state: {null_row['null_count']} / {total_row['total']} scrobbles have NULL album_artist")

    # Show potential compilations
    print_compilation_albums(conn)

    # First backfill non-compilations (albums with single artist)
    print("\nStep 1: Setting album_artist = artist for non-compilation albums...")
    non_compilation_updated = backfill_non_compilations(conn)
    print(f"  Updated {non_compilation_updated} scrobbles")

    # Then backfill compilations
    print("\nStep 2: Setting album_artist = 'Various Artists' for compilations...")
    compilation_updated = backfill_album_artist(conn)
    print(f"  Updated {compilation_updated} scrobbles")

    # Show final state
    null_row_after = conn.execute(
        "SELECT COUNT(*) as null_count FROM scrobble WHERE album_artist IS NULL"
    ).fetchone()
    print(f"\nFinal state: {null_row_after['null_count']} / {total_row['total']} scrobbles have NULL album_artist")

    # Show some examples of album_artist values
    print("\nSample album_artist values:")
    rows = conn.execute(
        """
        SELECT DISTINCT album_artist, COUNT(*) as count
        FROM scrobble
        WHERE album_artist IS NOT NULL
        GROUP BY album_artist
        ORDER BY count DESC
        LIMIT 10
        """
    ).fetchall()
    for row in rows:
        print(f"  {row['album_artist'][:40]:40} {row['count']:6} scrobbles")

    conn.close()
    print("\nBackfill complete!")


if __name__ == "__main__":
    main()
