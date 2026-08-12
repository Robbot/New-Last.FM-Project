#!/usr/bin/env python3
"""
Fold accent/punctuation-variant duplicate track entities onto their canonical
entity — the general, auto-discovering resolver for the whole class (both safe
groups and real-split groups). Re-runnable (idempotent).

Root cause: the album_tracks / MB backfill minted a second track entity per track
using a more aggressive normalizer (strips diacritics + punctuation) than the
scrobble Resolver (preserves them). So one logical track ends up as several
entities whose track_alias rows carry different norm_titles:
  scrobble-seeded : "te quiero puta!" , "ausländer" , "livin' on the edge"
  backfill-minted : "te quiero puta"  , "auslander" , "livin on the edge"

This script discovers every (artist_id, core) group with >1 entity (core = NFD-
strip-accents + strip-punctuation + lowercase + collapse-ws), picks a canonical
entity per group, and folds the rest. Folding repoints each orphan's scrobbles +
album_tracks rows + aliases onto the canonical, then deletes the empty orphan.
The canonical ends up resolving under BOTH normalization schemes, which prevents
recurrence (no spotify mapping needed; these are not source-tag variants).

TWO group shapes, both folded:
  - safe (<=1 entity has scrobbles): orphans carry 0 scrobbles, so the scrobble
    rewrite is a no-op — pure tracklist/alias repoint + entity delete.
  - real-split (>1 entity has scrobbles): orphans DO carry scrobbles. Moving them
    onto the canonical can collide on UNIQUE(uts, artist, album, track) when the
    same play was double-counted under two spellings (same uts + album, different
    track text — you can't play a track twice in one second). Those duplicate
    scrobbles are DEDUP-DELETED (precedent: fix_strokes_going_shopping_single.py);
    genuinely distinct orphan scrobbles are moved.

DEDUP RULE (group-level, handles multi-orphan groups): among all non-canonical
scrobbles in the group, a scrobble SURVIVES (gets moved to canonical) iff
  (a) no canonical scrobble shares its (uts, album), AND
  (b) it is the lowest-id non-canonical scrobble at its (uts, album).
All other non-canonical scrobbles are deleted. After the move the canonical holds
at most one scrobble per (uts, album), so no UNIQUE violation is possible.

EXCLUDES empty-core groups: titles entirely non-Latin (Cyrillic, katakana, emoji)
collapse core to "" and would be falsely grouped as one track.

ALIAS SAFETY: an orphan alias whose (artist_id, norm_title) already exists on the
canonical would violate track_alias PK on repoint. Those rows are DELETED (the
canonical already covers that norm_title); the rest are repointed. album_tracks PK
is (artist, album, track) text, so its track_id repoint never collides.

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


def _placeholders(n):
    return ",".join("?" * n)


def fold_group(conn, canon_id, orphan_ids):
    """Fold all orphans of one group onto the canonical. Returns a dict of counts:
    dedup_deleted, scrobbles_moved, album_tracks_repointed, aliases_repointed,
    aliases_dropped, entities_deleted, entities_kept."""
    canon_title = conn.execute(
        "SELECT title FROM track WHERE track_id=?", (canon_id,)
    ).fetchone()["title"]
    orphans = tuple(orphan_ids)
    ph = _placeholders(len(orphans))

    # --- scrobbles: dedup-delete the non-survivors, then move the survivors -----
    # A non-canonical scrobble SURVIVES iff (a) no canonical scrobble shares its
    # (uts, album) and (b) it is the lowest-id non-canonical scrobble at (uts, album).
    dedup_deleted = conn.execute(
        f"""
        DELETE FROM scrobble WHERE id IN (
          SELECT s.id FROM scrobble s
          WHERE s.track_id IN ({ph})
            AND NOT (
              NOT EXISTS (SELECT 1 FROM scrobble d
                          WHERE d.track_id=? AND d.uts=s.uts AND d.album=s.album)
              AND s.id = (SELECT MIN(d.id) FROM scrobble d
                          WHERE d.track_id IN ({ph}) AND d.uts=s.uts AND d.album=s.album)
            )
        )
        """,
        orphans + (canon_id,) + orphans,
    ).rowcount
    moved_scr = conn.execute(
        f"UPDATE scrobble SET track=?, track_id=? WHERE track_id IN ({ph})",
        (canon_title, canon_id) + orphans,
    ).rowcount

    # --- album_tracks: repoint (text PK, no collision) -----------------------
    moved_at = conn.execute(
        f"UPDATE album_tracks SET track_id=? WHERE track_id IN ({ph})",
        (canon_id,) + orphans,
    ).rowcount

    # --- aliases: drop colliding norm_titles, repoint the rest ---------------
    aliases_dropped = 0
    aliases_repointed = 0
    for orphan in orphans:
        aliases_dropped += conn.execute(
            """DELETE FROM track_alias WHERE track_id=? AND norm_title IN
               (SELECT norm_title FROM track_alias WHERE track_id=?)""",
            (orphan, canon_id),
        ).rowcount
        aliases_repointed += conn.execute(
            "UPDATE track_alias SET track_id=? WHERE track_id=?",
            (canon_id, orphan),
        ).rowcount

    # --- delete empty orphan entities ----------------------------------------
    entities_deleted = 0
    entities_kept = 0
    for orphan in orphans:
        remaining = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (orphan,))
                     + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (orphan,))
                     + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (orphan,)))
        if remaining == 0:
            entities_deleted += conn.execute(
                "DELETE FROM track WHERE track_id=?", (orphan,)
            ).rowcount
        else:
            entities_kept += 1

    return {
        "dedup_deleted": dedup_deleted,
        "scrobbles_moved": moved_scr,
        "album_tracks_repointed": moved_at,
        "aliases_repointed": aliases_repointed,
        "aliases_dropped": aliases_dropped,
        "entities_deleted": entities_deleted,
        "entities_kept": entities_kept,
    }


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

    # classify for reporting (safe vs real-split), but fold BOTH
    plan = []
    n_safe = n_split = 0
    for (aid, core), tids in groups.items():
        canon = pick_canonical(conn, tids)
        orphans = [t for t in tids if t != canon]
        with_scr = sum(1 for t in orphans
                       if _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (t,)))
        if with_scr == 0:
            n_safe += 1
        else:
            n_split += 1
        plan.append((aid, core, canon, orphans, with_scr))

    orphans_total = sum(len(o) for _, _, _, o, _ in plan)
    print(f"[plan] {len(plan)} groups / {orphans_total} orphans to fold  "
          f"(safe {n_safe}, real-split {n_split})")

    if not plan:
        print("\nNothing to do — no variant-dup groups (idempotent no-op).")
        return 0

    # sample preview (prefer real-split examples — the interesting ones)
    print(f"\n[preview] first 15 folds (real-split flagged with *):")
    shown = 0
    for aid, core, canon, orphans, with_scr in plan:
        if shown >= 15:
            break
        ar = conn.execute("SELECT name FROM artist WHERE artist_id=?", (aid,)).fetchone()["name"]
        ct = conn.execute("SELECT title FROM track WHERE track_id=?", (canon,)).fetchone()["title"]
        flag = " *" if with_scr else ""
        print(f"   {ar[:18]:18} can {canon} {ct[:34]!r:36} <- orphans {orphans}{flag}")
        shown += 1

    # --- apply every fold in one transaction --------------------------------
    tot = {k: 0 for k in ("dedup_deleted", "scrobbles_moved", "album_tracks_repointed",
                          "aliases_repointed", "aliases_dropped", "entities_deleted",
                          "entities_kept")}
    for aid, core, canon, orphans, _w in plan:
        c = fold_group(conn, canon, orphans)
        for k in tot:
            tot[k] += c[k]

    print("\n" + "=" * 72)
    print(f"TOTALS  scrobbles dedup-deleted: {tot['dedup_deleted']} | "
          f"scrobbles moved: {tot['scrobbles_moved']} | "
          f"tracklist rows repointed: {tot['album_tracks_repointed']}")
    print(f"        aliases repointed: {tot['aliases_repointed']} | "
          f"dup-alias rows dropped: {tot['aliases_dropped']} | "
          f"entities deleted: {tot['entities_deleted']}")
    if tot["entities_kept"]:
        print(f"        !! {tot['entities_kept']} orphan(s) kept (still had references)")

    # --- post-state ---------------------------------------------------------
    remaining_groups, _ = discover_groups(conn)
    print("\n--- post-state ---")
    print(f"  variant-dup groups remaining: {len(remaining_groups)} (expect 0)")
    print(f"  integrity: {conn.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"  dangling track_id refs (scrobble): "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track_id NOT IN (SELECT track_id FROM track)')}")
    print(f"  dangling track_id refs (album_tracks): "
          f"{_count(conn, 'SELECT COUNT(*) FROM album_tracks WHERE track_id IS NOT NULL AND track_id NOT IN (SELECT track_id FROM track)')}")
    print(f"  total scrobbles: {_count(conn, 'SELECT COUNT(*) FROM scrobble')}")

    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fold accent/punctuation-variant duplicate track entities "
                    "(safe + real-split groups) onto their canonical entity"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
