#!/usr/bin/env python3
"""
Analyze and distribute scrobbles from a compilation album to their original albums.
This is useful when a compilation like "20 Years on MTV" should be deleted and
its scrobbles reassigned to the original source albums.
"""

import sqlite3
import sys
import unicodedata
import re
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


def _normalize_for_matching(text: str) -> str:
    """Normalize text for fuzzy matching."""
    if not text:
        return ""

    # Normalize Unicode quotes/apostrophes
    text = text.replace('\u2018', "'")
    text = text.replace('\u2019', "'")
    text = text.replace('\u201c', '"')
    text = text.replace('\u201d', '"')

    # Remove accents
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])

    # Lowercase
    text = text.lower()

    # Replace hyphens and slashes with spaces
    text = re.sub(r'[–—\-/]+', ' ', text)

    # Remove punctuation
    text = re.sub(r'[\'".,:;!?(){}\[\]<>]+', '', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def find_fuzzy_matches(artist: str, track: str, compilation_album: str, conn):
    """Find potential fuzzy matches for a track in other albums."""
    normalized_track = _normalize_for_matching(track)

    # Find all tracks by this artist in other albums
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT album, track, COUNT(*) as count
        FROM scrobble
        WHERE artist = ? AND album != ?
        GROUP BY album, track
        ORDER BY count DESC
    """, (artist, compilation_album))

    candidates = []
    for row in cursor.fetchall():
        other_track = row["track"]
        other_normalized = _normalize_for_matching(other_track)

        # Calculate similarity
        if normalized_track == other_normalized:
            # Exact normalized match - high confidence
            candidates.append({
                "album": row["album"],
                "track": other_track,
                "count": row["count"],
                "confidence": "high",
                "reason": "normalized match"
            })
        elif (normalized_track in other_normalized or
              other_normalized in normalized_track):
            # Partial match - medium confidence
            candidates.append({
                "album": row["album"],
                "track": other_track,
                "count": row["count"],
                "confidence": "medium",
                "reason": "partial match"
            })

    return candidates


def analyze_compilation(compilation_album: str, use_fuzzy: bool = False):
    """
    Analyze a compilation album and find where its tracks should be reassigned.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all unique tracks from the compilation
    cursor.execute("""
        SELECT artist, track, COUNT(*) as count
        FROM scrobble
        WHERE album = ?
        GROUP BY artist, track
        ORDER BY count DESC
    """, (compilation_album,))

    compilation_tracks = cursor.fetchall()

    results = {
        "can_reassign": [],
        "cannot_reassign": [],
        "multiple_candidates": [],
        "fuzzy_matches": [],
        "total_scrobbles": 0,
        "reassignable_scrobbles": 0,
        "fuzzy_reassignable": 0
    }

    for track in compilation_tracks:
        artist = track["artist"]
        track_name = track["track"]
        count = track["count"]
        results["total_scrobbles"] += count

        # Try exact match first
        cursor.execute("""
            SELECT album, COUNT(*) as scrobbles
            FROM scrobble
            WHERE artist = ? AND track = ? AND album != ?
            GROUP BY album
            ORDER BY scrobbles DESC
        """, (artist, track_name, compilation_album))

        other_albums = cursor.fetchall()

        if len(other_albums) == 1:
            results["can_reassign"].append({
                "artist": artist,
                "track": track_name,
                "count": count,
                "target_album": other_albums[0]["album"],
                "target_scrobbles": other_albums[0]["scrobbles"]
            })
            results["reassignable_scrobbles"] += count
        elif len(other_albums) > 1:
            best = other_albums[0]
            results["multiple_candidates"].append({
                "artist": artist,
                "track": track_name,
                "count": count,
                "target_album": best["album"],
                "target_scrobbles": best["scrobbles"],
                "alternatives": [a["album"] for a in other_albums[1:]]
            })
            results["reassignable_scrobbles"] += count
        elif use_fuzzy:
            # Try fuzzy matching
            fuzzy_candidates = find_fuzzy_matches(artist, track_name, compilation_album, conn)
            if fuzzy_candidates:
                best = fuzzy_candidates[0]
                results["fuzzy_matches"].append({
                    "artist": artist,
                    "track": track_name,
                    "count": count,
                    "target_album": best["album"],
                    "target_track": best["track"],
                    "confidence": best["confidence"],
                    "reason": best["reason"],
                    "alternatives": fuzzy_candidates[1:] if len(fuzzy_candidates) > 1 else []
                })
                results["fuzzy_reassignable"] += count
            else:
                results["cannot_reassign"].append({
                    "artist": artist,
                    "track": track_name,
                    "count": count
                })
        else:
            results["cannot_reassign"].append({
                "artist": artist,
                "track": track_name,
                "count": count
            })

    conn.close()
    return results


def distribute_compilation(compilation_album: str, dry_run: bool = True, use_fuzzy: bool = False):
    """
    Distribute scrobbles from compilation to their original albums.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all scrobbles from the compilation
    cursor.execute("""
        SELECT id, artist, album, track, uts, artist_mbid, album_mbid, track_mbid
        FROM scrobble
        WHERE album = ?
        ORDER BY artist, track, uts
    """, (compilation_album,))

    scrobbles = cursor.fetchall()

    # Group by (artist, track)
    track_groups = defaultdict(list)
    for s in scrobbles:
        key = (s["artist"], s["track"])
        track_groups[key].append(s)

    summary = {
        "total_scrobbles": len(scrobbles),
        "updated": 0,
        "skipped": 0,
        "fuzzy_matched": 0,
        "details": []
    }

    for (artist, track), group in track_groups.items():
        # Try exact match first
        cursor.execute("""
            SELECT album, COUNT(*) as count
            FROM scrobble
            WHERE artist = ? AND track = ? AND album != ?
            GROUP BY album
            ORDER BY count DESC
            LIMIT 1
        """, (artist, track, compilation_album))

        target = cursor.fetchone()
        target_album = target[0] if target else None

        # If no exact match and fuzzy is enabled, try fuzzy
        if not target_album and use_fuzzy:
            normalized_track = _normalize_for_matching(track)

            # SQL doesn't have _normalize_for_matching, so we need to do it in Python
            cursor.execute("""
                SELECT album, track, COUNT(*) as count
                FROM scrobble
                WHERE artist = ? AND album != ?
                GROUP BY album, track
                ORDER BY count DESC
            """, (artist, compilation_album))

            for row in cursor.fetchall():
                if _normalize_for_matching(row["track"]) == normalized_track:
                    target_album = row["album"]
                    summary["fuzzy_matched"] += len(group)
                    break

        scrobble_ids = [s["id"] for s in group]

        if target_album:
            if not dry_run:
                cursor.executemany("""
                    UPDATE scrobble
                    SET album = ?
                    WHERE id = ?
                """, [(target_album, sid) for sid in scrobble_ids])

            summary["updated"] += len(scrobble_ids)
            summary["details"].append({
                "artist": artist,
                "track": track,
                "count": len(scrobble_ids),
                "from": compilation_album,
                "to": target_album
            })
        else:
            summary["skipped"] += len(group)

    if not dry_run:
        conn.commit()
    conn.close()

    return summary


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage:")
        print("  python -m app.services.distribute_compilation \"Album Name\" [--dry-run]")
        print("  python -m app.services.distribute_compilation \"Album Name\" --fuzzy [--execute]")
        sys.exit(1)

    compilation_album = sys.argv[1]
    use_fuzzy = "--fuzzy" in sys.argv
    dry_run = "--execute" not in sys.argv

    if dry_run:
        print(f"=== ANALYSIS MODE: {compilation_album} ===\n")
        results = analyze_compilation(compilation_album, use_fuzzy=use_fuzzy)

        print(f"Total scrobbles: {results['total_scrobbles']}")
        print(f"Can reassign (exact): {results['reassignable_scrobbles']}")
        if use_fuzzy:
            print(f"Can reassign (fuzzy): {results['fuzzy_reassignable']}")
        cannot = results['total_scrobbles'] - results['reassignable_scrobbles'] - results['fuzzy_reassignable']
        print(f"Cannot reassign: {cannot}")
        print()

        if results['fuzzy_matches']:
            print(f"Fuzzy matches ({len(results['fuzzy_matches'])} tracks, {results['fuzzy_reassignable']} scrobbles):")
            for t in results['fuzzy_matches'][:10]:
                print(f"  - {t['artist']}: {t['track']} -> {t['target_track']}")
                print(f"    (on {t['target_album']}, {t['confidence']} confidence: {t['reason']})")
            if len(results['fuzzy_matches']) > 10:
                print(f"  ... and {len(results['fuzzy_matches']) - 10} more")
            print()

        if results['cannot_reassign']:
            print(f"Cannot reassign ({len(results['cannot_reassign'])} tracks):")
            for t in results['cannot_reassign'][:10]:
                print(f"  - {t['artist']}: {t['track']} ({t['count']} plays)")
            if len(results['cannot_reassign']) > 10:
                print(f"  ... and {len(results['cannot_reassign']) - 10} more")
            print()

        if not use_fuzzy:
            print("To try fuzzy matching, add --fuzzy flag")
            print("To execute changes, add --execute flag")
        else:
            print("\nTo execute these changes, run:")
            print(f"  python -m app.services.distribute_compilation \"{compilation_album}\" --fuzzy --execute")
    else:
        print(f"=== EXECUTING: {compilation_album} (fuzzy={use_fuzzy}) ===\n")
        summary = distribute_compilation(compilation_album, dry_run=False, use_fuzzy=use_fuzzy)

        print(f"Updated {summary['updated']} scrobbles")
        if summary['fuzzy_matched'] > 0:
            print(f"  (including {summary['fuzzy_matched']} fuzzy-matched)")
        print(f"Skipped {summary['skipped']} scrobbles (no target album)")
        print(f"Total processed: {summary['total_scrobbles']}")


if __name__ == "__main__":
    main()
