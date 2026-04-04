#!/usr/bin/env python3
"""
Monitor newly added scrobbles for suffix discrepancies.

This service detects when new scrobbles contain suffixes that differ from
existing similar tracks - helping identify new suffix patterns to add to
sync_lastfm.py cleaning functions.

Usage:
    python -m app.services.monitor_new_scrobbles [--since-days N]

Options:
    --since-days N    Only check scrobbles from the last N days (default: 7)
"""

import sqlite3
import re
import unicodedata
import logging
import argparse
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timedelta, timezone
from app.logging_config import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


# ---------- Normalization helpers ----------

def _normalize_for_matching(text: str) -> str:
    """
    Normalize text for fuzzy matching - very aggressive.
    Strips accents, lowercases, removes most punctuation.
    """
    if not text:
        return ""

    # Remove accents
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])

    # Lowercase
    text = text.lower()

    # Remove punctuation
    text = re.sub(r'[\'".,:;!?(){}\[\]<>–—\-/]+', '', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def _get_core_name(name: str) -> str:
    """
    Get the 'core' name by stripping common suffix patterns aggressively.
    This is more aggressive than clean_remastered_suffix - it's designed
    for matching, not for display.
    """
    if not name:
        return ""

    core = name.lower()

    # Strip these common suffix patterns
    suffix_patterns = [
        r'\s*-\s*\d{4}\s+remastered\s+version\s*$',
        r'\s*-\s*\d{4}\s+digital\s+remaster\s*$',
        r'\s*-\s*\d{4}\s+remaster(ed)?\s*$',
        r'\s*-\s*\d{4}\s+(stereo|mono)\s+mix\s*$',
        r'\s*-\s*single\s+version\s*$',
        r'\s*-\s+album\s+version\s*$',
        r'\s*-\s+remix\s*$',
        r'\s*-\s+(?:deluxe|expanded)\s+edition\s*$',
        r'\s*\[\d{4}\s+remaster(ed)?\]\s*$',
        r'\s*\(\d{4}\s+remaster(ed)?\)\s*$',
        r'\s*\[remastered\]\s*$',
        r'\s*\(remastered\)\s*$',
        r'\s*-\s+live\s*$',
        r'\s*-\s*\d{4}\s*$',  # Bare year
    ]

    for pattern in suffix_patterns:
        core = re.sub(pattern, '', core, flags=re.IGNORECASE)

    return core.strip()


# ---------- Database helpers ----------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_scrobbles_since(days: int = 7) -> list[dict]:
    """Get scrobbles from the last N days."""
    conn = get_conn()
    cur = conn.cursor()

    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

    cur.execute("""
        SELECT id, artist, album, track, uts
        FROM scrobble
        WHERE uts >= ?
        ORDER BY uts DESC
    """, (cutoff_ts,))

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def build_core_name_index(scrobbles: list[dict]) -> dict:
    """
    Build an index of (artist, album) -> {core_track: [scrobbles]}.
    """
    index = defaultdict(lambda: defaultdict(list))

    for s in scrobbles:
        key = (_normalize_for_matching(s['artist']), _normalize_for_matching(s['album'] or ''))
        core = _get_core_name(s['track'])
        index[key][core].append(s)

    return index


def find_discrepancies(recent_scrobbles: list[dict], all_index: dict) -> list[dict]:
    """
    Find discrepancies where recent scrobbles have suffixes not in existing data.
    """
    discrepancies = []

    # Build a set of recent scrobble IDs
    recent_ids = {s['id'] for s in recent_scrobbles}

    for new in recent_scrobbles:
        key = (_normalize_for_matching(new['artist']), _normalize_for_matching(new['album'] or ''))
        new_core = _get_core_name(new['track'])

        # Find all scrobbles with the same core name (including older ones)
        matching_scrobbles = all_index.get(key, {}).get(new_core, [])

        # Find scrobbles with different track names but same core
        for match in matching_scrobbles:
            if match['id'] == new['id']:
                continue

            if match['track'] != new['track']:
                # Found a discrepancy - same core, different display names
                suffix_diff = _extract_suffix_diff(new['track'], match['track'])

                # Skip case-only differences (not real suffix issues)
                if suffix_diff in (' (case only)', ' (small word case)'):
                    continue

                discrepancies.append({
                    'new_track': new['track'],
                    'existing_track': match['track'],
                    'artist': new['artist'],
                    'album': new['album'] or '',
                    'suffix': suffix_diff,
                    'new_id': new['id'],
                    'existing_id': match['id'],
                    'core': new_core,
                    'is_recent': match['id'] in recent_ids,
                })

    return discrepancies


def _extract_suffix_diff(new_name: str, existing_name: str) -> str:
    """Extract the suffix that differs between two track names."""

    # Check if it's just a case difference (ignore these)
    if new_name.lower() == existing_name.lower():
        return " (case only)"

    # Check for small word capitalization differences (e.g., "From" vs "from")
    new_words = new_name.split()
    existing_words = existing_name.split()

    if len(new_words) == len(existing_words):
        case_only = True
        for nw, ew in zip(new_words, existing_words):
            if nw.lower() != ew.lower():
                case_only = False
                break
        if case_only:
            return " (small word case)"

    # Look for actual suffix patterns
    suffix_indicators = ['-', 'remastered', 'remaster', 'version', 'mix', 'deluxe', 'expanded',
                         'live', 'single', 'album', 'stereo', 'mono', 'edition']

    new_lower = new_name.lower()
    existing_lower = existing_name.lower()

    new_has_suffix = any(indicator in new_lower for indicator in suffix_indicators)
    existing_has_suffix = any(indicator in existing_lower for indicator in suffix_indicators)

    # Simple approach: see if one contains the other
    if new_name.startswith(existing_name):
        diff = new_name[len(existing_name):].strip()
        if diff and new_has_suffix:
            return diff
        elif diff:
            return f" (additional text: {diff})"
    elif existing_name.startswith(new_name):
        diff = existing_name[len(new_name):].strip()
        if diff and existing_has_suffix:
            return f"existing: {diff}"
        elif diff:
            return f" (existing has: {diff})"

    # Find common prefix
    common_len = 0
    min_len = min(len(new_name), len(existing_name))
    for i in range(min_len):
        if new_name[i].lower() == existing_name[i].lower():
            common_len += 1
        else:
            break

    if common_len > 3:  # Meaningful common base
        new_suffix = new_name[common_len:].strip()
        existing_suffix = existing_name[common_len:].strip()
        if new_suffix and not existing_suffix and new_has_suffix:
            return f"new: {new_suffix}"
        elif existing_suffix and not new_suffix and existing_has_suffix:
            return f"existing: {existing_suffix}"
        elif new_suffix and existing_suffix:
            return f"new: {new_suffix} | existing: {existing_suffix}"

    return " (other difference)"


# ---------- Reporting ----------

def find_album_track_mismatches(conn: sqlite3.Connection) -> list[dict]:
    """
    Find mismatches between scrobble and album_tracks tables.
    These are cases where track names differ (punctuation, abbreviations, etc.)
    causing lookups to fail.
    """
    mismatches = []

    cur = conn.cursor()

    # Get all unique (artist, album, track) from scrobble
    cur.execute("""
        SELECT DISTINCT artist, album, track
        FROM scrobble
        WHERE album IS NOT NULL AND album != '' AND track IS NOT NULL AND track != ''
    """)
    scrobble_tracks = {(row['artist'], row['album'], row['track']): row for row in cur.fetchall()}

    # Get all from album_tracks
    cur.execute("""
        SELECT DISTINCT artist, album, track
        FROM album_tracks
        WHERE album IS NOT NULL AND album != '' AND track IS NOT NULL AND track != ''
    """)
    album_tracks = {(row['artist'], row['album'], row['track']): row for row in cur.fetchall()}

    # Build normalized lookup for album_tracks
    album_tracks_norm = {}
    for (artist, album, track), row in album_tracks.items():
        key = (
            _normalize_for_matching(artist),
            _normalize_for_matching(album),
            _normalize_for_matching(track)
        )
        if key not in album_tracks_norm:
            album_tracks_norm[key] = []
        album_tracks_norm[key].append(row)

    # Check each scrobble track against album_tracks
    for (artist, album, track), scrobble_row in scrobble_tracks.items():
        key = (
            _normalize_for_matching(artist),
            _normalize_for_matching(album),
            _normalize_for_matching(track)
        )

        # Skip if exact match exists (no mismatch)
        if (artist, album, track) in album_tracks:
            continue

        # Check if there's a normalized match (same base, different formatting)
        if key in album_tracks_norm:
            for album_track_row in album_tracks_norm[key]:
                # Found a mismatch!
                at_track = album_track_row['track']

                # Skip if names are identical (shouldn't happen due to above check, but just in case)
                if track == at_track:
                    continue

                # Skip if just case difference
                if track.lower() == at_track.lower():
                    continue

                # Determine the type of mismatch
                diff_type = _classify_mismatch(track, at_track)

                mismatches.append({
                    'type': 'album_track_mismatch',
                    'scrobble_track': track,
                    'album_track_track': at_track,
                    'artist': artist,
                    'album': album,
                    'diff_type': diff_type,
                })

    return mismatches


def _classify_mismatch(name1: str, name2: str) -> str:
    """Classify the type of mismatch between two names."""
    # Check for common punctuation differences
    punctuation_diffs = []
    for punct in ['.', ',', "'", '"', '!', '?', '-', '/']:
        if punct in name1 and punct not in name2:
            punctuation_diffs.append(f"name1 has '{punct}'")
        elif punct in name2 and punct not in name1:
            punctuation_diffs.append(f"name2 has '{punct}'")

    if punctuation_diffs:
        return "punctuation: " + ", ".join(punctuation_diffs)

    # Check for abbreviations
    abbreviations = {
        'mr': 'mr.', 'mrs': 'mrs.', 'ms': 'ms.', 'dr': 'dr.',
        'prof': 'prof.', 'rev': 'rev.', 'hon': 'hon.', 'sr': 'sr.', 'jr': 'jr.'
    }

    for short, full in abbreviations.items():
        if short in name1.lower() and full in name2.lower():
            return "abbreviation"
        elif full in name2.lower() and short in name1.lower():
            return "abbreviation"

    # Check for ampersand vs "and"
    if '&' in name1 and ' and ' in name2.lower():
        return "ampersand vs and"
    if '&' in name2 and ' and ' in name1.lower():
        return "and vs ampersand"

    return "other"


def report_discrepancies(discrepancies: list[dict]) -> None:
    """Report findings to console and log."""
    if not discrepancies:
        logger.info("No suffix discrepancies found.")
        return

    # Group by suffix pattern
    suffix_groups = defaultdict(list)
    for d in discrepancies:
        suffix_groups[d['suffix']].append(d)

    print(f"\n{'='*80}")
    print(f"Found {len(discrepancies)} suffix discrepancies across {len(suffix_groups)} patterns:")
    print(f"{'='*80}\n")

    # Sort by frequency
    for suffix, items in sorted(suffix_groups.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"\n[{len(items)}x] Suffix: '{suffix}'")

        # Show unique examples (limit 3)
        shown = set()
        for d in items:
            example = (d['artist'], d['album'], d['existing_track'], d['new_track'])
            if example not in shown:
                shown.add(example)
                print(f"   {d['artist']}: \"{d['existing_track']}\" vs \"{d['new_track']}\"")
                if len(shown) >= 3:
                    break

        if len(items) > len(shown):
            print(f"   ... and {len(items) - len(shown)} more")

    print(f"\n{'='*80}")
    print("Add these patterns to _REMASTER_PATTERNS in sync_lastfm.py")
    print(f"{'='*80}\n")


def report_album_track_mismatches(mismatches: list[dict]) -> None:
    """Report scrobble vs album_tracks mismatches."""
    if not mismatches:
        logger.info("No scrobble/album_tracks mismatches found.")
        return

    # Group by diff_type
    type_groups = defaultdict(list)
    for m in mismatches:
        type_groups[m['diff_type']].append(m)

    print(f"\n{'='*80}")
    print(f"Found {len(mismatches)} scrobble vs album_tracks mismatches:")
    print(f"{'='*80}\n")
    print("These cause track detail lookups to fail because names don't match exactly.")

    # Sort by frequency
    for diff_type, items in sorted(type_groups.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"\n[{len(items)}x] {diff_type}")

        # Show unique examples (limit 5)
        shown = set()
        for m in items:
            example = (m['artist'], m['album'], m['scrobble_track'], m['album_track_track'])
            if example not in shown:
                shown.add(example)
                print(f"   {m['artist']} - {m['album']}:")
                print(f"     scrobble:  \"{m['scrobble_track']}\"")
                print(f"     alb_track: \"{m['album_track_track']}\"")
                if len(shown) >= 5:
                    break

        if len(items) > len(shown):
            print(f"   ... and {len(items) - len(shown)} more")

    print(f"\n{'='*80}")
    print("Fix with: python -m app.services.clean_track_case_db")
    print("Or update normalization in sync_lastfm.py")
    print(f"{'='*80}\n")


def suggest_patterns(discrepancies: list[dict]) -> list[str]:
    """Suggest regex patterns based on found discrepancies."""
    suggestions = []
    seen = set()

    for d in discrepancies:
        suffix = d['suffix'].lower()

        if suffix in seen:
            continue
        seen.add(suffix)

        # Pattern detection
        if 'remastered version' in suffix:
            count = sum(1 for x in discrepancies if 'remastered version' in x['suffix'].lower())
            suggestions.append(f"# YYYY Remastered Version (~{count} occurrences)")
            suggestions.append(r'r" -\s+\d{4}\s+(?:Remastered|Remaster)\s+(?:Version|version)\s*$",')
        elif 'digital remaster' in suffix:
            count = sum(1 for x in discrepancies if 'digital remaster' in x['suffix'].lower())
            suggestions.append(f"# YYYY Digital Remaster (~{count} occurrences)")
            suggestions.append(r'r" -\s+\d{4}\s+(?:Digital\s+)?(?:Remastered|Remaster)\s*$",')
        elif 'single version' in suffix:
            count = sum(1 for x in discrepancies if 'single version' in x['suffix'].lower())
            suggestions.append(f"# Single Version (~{count} occurrences)")
            suggestions.append(r'r" -\s+(?:Single Version|single version)\s*$",')
        elif suffix.startswith('[') and 'remaster' in suffix:
            count = sum(1 for x in discrepancies if x['suffix'].startswith('['))
            suggestions.append(f"# [YYYY Remaster] pattern (~{count} occurrences)")
            suggestions.append(r'r"\s*\[\s*\d{4}\s+(?:Remastered|Remaster)\s*\]\s*$",')
        elif suffix.startswith('(') and 'remaster' in suffix:
            count = sum(1 for x in discrepancies if x['suffix'].startswith('('))
            suggestions.append(f"# (YYYY Remaster) pattern (~{count} occurrences)")
            suggestions.append(r'r"\s*\(\s*\d{4}\s+(?:Remastered|Remaster)\s*\)\s*$",')
        else:
            # Unknown pattern - show the actual suffix
            suggestions.append(f"# TODO: Pattern for suffix: {suffix[:50]}")

    return suggestions


# ---------- Main ----------

def main() -> None:
    parser = argparse.ArgumentParser(description='Monitor for suffix discrepancies in scrobbles')
    parser.add_argument('--since-days', type=int, default=7,
                        help='Check scrobbles from last N days (default: 7)')
    parser.add_argument('--check-mismatches', action='store_true',
                        help='Also check scrobble vs album_tracks mismatches')
    args = parser.parse_args()

    logger.info(f"Checking scrobbles from last {args.since_days} days...")

    # Get recent scrobbles
    recent = get_scrobbles_since(days=args.since_days)
    logger.info(f"Found {len(recent)} recent scrobbles.")

    # Also get ALL scrobbles to build complete index for comparison
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, artist, album, track, uts FROM scrobble")
    all_scrobbles = [dict(row) for row in cur.fetchall()]
    conn.close()

    logger.info(f"Total scrobbles in database: {len(all_scrobbles)}")

    # Build index
    all_index = build_core_name_index(all_scrobbles)

    # Find suffix discrepancies
    discrepancies = find_discrepancies(recent, all_index)
    report_discrepancies(discrepancies)

    if discrepancies:
        print("Suggested patterns to add:\n")
        suggestions = suggest_patterns(discrepancies)
        for s in suggestions:
            print(s)

    # Check for scrobble/album_tracks mismatches if requested
    if args.check_mismatches:
        logger.info("Checking scrobble vs album_tracks mismatches...")
        conn = get_conn()
        mismatches = find_album_track_mismatches(conn)
        conn.close()
        report_album_track_mismatches(mismatches)

    total_issues = len(discrepancies)
    if args.check_mismatches:
        total_issues += len(mismatches)

    logger.info(f"Monitor complete. Found {total_issues} total issues.")


if __name__ == "__main__":
    main()
