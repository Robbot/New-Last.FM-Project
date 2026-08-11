#!/usr/bin/env python3
"""
Full sweep: fix Windows-1250 mojibake tracks (Polish diacritics -> '?') for the
remaining 11 Polish artists, after the 3-artist pilot
(fix_polish_mojibake_pilot.py: Budka Suflera, Hey, Siekiera). Re-runnable.

Covers: Armia, Azyl P., Coma, Cool Kids of Death, Kasa, Klaus Mitffoch,
Kukiz & Hak, Kult, Luxtorpeda, Róże Europy, Sistars.

Two operation kinds:
  * FOLD (dst_tid set): mojibake track_id folds onto an existing canonical
    (non-mojibake) entity — move scrobbles (text + track_id), repoint the
    mojibake alias to the canonical entity, delete the orphan mojibake entity.
    Verified: canonical entity present with that exact title, zero album_tracks
    refs on the src, zero timestamp collisions.
  * RENAME (dst_tid None): no canonical entity exists, so fix the mojibake in
    place — rename the entity title + the scrobble text (track_id unchanged).
    Used where there's no clean twin, OR where the only "canonical" differs in a
    way we want to preserve (Live Mix suffix, feat. artists, a separately
    misspelled Bonus-Track entity).

As with the pilot, dst track_ids are hardcoded rather than Resolver-resolved:
remote commit 0271a87 made the track normalizer strip accents while existing
aliases keep them, so resolve_track_id() cannot find accented canonical entities
and would create duplicates. (That normalization bug is a separate fix.)

FLAG entries (do more than swap '?' for a diacritic) — review before applying:
  * Azyl P. "Ma?a Maggie"      -> "Mała Maggie (Bonus Track)"   (folds onto tid 8443; adds suffix)
  * Azyl P. "Kara ?mierci"     -> "Kara śmierci (Bonus Track)"  (folds onto tid 35446; adds suffix)
  * CKD   "Butelki Z Benzyn? I Kamienie (Live Mix)" -> keeps "(Live Mix)" (canonical 1020 is the studio cut)
  * Sistars "Freestyle/City of love feat. APEX, ?ukasz Paprocki" -> keeps feat. info (canonicals omit it)
  * Azyl P. "Nic wi?cej mi nie trzeba" -> rename only; leaves the separately-misspelled
    "Nic Wiecej Mi Nie Trzeba (Bonus Track)" (tid 35447) untouched

Left untouched (legitimate '?' titles, diacritics already correct, no clean twin):
Kult "Dlaczego Tak Tu Jest?", Luxtorpeda "Gdzie ty jesteś?", "Jestem zwycięzcą ?".

Usage:
    python -m app.services.fix_polish_mojibake_full --dry-run
    python -m app.services.fix_polish_mojibake_full            # apply
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

# (artist, src_mojibake_track_id, dst_canonical_track_id_or_None, corrected_title)
PLAN = [
    # ---------------- Armia ----------------
    ("Armia", 25986, 873, "Strzały znikąd"),
    ("Armia", 25987, 871, "Zła krew"),
    ("Armia", 25988, 872, "Sygnały"),
    # ---------------- Azyl P. ----------------
    ("Azyl P.", 29519, 35434, "już lecą"),
    ("Azyl P.", 29522, 35438, "nasz jedyny świat"),
    ("Azyl P.", 29524, 35436, "już nie mogę"),
    ("Azyl P.", 29411, 8443, "Mała Maggie (Bonus Track)"),     # FLAG: folds, adds suffix
    ("Azyl P.", 29523, 35446, "Kara śmierci (Bonus Track)"),   # FLAG: folds, adds suffix
    ("Azyl P.", 29525, None, "Nic więcej mi nie trzeba"),      # FLAG: rename; leaves 35447 separate
    # ---------------- Coma ----------------
    ("Coma", 29255, 7933, "Woda leży pod powierzchnią"),       # fixes ?->ż AND ending a->ą
    # ---------------- Cool Kids of Death ----------------
    ("Cool Kids of Death", 25386, 120, "Ciągle jestem sam"),
    ("Cool Kids of Death", 25387, 6624, "Nagle zapomnieć wszystko"),
    ("Cool Kids of Death", 25388, 6628, "Leżeć"),
    ("Cool Kids of Death", 25385, None, "Zapowiedź"),          # rename
    ("Cool Kids of Death", 25389, None, "Butelki z benzyną i kamienie (Live Mix)"),  # FLAG: keep Live Mix
    ("Cool Kids of Death", 25390, None, "Zakończenie"),        # rename
    # ---------------- Kasa ----------------
    ("Kasa", 28529, None, "Wszystko spełni się"),              # rename
    # ---------------- Klaus Mitffoch ----------------
    ("Klaus Mitffoch", 29223, 9253, "Wiązanka pieśni bojowych"),
    ("Klaus Mitffoch", 29368, 4632, "strzeż się tych miejsc"),
    ("Klaus Mitffoch", 29387, 7053, "Jezu jak się cieszę"),
    # ---------------- Kukiz & Hak ----------------
    ("Kukiz & Hak", 29171, 3816, "Ideały"),
    ("Kukiz & Hak", 29173, 3824, "Mała Dziewczynka"),
    ("Kukiz & Hak", 29168, 3819, "Ołowiane Głowy"),            # fixes ?->ł AND Glowy->Głowy
    ("Kukiz & Hak", 29169, 3820, "Słownik Wyrazów Obcych"),    # fixes ?->ł AND Wyrazow->Wyrazów
    # ---------------- Kult ----------------
    ("Kult", 27396, 16466, "Pasażer"),
    ("Kult", 27397, 153, "Piosenka młodych wioślarzy"),
    ("Kult", 29388, 8361, "Dziewczyna o perłowych włosach"),
    # ---------------- Luxtorpeda ----------------
    ("Luxtorpeda", 29238, 7004, "Za wolność"),
    ("Luxtorpeda", 29459, 6999, "Jestem głupcem"),
    ("Luxtorpeda", 29460, 7002, "W ciemności"),
    ("Luxtorpeda", 29461, 7003, "3000 świń"),
    # ---------------- Róże Europy ----------------
    ("Róże Europy", 27603, 45254, "Za coca-colę i miłość"),
    ("Róże Europy", 26628, 844, "Stańcie przed lustrami"),
    # ---------------- Sistars ----------------
    ("Sistars", 28002, 45920, "Było co było"),
    ("Sistars", 27725, None, "Freestyle Conversation feat. APEX, Łukasz Paprocki"),  # FLAG: keep feat
    ("Sistars", 28006, None, "City of love feat. APEX, Łukasz Paprocki"),            # FLAG: keep feat
]


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


def run(dry_run: bool) -> int:
    conn = get_db_connection()
    try:
        return _run(conn, dry_run)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, dry_run: bool) -> int:
    print("=" * 80)
    print(f"Polish mojibake track fix — full sweep (11 artists)  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 80)
    print(f"{'artist':<20} {'op':>5} {'src':>6} {'dst':>6} {'plays':>5}  "
          f"{'src title':<32} -> {'corrected'}")
    print("-" * 130)

    total_moved = 0
    n_fold = n_rename = 0

    for artist, src_tid, dst_tid, corrected in PLAN:
        src_row = conn.execute(
            "SELECT title FROM track WHERE track_id=?", (src_tid,)
        ).fetchone()
        if not src_row:
            print(f"{artist:<20} {'--':>5} {src_tid:>6} {'--':>6}   --    (src gone — already done)")
            continue
        src_title = src_row["title"]
        plays = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (src_tid,))

        if dst_tid is None:
            # ---- pure rename: keep track_id, fix entity title + scrobble text ----
            if src_title == corrected:
                print(f"{artist:<20} {'renm':>5} {src_tid:>6} {'--':>6} {plays:>5}  "
                      f"{src_title!r:<32} -> (already renamed)")
                continue
            # verify no existing entity already holds the corrected title (would be odd)
            existing = conn.execute(
                "SELECT track_id FROM track WHERE artist_id=(SELECT artist_id FROM track WHERE track_id=?) "
                "AND title=?", (src_tid, corrected)).fetchone()
            warn = f"  !! target title already on tid {existing['track_id']}" if existing else ""
            print(f"{artist:<20} {'renm':>5} {src_tid:>6} {'--':>6} {plays:>5}  "
                  f"{src_title!r:<32} -> {corrected!r}{warn}")
            conn.execute("UPDATE scrobble SET track=? WHERE track_id=?", (corrected, src_tid))
            conn.execute("UPDATE track SET title=? WHERE track_id=?", (corrected, src_tid))
            total_moved += plays
            n_rename += 1
        else:
            # ---- fold onto existing canonical dst entity ----
            dst_row = conn.execute("SELECT title FROM track WHERE track_id=?", (dst_tid,)).fetchone()
            if not dst_row:
                print(f"{artist:<20} {'fold':>5} {src_tid:>6} {dst_tid:>6}   --    !! dst {dst_tid} MISSING — skip")
                continue
            if dst_row["title"] != corrected:
                print(f"{artist:<20} {'fold':>5} {src_tid:>6} {dst_tid:>6} {plays:>5}  "
                      f"{src_title!r:<32} -> !! dst title {dst_row['title']!r} != {corrected!r} — skip")
                continue
            print(f"{artist:<20} {'fold':>5} {src_tid:>6} {dst_tid:>6} {plays:>5}  "
                  f"{src_title!r:<32} -> {corrected!r}")
            conn.execute("UPDATE scrobble SET track=?, track_id=? WHERE track_id=?",
                         (corrected, dst_tid, src_tid))
            conn.execute("UPDATE track_alias SET track_id=? WHERE track_id=?", (dst_tid, src_tid))
            remaining = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (src_tid,))
                         + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (src_tid,))
                         + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (src_tid,)))
            if remaining == 0:
                conn.execute("DELETE FROM track WHERE track_id=?", (src_tid,))
            else:
                print(f"   !! kept src entity {src_tid}: still {remaining} reference(s)")
            total_moved += plays
            n_fold += 1

    print("-" * 130)
    print(f"total scrobbles moved/renamed: {total_moved}  ({n_fold} folds, {n_rename} renames)")

    # post-state: mid-word mojibake remaining across ALL 14 artists
    print("\n--- post-state: remaining mid-word '?' mojibake per artist (all 14) ---")
    import re
    midq = re.compile(r"[A-Za-z]\?[A-Za-z]")
    all14 = ["Armia", "Azyl P.", "Budka Suflera", "Coma", "Cool Kids of Death", "Hey",
             "Kasa", "Klaus Mitffoch", "Kukiz & Hak", "Kult", "Luxtorpeda",
             "Róże Europy", "Siekiera", "Sistars"]
    for A in all14:
        rows = conn.execute(
            "SELECT DISTINCT track FROM scrobble WHERE artist=? AND track LIKE '%?%'", (A,)).fetchall()
        mid = [r["track"] for r in rows if midq.search(r["track"])]
        print(f"  {A}: {len(mid)} remain" + (f"  {mid}" if mid else ""))

    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Full sweep: fix Polish mojibake tracks for 11 remaining artists (fold + rename)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
