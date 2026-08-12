#!/usr/bin/env python3
"""
Fold accent/punctuation-variant duplicate track entities onto their canonical
entity — the general, auto-discovering version of fix_track_entity_case_dups.py.
Re-runnable (idempotent).

Root cause (same as the case-dup script): the album_tracks / MB backfill minted a
second track entity per track using a more aggressive normalizer (strips diacritics
+ punctuation) than the scrobble Resolver (preserves them). So one logical track
ends up as several entities whose track_alias rows carry different norm_titles:
  scrobble-seeded : "te quiero puta!" , "ausländer" , "livin' on the edge"
  backfill-minted : "te quiero puta"  , "auslander" , "livin on the edge"

This script discovers every (artist_id, core) group with >1 entity, where core =
NFD-strip-accents + strip-punctuation + lowercase + collapse-ws. For each group it
picks a canonical entity and folds the rest. Folding repoints each orphan's
scrobbles + album_tracks rows + aliases onto the canonical, then deletes the empty
orphan. The canonical ends up resolving under BOTH normalization schemes (its own
preserved aliases + the orphans' stripped aliases), which prevents recurrence.

SCOPE — folds only SAFE groups (at most one entity carries scrobbles):
  - single scrobble-winner : fold the 0-scrobble variants onto the winner.
  - all-zero               : library dedup; canonical by tracklist richness.
Because every orphan has 0 scrobbles in a safe group, the scrobble UPDATE is a
no-op and there is NO UNIQUE(uts, artist, album, track) collision risk. Groups
where >1 entity has scrobbles (real splits that fragment play counts) are DEFERRED
for manual review — not touched here.

EXCLUDES empty-core groups: titles that are entirely non-Latin (Cyrillic,
katakana, emoji) collapse core to "" and would be falsely grouped as one track.

Alias-norm safety: an orphan alias whose (artist_id, norm_title) already exists on
the canonical would violate track_alias PK on repoint. Those rows are DELETED
(canonical already covers that norm_title); the remaining orphan aliases are
repointed. album_tracks PK is (artist, album, track) text, so its track_id repoint
never collides.

Usage:
    python -m app.services.fix_track_entity_variant_dups --dry-run
    python -m app.services.fix_track_entity_variant_dups
"""

import argparse
import re
import sqlite3
import unicodedata
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)


def get_db_path() -> str:
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    if not db_path.exists():
        raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")
    return str(db_path)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _count(conn, sql, params=()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def core_title(title: str) -> str:
    """Aggressive normalization: lowercase, NFD-strip accents, strip punctuation."""
    t = unicodedata.normalize("NFD", title.lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = re.sub(r"[^a-z0-9 ]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def discover_groups(conn):
    """Return {artist_id, core} -> list of track_ids, for groups with >1 entity
    and a non-empty core. Also returns the count of empty-core groups excluded."""
    from collections import defaultdict
    g = defaultdict(list)
    for r in conn.execute("SELECT track_id, title, artist_id FROM track"):
        g[(r["artist_id"], core_title(r["title"]))].append(r["track_id"])
    empty = sum(1 for k, v in g.items() if k[1] == "" and len(v) > 1)
    real = {k: v for k, v in g.items() if k[1] != "" and len(v) > 1}
    return real, empty


def pick_canonical(conn, track_ids):
    """Choose the surviving entity: most scrobbles, then most tracklist rows, then
    has an MBID hint, then lowest track_id (deterministic)."""
    best = None
    for tid in track_ids:
        scrobs = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (tid,))
        at = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (tid,))
        has_mbid = 1 if conn.execute(
            "SELECT mbid FROM track WHERE track_id=?", (tid,)
        ).fetchone()["mbid"] else 0
        key = (scrobs, at, has_mbid, -tid)
        if best is None or key > best[0]:
            best = (key, tid)
    return best[1]


def plan_group(conn, track_ids):
    """Classify a group. Returns (canonical_id, [orphan_ids], status).
    status: 'safe' (<=1 entity has scrobbles), 'defer' (>1 has scrobbles)."""
    canon = pick_canonical(conn, track_ids)
    orphans = [t for t in track_ids if t != canon]
    with_scr = sum(1 for t in orphans
                   if _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (t,)))
    # 'safe' requires every orphan to have 0 scrobbles
    status = "safe" if with_scr == 0 else "defer"
    return canon, orphans, status


def fold_orphan(conn, canon_id, orphan_id):
    """Repoint one orphan's refs onto the canonical, delete the orphan. Returns
    (scrobbles_moved, album_tracks_repointed, aliases_repointed, aliases_dropped)."""
    canon_title = conn.execute(
        "SELECT title FROM track WHERE track_id=?", (canon_id,)
    ).fetchone()["title"]
    moved_scr = conn.execute(
        "UPDATE scrobble SET track=?, track_id=? WHERE track_id=?",
        (canon_title, canon_id, orphan_id),
    ).rowcount
    moved_at = conn.execute(
        "UPDATE album_tracks SET track_id=? WHERE track_id=?",
        (canon_id, orphan_id),
    ).rowcount
    # drop orphan aliases whose norm_title already exists on the canonical (would
    # collide with PK), then repoint the rest
    dropped = conn.execute(
        """DELETE FROM track_alias WHERE track_id=? AND norm_title IN
           (SELECT norm_title FROM track_alias WHERE track_id=?)""",
        (orphan_id, canon_id),
    ).rowcount
    moved_alias = conn.execute(
        "UPDATE track_alias SET track_id=? WHERE track_id=?",
        (canon_id, orphan_id),
    ).rowcount
    # only delete the entity once it has no remaining references
    remaining = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (orphan_id,))
                 + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (orphan_id,))
                 + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (orphan_id,)))
    deleted = 0
    if remaining == 0:
        deleted = conn.execute("DELETE FROM track WHERE track_id=?", (orphan_id,)).rowcount
    return moved_scr, moved_at, moved_alias, dropped, deleted, remaining


def run(dry_run: bool) -> int:
    conn = get_db_connection()
    try:
        return _run(conn, dry_run)
    finally:
        conn.close()


def _run(conn, dry_run: bool) -> int:
    print("=" * 72)
    print(f"Track-entity variant-dup fold  ({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    groups, empty_excluded = discover_groups(conn)
    print(f"\n[discover] {len(groups)} real variant-dup groups "
          f"({sum(len(v) for v in groups.values())} entities); "
          f"{empty_excluded} empty-core (non-Latin) group(s) excluded")

    safe_plan, defer_groups = [], 0
    defer_orphans = 0
    for (aid, core), tids in groups.items():
        canon, orphans, status = plan_group(conn, tids)
        if status == "safe":
            safe_plan.append((aid, core, canon, orphans))
        else:
            defer_groups += 1
            defer_orphans += len(orphans)

    safe_orphans = sum(len(o) for _, _, _, o in safe_plan)
    print(f"[plan] SAFE to fold: {len(safe_plan)} groups / {safe_orphans} orphans")
    print(f"[plan] DEFER (real split, >1 side has scrobbles): "
          f"{defer_groups} groups / {defer_orphans} orphans")

    if not safe_plan:
        print("\nNothing to do — no safe groups (idempotent no-op).")
        return 0

    # sample preview
    print(f"\n[preview] first 15 safe folds:")
    for aid, core, canon, orphans in safe_plan[:15]:
        ar = conn.execute("SELECT name FROM artist WHERE artist_id=?", (aid,)).fetchone()["name"]
        ct = conn.execute("SELECT title FROM track WHERE track_id=?", (canon,)).fetchone()["title"]
        print(f"   {ar[:18]:18} can {canon} {ct[:34]!r:36} <- orphans {orphans}")

    # --- apply every safe fold in one transaction --------------------------
    tot_scr = tot_at = tot_alias = tot_drop = tot_del = 0
    not_deleted = 0
    for aid, core, canon, orphans in safe_plan:
        for orphan in orphans:
            m_scr, m_at, m_alias, m_drop, deleted, remaining = fold_orphan(conn, canon, orphan)
            tot_scr += m_scr
            tot_at += m_at
            tot_alias += m_alias
            tot_drop += m_drop
            tot_del += deleted
            if remaining:
                not_deleted += 1

    print("\n" + "=" * 72)
    print(f"TOTALS  scrobbles moved: {tot_scr} | tracklist rows repointed: {tot_at} | "
          f"aliases repointed: {tot_alias} | dup-alias rows dropped: {tot_drop} | "
          f"entities deleted: {tot_del}")
    if not_deleted:
        print(f"        !! {not_deleted} orphan(s) kept (still had references)")

    # --- post-state ---------------------------------------------------------
    remaining_groups, _ = discover_groups(conn)
    rem_safe = 0
    for (aid, core), tids in remaining_groups.items():
        if plan_group(conn, tids)[2] == "safe":
            rem_safe += 1
    print("\n--- post-state ---")
    print(f"  safe variant-dup groups remaining: {rem_safe} (expect 0)")
    print(f"  deferred real-split groups remaining: {len(remaining_groups) - rem_safe}")
    print(f"  integrity: {conn.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"  dangling track_id refs (scrobble): "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track_id NOT IN (SELECT track_id FROM track)')}")
    print(f"  dangling track_id refs (album_tracks): "
          f"{_count(conn, 'SELECT COUNT(*) FROM album_tracks WHERE track_id IS NOT NULL AND track_id NOT IN (SELECT track_id FROM track)')}")

    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fold accent/punctuation-variant duplicate track entities (safe groups) "
                    "onto their canonical entity"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
