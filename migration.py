import csv
import sqlite3
from pathlib import Path

CSV_FILE = "files/lastfmstats.csv"
DB_FILE  = "files/lastfmstats.sqlite"

conn = sqlite3.connect(DB_FILE)

# optional speed-ups (OK for one-off import on a local DB file)
conn.execute("PRAGMA journal_mode = WAL;")
conn.execute("PRAGMA synchronous = OFF;")

cur = conn.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS scrobble (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    artist   TEXT NOT NULL,
    album    TEXT NOT NULL,
    album_id TEXT,
    track    TEXT NOT NULL,
    date     INTEGER NOT NULL,
    UNIQUE (track, date)
);
""")

BATCH_SIZE = 1000
batch = []
insert_sql = """
INSERT OR IGNORE INTO scrobble
(artist, album, album_id, track, date)
VALUES (?, ?, ?, ?, ?)
"""

with open(CSV_FILE, encoding="utf-8") as f:
    reader = csv.reader(f, delimiter=';')
    next(reader, None)  # skip header

    for i, row in enumerate(reader, start=1):
        if len(row) < 5:
            continue

        artist   = row[0]
        album    = row[1]
        album_id = row[2] or None
        track    = row[3]
        date     = int(row[4])

        batch.append((artist, album, album_id, track, date))

        if len(batch) >= BATCH_SIZE:
            cur.executemany(insert_sql, batch)
            conn.commit()
            batch.clear()

            if i % 10000 == 0:
                print(f"Imported {i} rows...")

# final remaining rows
if batch:
    cur.executemany(insert_sql, batch)
    conn.commit()

conn.close()
print("Import finished.")