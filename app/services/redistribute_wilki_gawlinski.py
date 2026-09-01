#!/usr/bin/env python3
"""Redistribute the Wilki/Robert Gawlinski greatest-hits scrobbles.

Routes every track from the legacy, unaccented combined-album tag to its
original official album. The two songs first released on the compilation are
routed to the canonical ``Największe przeboje`` album entity.

Usage:
    python -m app.services.redistribute_wilki_gawlinski --dry-run
    python -m app.services.redistribute_wilki_gawlinski
"""

import argparse
import sqlite3
from collections import Counter
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
SOURCE_ALBUM = "Wilki I Robert Gawlinski Najwieksze Przeboje"

TRACK_TO_ALBUM = {
    ("Robert Gawliński", "Beze Mnie O Mnie"): "Największe przeboje",
    ("Robert Gawliński", "Cherman"): "Gra",
    ("Robert Gawliński", "Czy Czujesz Czasem Co Czuję Ja"): "X",
    ("Robert Gawliński", "Dokąd Zmierzamy"): "Solo",
    ("Robert Gawliński", "Jasne Ulice"): "Solo",
    ("Robert Gawliński", "Mamy Tylko Chwile"): "Gra",
    ("Robert Gawliński", "Miasto we śnie"): "X",
    ("Robert Gawliński", "Nie Stalo Sie Nic"): "Kwiaty jak relikwie",
    ("Robert Gawliński", "O Milosci (Pamieci B. Lyszkiewicza)"): "Największe przeboje",
    ("Robert Gawliński", "O Sobie Samym"): "Solo",
    ("Robert Gawliński", "Sid and Nancy"): "Kwiaty jak relikwie",
    ("Robert Gawliński", "Trzy Noce Z Deszczem"): "Solo",
    ("Wilki", "A Moje Bostwa Placza"): "Acousticus Rockus",
    ("Wilki", "Aborygen"): "Wilki",
    ("Wilki", "Ali Lama Sabachtani"): "Wilki",
    ("Wilki", "Amiranda (Abbey Mix)"): "Wilki",
    ("Wilki", "Ballada Emanuel"): "Przedmieścia",
    ("Wilki", "Beniamin"): "Wilki",
    ("Wilki", "Cien W Dolinie Mgiel"): "Przedmieścia",
    ("Wilki", "Eroll"): "Wilki",
    ("Wilki", "Folkowy"): "Acousticus Rockus",
    ("Wilki", "Gloria"): "Wilki",
    ("Wilki", "Jeden raz odwiedzamy świat"): "Przedmieścia",
    ("Wilki", "Moja Baby"): "Przedmieścia",
    ("Wilki", "N'Avoie"): "Przedmieścia",
    ("Wilki", "Nie zabiję nocy"): "Przedmieścia",
    ("Wilki", "Rachela"): "Wilki",
    ("Wilki", "Sen O Warszawie"): "Acousticus Rockus",
    ("Wilki", "Son of the Blue Sky"): "Wilki",
    ("Wilki", "Śpij mój śnie"): "Acousticus Rockus",
}


def redistribute(dry_run: bool = True) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")

    rows = conn.execute(
        "SELECT id, artist, track FROM scrobble WHERE album = ? ORDER BY id",
        (SOURCE_ALBUM,),
    ).fetchall()
    unmapped = sorted({(r["artist"], r["track"]) for r in rows} - TRACK_TO_ALBUM.keys())
    if unmapped:
        conn.close()
        raise RuntimeError(f"Unmapped source tracks; refusing partial update: {unmapped}")

    targets = {}
    for artist, target_album in set((a, album) for (a, _), album in TRACK_TO_ALBUM.items()):
        target = conn.execute(
            """
            SELECT al.album_id,
                   COALESCE(NULLIF(at.album_mbid, ''), NULLIF(s.album_mbid, '')) AS mbid
            FROM album al
            JOIN artist ar ON ar.artist_id = al.artist_id
            LEFT JOIN album_tracks at
              ON at.album_id = al.album_id AND at.album_mbid IS NOT NULL AND at.album_mbid != ''
            LEFT JOIN scrobble s
              ON s.album_id = al.album_id AND s.album_mbid IS NOT NULL AND s.album_mbid != ''
            WHERE ar.name = ? AND al.title = ?
            LIMIT 1
            """,
            (artist, target_album),
        ).fetchone()
        if target is None:
            conn.close()
            raise RuntimeError(f"Missing canonical target album: {artist} / {target_album}")
        targets[(artist, target_album)] = (target["album_id"], target["mbid"])

    summary = Counter()
    if not dry_run:
        conn.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            target_album = TRACK_TO_ALBUM[(row["artist"], row["track"])]
            album_id, album_mbid = targets[(row["artist"], target_album)]
            summary[(row["artist"], target_album)] += 1
            if not dry_run:
                conn.execute(
                    """
                    UPDATE scrobble
                    SET album = ?, album_mbid = ?, album_id = ?, album_artist = ?, track_id = NULL
                    WHERE id = ?
                    """,
                    (target_album, album_mbid, album_id, row["artist"], row["id"]),
                )
        if not dry_run:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"dry_run": dry_run, "moved": len(rows), "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = redistribute(dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Scrobbles {'to move' if args.dry_run else 'moved'}: {result['moved']}")
    for (artist, album), count in sorted(result["summary"].items()):
        print(f"  {artist} / {album}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
