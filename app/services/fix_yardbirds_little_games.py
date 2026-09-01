#!/usr/bin/env python3
"""Correct The Yardbirds' Little Games to MusicBrainz release e620d72e...."""

import argparse
import sqlite3
from pathlib import Path

from app.db.connections import _normalize_track_name_for_matching


DB = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
ARTIST = "The Yardbirds"
ALBUM = "Little Games"
RELEASE_MBID = "e620d72e-1a84-463d-8760-c1a869c4cff2"

# (release title, recording MBID, existing canonical title where it differs)
TRACKS = [
    ("Little Games", "8c9e92b8-8abf-412b-8142-3a2290ae09d2", None),
    ("Smile on Me (2002 stereo mix)", "436d265b-e49e-4bb8-8423-ecb29d5c8c49", "Smile on Me"),
    ("White Summer", "1fcb16c5-40bb-4c74-8de0-bdd6419a8f30", None),
    ("Tinker, Tailor, Soldier, Sailor (2002 stereo mix)", "35064a96-cc65-4b8e-bc50-3894a09e7534", "Tinker Tailor Soldier Sailor"),
    ("Glimpses", "46aa921b-144a-4b57-97da-ff2abf717868", "Glimpes"),
    ("Drinking Muddy Water", "afc1b215-52b7-4d75-940a-cdc6692bad19", None),
    ("No Excess Baggage", "f3633c5c-c4e2-452a-a7e7-cd04df2f9dc8", None),
    ("Stealing Stealing", "1e8652a7-bb22-47e2-a336-3307f2ae1e22", None),
    ("Only the Black Rose", "1a67d6b6-b372-4b42-9149-0d2794361d61", None),
    ("Little Soldier Boy", "0b50331f-7b53-4876-a3a9-d2089520a52e", None),
    ("Puzzles (1991 US stereo mix)", "6b481864-cd9b-4a4b-826b-7188de45fc4d", "Puzzles"),
    ("I Remember the Night (1991 US stereo mix)", "0ac53b77-b755-4509-8c0e-64cff97b36eb", "I Remember the Night"),
    ("Ha Ha Said the Clown", "be721c2c-1d0d-4389-b437-d90d574b8234", None),
    ("Ten Little Indians (1991 US stereo mix)", "5bd24954-34b6-460f-bfbe-ca47ecd56c93", "Ten Little Indians"),
    ("Goodnight Sweet Josephine (version 1 unphased version)", "05b6b7cd-a3db-41a9-ac06-8a65cd282903", "Goodnight Sweet Josephine UK"),
    ("Think About It", "9347f16c-87a2-4efb-8a28-bcb01d2f6163", None),
    ("Goodnight Sweet Josephine (phased US single version)", "3f249d33-3d53-42cd-93e7-4567ee9b46f9", "Goodnight Sweet Josephine USA"),
    ("Most Likely You'll Go Your Own Way (and I'll Go Mine) (BBC session)", "f569d682-35d3-4d2f-ac00-15f94df4603c", None),
    ("Little Games (BBC session)", "9433e074-5225-4126-aa4a-5f51e275b75f", None),
    ("Drinking Muddy Water (BBC session)", "f1f0386d-8e83-4b6d-a2fc-e9bedd1351a2", None),
    ("Think About It (BBC session)", "4e9ae692-2781-431b-9966-3fc72da8a841", None),
    ("Goodnight Sweet Josephine (BBC session)", "6ff81b69-1a4a-4271-95b3-6c1867a7e9e7", None),
    ("My Baby (BBC session)", "73cad4d7-f71f-4661-a14d-473897a7b129", None),
    ("White Summer (BBC session)", "68dd11d8-1790-4bde-8af6-e58be1f8f003", None),
    ("Dazed and Confused (BBC session)", "d0dc6eb9-e9df-44d4-b6b0-55d4f9a7e4d2", None),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        artist = conn.execute("SELECT artist_id FROM artist WHERE name=?", (ARTIST,)).fetchone()
        if not artist:
            raise RuntimeError(f"Artist not found: {ARTIST}")
        artist_id = artist["artist_id"]
        album = conn.execute(
            "SELECT album_id FROM album WHERE artist_id=? AND title=?", (artist_id, ALBUM)
        ).fetchone()
        if not album:
            raise RuntimeError(f"Album not found: {ARTIST} - {ALBUM}")
        album_id = album["album_id"]

        rows = []
        created = 0
        for position, (release_title, recording_mbid, canonical_title) in enumerate(TRACKS, 1):
            lookup_title = canonical_title or release_title
            track = conn.execute(
                "SELECT track_id FROM track WHERE artist_id=? AND title=?", (artist_id, lookup_title)
            ).fetchone()
            if track:
                track_id = track["track_id"]
                conn.execute("UPDATE track SET mbid=? WHERE track_id=?", (recording_mbid, track_id))
            else:
                cur = conn.execute(
                    "INSERT INTO track (title, mbid, artist_id, album_id) VALUES (?,?,?,?)",
                    (release_title, recording_mbid, artist_id, album_id),
                )
                track_id = cur.lastrowid
                norm = _normalize_track_name_for_matching(release_title)
                conn.execute(
                    "INSERT INTO track_alias (artist_id,norm_title,track_id) VALUES (?,?,?)",
                    (artist_id, norm, track_id),
                )
                created += 1
            rows.append((ARTIST, ALBUM, release_title, position, recording_mbid,
                         RELEASE_MBID, artist_id, album_id, track_id))

        removed = conn.execute("DELETE FROM album_tracks WHERE album_id=?", (album_id,)).rowcount
        conn.executemany(
            """INSERT INTO album_tracks
               (artist,album,track,track_number,track_mbid,album_mbid,
                artist_id,album_id,track_id) VALUES (?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.execute("UPDATE album SET mbid=? WHERE album_id=?", (RELEASE_MBID, album_id))
        scrobbles = conn.execute(
            "UPDATE scrobble SET album_mbid=? WHERE album_id=?", (RELEASE_MBID, album_id)
        ).rowcount
        art = conn.execute(
            "UPDATE album_art SET album_mbid=? WHERE album_id=?", (RELEASE_MBID, album_id)
        ).rowcount

        print(f"album_id={album_id}; replaced {removed} rows with {len(rows)}; "
              f"created {created} track entities; updated {scrobbles} scrobbles and {art} art row")
        if args.dry_run:
            conn.rollback()
            print("dry run: rolled back")
        else:
            conn.commit()
            print("committed")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
