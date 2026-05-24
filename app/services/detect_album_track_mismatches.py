#!/usr/bin/env python3
"""Detect scrobble tracks that don't match their album's tracklisting."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

from app.db.connections import get_db_connection, _normalize_for_matching

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


def detect_mismatches():
    """Find scrobbles whose track name doesn't match any track in the album's tracklisting."""
    conn = get_db_connection()

    # Get all album_tracks grouped by (artist, album)
    album_tracks_rows = conn.execute(
        "SELECT artist, album, track FROM album_tracks"
    ).fetchall()
    album_track_map = defaultdict(set)
    for row in album_tracks_rows:
        album_track_map[(row["artist"], row["album"])].add(row["track"])

    # Get distinct scrobble tracks per (artist, album) with play counts
    scrobble_rows = conn.execute("""
        SELECT artist, album, track, COUNT(*) as play_count
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        GROUP BY artist, album, track
    """).fetchall()
    conn.close()

    mismatches = []

    for row in scrobble_rows:
        artist, album, track, play_count = (
            row["artist"], row["album"], row["track"], row["play_count"],
        )
        key = (artist, album)

        # Skip if we don't have a tracklisting for this album
        if key not in album_track_map:
            continue

        # Check if track matches any album track (normalized)
        normalized_scrobble = _normalize_for_matching(track)
        found = any(
            _normalize_for_matching(at) == normalized_scrobble
            for at in album_track_map[key]
        )

        if not found:
            mismatches.append({
                "artist": artist,
                "album": album,
                "track": track,
                "play_count": play_count,
                "album_tracks": sorted(album_track_map[key]),
            })

    return mismatches


def write_report(mismatches):
    """Write mismatches to a dated report file and return the path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    report_path = REPORTS_DIR / f"album_track_mismatches_{date_str}.txt"

    # Group by (artist, album)
    by_album = defaultdict(list)
    for m in mismatches:
        by_album[(m["artist"], m["album"])].append(m)

    lines = []
    lines.append(f"Album Track Mismatch Report — {date_str}")
    lines.append(f"Total mismatches: {len(mismatches)} across {len(by_album)} albums")
    lines.append("=" * 70)

    for (artist, album), entries in sorted(by_album.items()):
        lines.append("")
        lines.append(f"{artist} — {album}")
        lines.append("-" * 60)

        lines.append("  Album tracklisting:")
        for t in entries[0]["album_tracks"]:
            lines.append(f"    • {t}")

        lines.append("")
        lines.append("  Mismatched scrobbles:")
        for e in sorted(entries, key=lambda x: -x["play_count"]):
            lines.append(f"    ✗ \"{e['track']}\" ({e['play_count']} plays)")

        lines.append("")
        lines.append("-" * 60)

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main():
    print("Detecting album track mismatches...")
    mismatches = detect_mismatches()
    report_path = write_report(mismatches)

    # Summary
    artists = len(set(m["artist"] for m in mismatches))
    albums = len(set((m["artist"], m["album"]) for m in mismatches))

    print(f"\nFound {len(mismatches)} mismatched track(s) across {albums} album(s) by {artists} artist(s)")
    print(f"Report saved to: {report_path}")

    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
