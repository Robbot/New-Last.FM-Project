#!/usr/bin/env python3
"""
Clean false-positive compilation albums by fixing artist name variations.

This script identifies albums marked as "Various Artists" that are actually
single-artist albums with inconsistent artist names, and fixes them by:
1. Identifying the correct artist name for each album
2. Setting album_artist to the correct artist (removing "Various Artists")
3. Not changing the artist field to avoid UNIQUE constraint violations
"""

import sqlite3
from pathlib import Path
from collections import Counter, defaultdict
import re


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


# ---------- Artist name normalization ----------
def normalize_artist_name(name: str) -> str:
    """Normalize artist name for comparison."""
    if not name:
        return ""
    # Lowercase, remove accents, remove extra spaces
    name = name.lower().strip()
    # Remove common variations
    name = re.sub(r'\s+', ' ', name)
    # Remove diacritics
    name = re.sub(r'[áäâà]', 'a', name)
    name = re.sub(r'[éëèê]', 'e', name)
    name = re.sub(r'[íïìî]', 'i', name)
    name = re.sub(r'[óöôò]', 'o', name)
    name = re.sub(r'[úüûù]', 'u', name)
    name = re.sub(r'[ýÿ]', 'y', name)
    name = re.sub(r'[ñ]', 'n', name)
    name = re.sub(r'[ćčç]', 'c', name)
    name = re.sub(r'[śš]', 's', name)
    name = re.sub(r'[źž]', 'z', name)
    name = re.sub(r'[ł]', 'l', name)
    return name


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_albums_with_various_artists(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Get all albums marked as Various Artists with their artist list."""
    cur = conn.cursor()

    cur.execute("""
        SELECT album, artist
        FROM scrobble
        WHERE album_artist = 'Various Artists'
        ORDER BY album, artist
    """)

    albums = defaultdict(list)
    for row in cur.fetchall():
        albums[row["album"]].append(row["artist"])

    return dict(albums)


# Known artist name variations
# Format: "normalized_name" -> "correct_display_name"
KNOWN_VARIATIONS = {
    # 30 Seconds to Mars variations
    "30 seconds to mars": "30 Seconds to Mars",
    "thirty seconds to mars": "30 Seconds to Mars",

    # Happysad variations
    "happysad": "Happysad",

    # Korn variations
    "korn": "Korn",

    # Pudelsi variations
    "pudelsi": "Püdelsi",

    # Bryan Adams
    "brian adams": "Bryan Adams",

    # Everything But the Girl
    "everything but the girl": "Everything But the Girl",

    # Van Halen (Edward is Van Halen's first name, but artist is Van Halen)
    "edward van halen": "Van Halen",

    # Jim Morrison / The Doors
    "jim morrison": "The Doors",

    # Ania Dąbrowska
    "ania d?browska": "Ania",

    # Polish characters
    "d?em": "Dżem",

    # The Bands
    "the bloodhound gang": "Bloodhound Gang",
    "the editors": "Editors",
    "the flaming lips": "The Flaming Lips",
    "the slow show": "The Slow Show",
    "the connells": "The Connells",
    "the chemical brothers": "The Chemical Brothers",
    "the cure": "The Cure",
    "the jam": "The Jam",
    "the clash": "The Clash",
    "the cult": "The Cult",
    "the stranglers": "The Stranglers",
    "the police": "The Police",
    "the smiths": "The Smiths",
    "the doors": "The Doors",
    "the beatles": "The Beatles",
    "the sisters of mercy": "The Sisters of Mercy",
    "the hallucination": "The Hallucination",
    "the wolfgang press": "The Wolfgang Press",
    "the three degrees": "The Three Degrees",
    "the electric hellfire club": "The Electric Hellfire Club",
    "the bates": "The Bates",
    "the merry thoughts": "The Merry Thoughts",
    "the six parts seven": "The Six Parts Seven",
    "the sixx": "Sixx: A.M.",
    "the bjork": "Björk",
    "the sarah mclachlan": "Sarah McLachlan",
    "the aimee mann": "Aimee Mann",
    "the cat power": "Cat Power",
    "the nine inch nails": "Nine Inch Nails",
    "the rammstein": "Rammstein",
    "the smashing pumpkins": "The Smashing Pumpkins",
    "the jesus & mary chain": "Jesus & Mary Chain",
    "the machines of loving grace": "Machines of Loving Grace",
    "the bad religion": "Bad Religion",
    "the sonic youth": "Sonic Youth",
    "the mudhoney": "Mudhoney",
    "the soundgarden": "Soundgarden",
    "the rollins band": "Rollins Band",
    "the beastie boys": "Beastie Boys",
    "the arcade fire": "Arcade Fire",
    "the bright eyes": "Bright Eyes",
    "the shins": "The Shins",
    "the coldplay": "Coldplay",
    "the counting crows": "Counting Crows",
    "the placebo": "Placebo",
    "the tears for fears": "Tears for Fears",
    "the duran duran": "Duran Duran",
    "the moby": "Moby",
    "the clan of xymox": "Clan of Xymox",
    "the cocteau twins": "Cocteau Twins",
    "the dead can dance": "Dead Can Dance",
    "the this mortal coil": "This Mortal Coil",
    "the diamanda galas": "Diamanda Galás",
    "the david bowie": "David Bowie",
    "the heart": "Heart",
    "the boston": "Boston",
    "the cars": "The Cars",
    "the detective": "The Detective",
    "the drivin' n' cryin'": "Drivin' n' Cryin'",
    "the godfathers": "The Godfathers",
    "the jesus jones": "Jesus Jones",
    "the posies": "The Posies",
    "the rockingbirds": "The Rockingbirds",
    "the waterboys": "The Waterboys",
    "the mission": "The Mission",
    "the all about eve": "All About Eve",
    "the fields of the nephilim": "Fields of the Nephilim",
    "the and also the trees": "And Also the Trees",
    "the weather prophets": "The Weather Prophets",
    "the heart thieves": "The Heart Thieves",
    "the new model army": "New Model Army",
    "the lords of the new church": "The Lords of the New Church",
    "the psychedelic furs": "Psychedelic Furs",
    "the sound": "The Sound",
    "the chords": "The Chords",
    "the members": "The Members",

    # INXS
    "inxs": "INXS",

    # Polish characters and variations
    "meskie granie orkiestra": "Męskie Granie Orkiestra",
    "mieszk Granie Orkiestra": "Męskie Granie Orkiestra",
    "robert gwali?ski": "Robert Gawliński",
    "agnieszka chyli?ska": "Agnieszka Chylińska",
    "klaus mitffoch": "Klaus Mitfłoch",

    # USA for Africa
    "u.s.a. for africa": "USA for Africa",
    "usa for africa": "USA for Africa",

    # FOTONESS variations
    "fotoness": "FOTONESS",

    # Daron Malakian and Scars on Broadway -> Scars on Broadway
    "daron malakian and scars on broadway": "Scars on Broadway",

    # Męskie Granie contributors (all map to Męskie Granie Orkiestra)
    "mrozu & vito bambino": "Męskie Granie Orkiestra",
    "artur rojek": "Męskie Granie Orkiestra",
    "igo": "Męskie Granie Orkiestra",
    "lao che": "Męskie Granie Orkiestra",
    "nosowska": "Męskie Granie Orkiestra",
    "daria zawiatoW": "Męskie Granie Orkiestra",
    "daria zawiato?": "Męskie Granie Orkiestra",
    "krzysztof zalewski": "Męskie Granie Orkiestra",
    "coma": "Męskie Granie Orkiestra",
    "eabs": "Męskie Granie Orkiestra",
    "kortez": "Męskie Granie Orkiestra",
    "rysy": "Męskie Granie Orkiestra",

    # Various Polish artists
    "jerzy grundwald": "Męskie Granie Orkiestra",
    "tilt": "Tilt",
    "sztywny pal azji": "Sztywny Pal Azji",
    "lombard": "Lombard",
    "rezerwat": "Rezerwat",
    "madame": "Madame",
    "shakin' dudi": "Shakin' Dudi",

    # Miguel and the Living Dead variations
    "migue l and the living dead": "Miguel and the Living Dead",

    # 1000 Homo DJs
    "1,000 homo dj's": "1000 Homo DJs",

    # My Head
    "my.head": "My Head",

    # Alannah Myles variations
    "allanah myles": "Alannah Myles",

    # British Sea Power / Sea Power
    "sea power": "British Sea Power",

    # Agnieszka Chylińska variations
    "chylinska": "Agnieszka Chylińska",

    # Robert Gawliński variations
    "robert gwali?ski": "Robert Gawliński",

    # Other variations
    "micheal jackson & paul mccartney": "Paul McCartney",
    "paul mccartney & stevie wonder": "Paul McCartney",
    "dave matthews band": "Dave Matthews Band",
    "ozzy osbourne & therapy?": "Ozzy Osbourne & Therapy?",
    "edward van halen": "Van Halen",
    "suzanne vega & dna": "Suzanne Vega",
}


def identify_correct_artist(artists: list[str]) -> str | None:
    """
    Identify the correct artist name from a list of potentially varying names.
    Returns the correct name if they're all variations of the same artist,
    or None if they're truly different artists.
    """
    if len(artists) <= 1:
        return None  # Single artist - no variation

    # Normalize all artist names for comparison
    normalized_map = {}
    for artist in artists:
        normalized = normalize_artist_name(artist)
        if normalized not in normalized_map:
            normalized_map[normalized] = []
        normalized_map[normalized].append(artist)

    # If all normalized names are the same, they're variations
    if len(normalized_map) == 1:
        # All are variations - pick the one that looks "most correct"
        candidates = list(artists)
        # Prefer proper capitalization
        for candidate in candidates:
            if candidate and candidate[0].isupper() and any(c.islower() for c in candidate[1:]):
                return candidate
        # Fallback to first artist
        return artists[0]

    # Check known variations
    correct_artists = set()
    for artist in artists:
        normalized = normalize_artist_name(artist)
        if normalized in KNOWN_VARIATIONS:
            correct_artists.add(KNOWN_VARIATIONS[normalized])
        else:
            correct_artists.add(artist)

    # If all map to the same artist, they're variations
    if len(correct_artists) == 1:
        return list(correct_artists)[0]

    return None  # Truly different artists


def is_single_artist_album(album: str, artists: list[str], conn: sqlite3.Connection) -> bool:
    """
    Determine if an album is truly a single-artist album despite having multiple artist names.
    """
    # Check if all artists are variations of the same artist
    correct_artist = identify_correct_artist(artists)
    if correct_artist:
        return True

    # If we have 2-3 artists, check if one dominates (e.g., 95%+ of tracks)
    if len(artists) <= 3:
        cur = conn.cursor()
        cur.execute("""
            SELECT artist, COUNT(*) as count
            FROM scrobble
            WHERE album = ? AND album_artist = 'Various Artists'
            GROUP BY artist
            ORDER BY count DESC
        """, (album,))

        results = cur.fetchall()
        if results:
            total = sum(r["count"] for r in results)
            dominant = results[0]["count"]
            # If one artist has >90% of scrobbles, it's probably their album
            if dominant / total > 0.9:
                return True

    return False


def fix_single_artist_albums(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Fix single-artist albums that were incorrectly marked as Various Artists.
    Only updates album_artist field to avoid UNIQUE constraint violations.
    Returns dict with album -> number of scrobbles updated.
    """
    albums = get_albums_with_various_artists(conn)
    fixed_albums = {}
    cur = conn.cursor()

    print("Analyzing albums for false positives...")
    for album, artists in sorted(albums.items()):
        if is_single_artist_album(album, artists, conn):
            correct_artist = identify_correct_artist(artists)

            if correct_artist:
                # Update album_artist to the correct artist
                cur.execute("""
                    UPDATE scrobble
                    SET album_artist = ?
                    WHERE album = ? AND album_artist = 'Various Artists'
                """, (correct_artist, album))
                changes = cur.rowcount
                if changes > 0:
                    print(f"  '{album}': Set album_artist to '{correct_artist}' ({changes} scrobbles)")
                    fixed_albums[album] = fixed_albums.get(album, 0) + changes
            else:
                # No clear correct artist, use the most common one
                cur.execute("""
                    SELECT artist, COUNT(*) as count
                    FROM scrobble
                    WHERE album = ? AND album_artist = 'Various Artists'
                    GROUP BY artist
                    ORDER BY count DESC
                    LIMIT 1
                """, (album,))
                result = cur.fetchone()
                if result:
                    correct_artist = result["artist"]
                    cur.execute("""
                        UPDATE scrobble
                        SET album_artist = ?
                        WHERE album = ? AND album_artist = 'Various Artists'
                    """, (correct_artist, album))
                    changes = cur.rowcount
                    if changes > 0:
                        print(f"  '{album}': Set album_artist to '{correct_artist}' ({changes} scrobbles)")
                        fixed_albums[album] = fixed_albums.get(album, 0) + changes

    conn.commit()
    return fixed_albums


def main():
    print("Cleaning false-positive compilation albums...")
    print(f"Database: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"ERROR: Database file not found at {DB_PATH}")
        return

    conn = get_conn()

    # Backup the database before making changes
    backup_path = DB_PATH.with_suffix(".sqlite.backup")
    print(f"\nCreating backup at: {backup_path}")
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print("Backup created successfully.")

    try:
        fixed_albums = fix_single_artist_albums(conn)

        if not fixed_albums:
            print("\nNo false-positive albums found to fix.")
        else:
            total_scrobbles = sum(fixed_albums.values())
            print(f"\nDone. Fixed {len(fixed_albums)} album(s) with {total_scrobbles} scrobble(s).")
            print(f"Backup saved at: {backup_path}")

    except Exception as e:
        print(f"\nERROR during cleanup: {e}")
        import traceback
        traceback.print_exc()
        print("\nRolling back changes...")
        conn.rollback()
        print("Changes rolled back. You can restore from backup if needed.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
