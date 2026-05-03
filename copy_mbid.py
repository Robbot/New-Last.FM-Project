#!/usr/bin/env python3
import sqlite3
import time

print('Starting MBID copy from scrobbles to album_tracks...')

# Use a longer timeout and WAL mode for better concurrency
conn = sqlite3.connect('files/lastfmstats.sqlite', timeout=60, isolation_level='IMMEDIATE')
conn.execute('PRAGMA journal_mode=WAL')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print('Getting albums that need updating...')

# First, let's find albums that need updating (smaller batch)
cursor.execute('''
    SELECT DISTINCT at.album
    FROM album_tracks at
    WHERE at.album_mbid IS NULL OR at.album_mbid = ""
    LIMIT 100
''')

albums_to_update = [row[0] for row in cursor.fetchall()]
print(f'Processing batch of {len(albums_to_update)} albums...')

updated = 0
for i, album in enumerate(albums_to_update):
    try:
        # Get the MBID from scrobbles for this album
        cursor.execute('''
            SELECT album_mbid, COUNT(*) as count
            FROM scrobble
            WHERE album = ?
              AND album_mbid IS NOT NULL
              AND album_mbid != ""
            GROUP BY album_mbid
            ORDER BY count DESC
            LIMIT 1
        ''', [album])

        result = cursor.fetchone()
        if result and result[0]:
            mbid = result[0]
            # Update all album_tracks entries for this album
            cursor.execute('''
                UPDATE album_tracks
                SET album_mbid = ?
                WHERE album = ?
                  AND (album_mbid IS NULL OR album_mbid = "")
            ''', [mbid, album])

            count = cursor.rowcount
            updated += count

            if (i + 1) % 10 == 0:
                print(f'Processed {i+1}/{len(albums_to_update)} albums, updated {updated} entries...')

    except Exception as e:
        print(f'Error updating {album}: {e}')

conn.commit()
conn.close()

print(f'Updated {updated} album_tracks entries with MBID from scrobbles')
