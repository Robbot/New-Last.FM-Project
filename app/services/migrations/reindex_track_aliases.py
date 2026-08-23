"""Reindex persisted track aliases after track-normalizer changes.

Run the entity-variant fold first when current-normalized keys point at more than
one entity. This migration is deliberately additive: legacy keys remain valid,
while every track also gains the key produced by the current normalizer.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.db.connections import _normalize_track_name_for_matching
from app.services.fix_track_entity_variant_dups import _run as fold_variant_duplicates


NORMALIZER_VERSION = 2


def reindex_track_aliases(conn: sqlite3.Connection, *, dry_run: bool = False) -> dict[str, int]:
    """Fold normalized duplicates, seed current alias keys, and store the version."""
    conn.row_factory = sqlite3.Row
    conn.execute("SAVEPOINT track_alias_reindex")
    try:
        # This handles existing splits such as Chop Suey! before keys are seeded.
        fold_variant_duplicates(conn, dry_run=False, manage_transaction=False)

        inserted = 0
        ambiguous = 0
        conn.execute(
            "CREATE TABLE IF NOT EXISTS track_alias_normalization_conflict ("
            "track_id INTEGER NOT NULL, artist_id INTEGER NOT NULL, norm_title TEXT NOT NULL, "
            "existing_track_id INTEGER NOT NULL, normalizer_version INTEGER NOT NULL, "
            "PRIMARY KEY(track_id, norm_title, normalizer_version))"
        )
        conn.execute(
            "DELETE FROM track_alias_normalization_conflict WHERE normalizer_version=?",
            (NORMALIZER_VERSION,),
        )
        for row in conn.execute("SELECT track_id, artist_id, title FROM track").fetchall():
            norm = _normalize_track_name_for_matching(row["title"])
            if not norm:
                continue
            owner = conn.execute(
                "SELECT track_id FROM track_alias WHERE artist_id=? AND norm_title=?",
                (row["artist_id"], norm),
            ).fetchone()
            if owner and owner["track_id"] != row["track_id"]:
                ambiguous += 1
                conn.execute(
                    "INSERT INTO track_alias_normalization_conflict "
                    "(track_id, artist_id, norm_title, existing_track_id, normalizer_version) "
                    "VALUES (?,?,?,?,?)",
                    (row["track_id"], row["artist_id"], norm, owner["track_id"],
                     NORMALIZER_VERSION),
                )
                continue
            inserted += conn.execute(
                "INSERT OR IGNORE INTO track_alias (artist_id, norm_title, track_id) VALUES (?,?,?)",
                (row["artist_id"], norm, row["track_id"]),
            ).rowcount

        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_metadata "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_metadata(key, value) VALUES('track_alias_normalizer_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(NORMALIZER_VERSION),),
        )
        result = {"aliases_inserted": inserted, "ambiguous": ambiguous}
        if dry_run:
            conn.execute("ROLLBACK TO track_alias_reindex")
        conn.execute("RELEASE track_alias_reindex")
        return result
    except Exception:
        conn.execute("ROLLBACK TO track_alias_reindex")
        conn.execute("RELEASE track_alias_reindex")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database", type=Path, default=Path("files/lastfmstats.sqlite"))
    args = parser.parse_args()
    with sqlite3.connect(args.database) as conn:
        result = reindex_track_aliases(conn, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
