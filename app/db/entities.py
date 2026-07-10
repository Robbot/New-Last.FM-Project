"""
Canonical entity resolver (Phase 1 of the relational rework).

Maps free-text artist / album / track names to stable surrogate ids in the
`artist` / `album` / `track` tables, recording every variant spelling in the
`*_alias` tables so subsequent lookups are a fast indexed hit.

Identity policy (conservative — see memory: project-entity-resolver-mbid-policy):
  - Artist identity = exact alias name, then `_normalize_for_matching(name)`
    (lowercase + accent strip). Case/accent variants merge automatically
    (INXS/Inxs, José/Jose). MBID is stored as a *hint* and is **never** used
    to merge two differently-named artists, because shared MBIDs are
    ambiguous between variant spellings and collaboration mis-tags
    (David Bowie vs "David Bowie & Queen"). Substantive merges are deferred
    to the manual Phase 4 merge tool.
  - Album identity = (owning artist_id, `_normalize_for_matching(title)`).
    Various-Artists compilations resolve under a single VA sentinel artist.
  - Track identity = (artist_id, `_normalize_track_name_for_matching(title)`).

`Resolver` holds a per-instance dict cache, so batch writers (sync, backfill)
should instantiate one and reuse it. The module-level free functions create a
throwaway `Resolver` per call for one-off request-time writers.

NOTE: `sqlite3.Connection` disallows attribute attachment and weakref, so a
Resolver cannot be cached *on* a connection — callers that want caching hold
the instance themselves.
"""

import logging
import sqlite3

from .connections import _normalize_for_matching, _normalize_track_name_for_matching

logger = logging.getLogger(__name__)

_VA_SENTINEL_NAME = "Various Artists"


class Resolver:
    """Resolve artist/album/track names to canonical ids on a single connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._artist_cache: dict[tuple[str, str], int] = {}   # (name, mbid|"") -> id
        self._album_cache: dict[tuple[int, str], int] = {}    # (artist_id, norm_title) -> id
        self._track_cache: dict[tuple[int, str], int] = {}    # (artist_id, norm_title) -> id
        self._va_sentinel_id: int | None = None

    # ------------------------------------------------------------------ artist
    def resolve_artist_id(self, name: str, mbid: str | None = None) -> int:
        """Return the canonical artist_id for `name`, creating it if new.

        MBID is stored as a hint on the artist row but never merges names.
        """
        if not name or not name.strip():
            raise ValueError("artist name is required")
        name = name.strip()
        mbid = (mbid or "").strip()

        cache_key = (name, mbid)
        cached = self._artist_cache.get(cache_key)
        if cached is not None:
            return cached

        artist_id = self._lookup_artist(name)
        if artist_id is None:
            artist_id = self._create_artist(name, mbid)

        self._artist_cache[cache_key] = artist_id
        # Name is the true identity; cache the name-only key too so a later
        # resolve of the same name without an mbid is a dict hit.
        self._artist_cache.setdefault((name, ""), artist_id)
        return artist_id

    def _lookup_artist(self, name: str) -> int | None:
        # 1. Exact alias spelling.
        row = self.conn.execute(
            "SELECT artist_id FROM artist_alias WHERE alias_name = ?", (name,)
        ).fetchone()
        if row:
            return row[0]

        # 2. Normalized alias (case/accent merge only — never MBID).
        norm = _normalize_for_matching(name)
        if norm:
            # DISTINCT artist_id: one artist can legitimately own several alias
            # spellings that share a norm (e.g. "Melissa Auf Der Maur" and
            # "Melissa auf der Maur"); those must not read as a collision.
            rows = self.conn.execute(
                "SELECT DISTINCT artist_id FROM artist_alias WHERE norm_name = ?", (norm,)
            ).fetchall()
            if len(rows) == 1:
                artist_id = rows[0][0]
                # Self-heal: remember this exact spelling for faster future hits.
                self.conn.execute(
                    "INSERT OR IGNORE INTO artist_alias (alias_name, norm_name, artist_id) "
                    "VALUES (?, ?, ?)",
                    (name, norm, artist_id),
                )
                return artist_id
            if len(rows) > 1:
                # Two distinct artists share a normalized name — ambiguous, do
                # not pick one. Create a new artist for this spelling instead.
                logger.warning(
                    "Normalized artist name collision for %r (%d distinct artists); "
                    "creating a separate artist", name, len(rows),
                )
        return None

    def _create_artist(self, name: str, mbid: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO artist (name, mbid) VALUES (?, ?)",
            (name, mbid or None),
        )
        artist_id = cur.lastrowid
        self.conn.execute(
            "INSERT INTO artist_alias (alias_name, norm_name, artist_id) "
            "VALUES (?, ?, ?)",
            (name, _normalize_for_matching(name), artist_id),
        )
        return artist_id

    @property
    def va_sentinel_id(self) -> int:
        """The single 'Various Artists' sentinel artist used to key VA albums."""
        if self._va_sentinel_id is None:
            self._va_sentinel_id = self.resolve_artist_id(_VA_SENTINEL_NAME)
        return self._va_sentinel_id

    # ------------------------------------------------------------------- album
    def resolve_album_id(
        self,
        artist_id: int,
        album_title: str,
        album_mbid: str | None = None,
        album_artist_text: str | None = None,
    ) -> int:
        """Return the canonical album_id for `album_title` under `artist_id`.

        Various-Artists compilations (album_artist_text ~= "Various Artists")
        resolve under the VA sentinel so all contributing artists share one album.
        """
        title = (album_title or "").strip()
        owner = self.va_sentinel_id if self._is_various_artists(album_artist_text) else artist_id
        norm = _normalize_for_matching(title)

        cache_key = (owner, norm)
        cached = self._album_cache.get(cache_key)
        if cached is not None:
            return cached

        row = self.conn.execute(
            "SELECT album_id FROM album_alias WHERE artist_id = ? AND norm_title = ?",
            (owner, norm),
        ).fetchone()
        if row:
            album_id = row[0]
        else:
            mbid = (album_mbid or "").strip()
            cur = self.conn.execute(
                "INSERT INTO album (title, mbid, artist_id) VALUES (?, ?, ?)",
                (title, mbid or None, owner),
            )
            album_id = cur.lastrowid
            self.conn.execute(
                "INSERT INTO album_alias (artist_id, norm_title, album_id) "
                "VALUES (?, ?, ?)",
                (owner, norm, album_id),
            )
        self._album_cache[cache_key] = album_id
        return album_id

    # ------------------------------------------------------------------- track
    def resolve_track_id(
        self,
        artist_id: int,
        track_title: str,
        track_mbid: str | None = None,
    ) -> int:
        """Return the canonical track_id for `track_title` under `artist_id`.

        Name-first (track normalizer strips remastered/version suffixes); MBID
        is stored as a hint only, never used to merge (consistent conservative
        policy).
        """
        title = (track_title or "").strip()
        if not title:
            raise ValueError("track title is required")
        norm = _normalize_track_name_for_matching(title)

        cache_key = (artist_id, norm)
        cached = self._track_cache.get(cache_key)
        if cached is not None:
            return cached

        row = self.conn.execute(
            "SELECT track_id FROM track_alias WHERE artist_id = ? AND norm_title = ?",
            (artist_id, norm),
        ).fetchone()
        if row:
            track_id = row[0]
        else:
            mbid = (track_mbid or "").strip()
            cur = self.conn.execute(
                "INSERT INTO track (title, mbid, artist_id, album_id) "
                "VALUES (?, ?, ?, NULL)",
                (title, mbid or None, artist_id),
            )
            track_id = cur.lastrowid
            self.conn.execute(
                "INSERT INTO track_alias (artist_id, norm_title, track_id) "
                "VALUES (?, ?, ?)",
                (artist_id, norm, track_id),
            )
        self._track_cache[cache_key] = track_id
        return track_id

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _is_various_artists(album_artist_text: str | None) -> bool:
        if not album_artist_text:
            return False
        return _normalize_for_matching(album_artist_text) == _normalize_for_matching(_VA_SENTINEL_NAME)


# --- Free-function wrappers for one-off request-time writers ---------------
# These create a throwaway Resolver per call (no caching across calls). Batch
# writers should use Resolver(conn) directly and reuse the instance.

def get_resolver(conn: sqlite3.Connection) -> Resolver:
    """Return a Resolver bound to `conn` (fresh instance each call)."""
    return Resolver(conn)


def resolve_artist_id(conn: sqlite3.Connection, name: str, mbid: str | None = None) -> int:
    return Resolver(conn).resolve_artist_id(name, mbid)


def resolve_album_id(
    conn: sqlite3.Connection,
    artist_id: int,
    album_title: str,
    album_mbid: str | None = None,
    album_artist_text: str | None = None,
) -> int:
    return Resolver(conn).resolve_album_id(artist_id, album_title, album_mbid, album_artist_text)


def resolve_track_id(
    conn: sqlite3.Connection,
    artist_id: int,
    track_title: str,
    track_mbid: str | None = None,
) -> int:
    return Resolver(conn).resolve_track_id(artist_id, track_title, track_mbid)


# --- Read-only lookups (no entity creation) -------------------------------
# For read paths that need to find an existing canonical id from a name without
# creating entities. Returns None when the name is not in the alias tables.

def lookup_track_id(conn: sqlite3.Connection, artist_name: str, track_name: str) -> int | None:
    """Find the canonical track_id for (artist_name, track_name) using the alias
    tables, without creating anything. Handles variant spellings (case/accent/
    suffix) the same way writes do. Returns None if not found.
    """
    if not artist_name or not track_name:
        return None

    artist_id = _lookup_artist_id(conn, artist_name)
    if artist_id is None:
        return None

    norm_track = _normalize_track_name_for_matching(track_name)
    t = conn.execute(
        "SELECT track_id FROM track_alias WHERE artist_id = ? AND norm_title = ?",
        (artist_id, norm_track),
    ).fetchone()
    return t[0] if t else None


def _lookup_artist_id(conn: sqlite3.Connection, artist_name: str) -> int | None:
    """Read-only: find the canonical artist_id for a name from the alias tables.
    Exact alias spelling first, then a unique normalized match. Returns None if
    not found or ambiguous (multiple distinct normalized matches).
    """
    if not artist_name:
        return None
    row = conn.execute(
        "SELECT artist_id FROM artist_alias WHERE alias_name = ?", (artist_name,)
    ).fetchone()
    if row:
        return row[0]
    norm = _normalize_for_matching(artist_name)
    if not norm:
        return None
    rows = conn.execute(
        "SELECT DISTINCT artist_id FROM artist_alias WHERE norm_name = ?", (norm,)
    ).fetchall()
    if len(rows) == 1:
        return rows[0][0]
    return None


def lookup_album_id(
    conn: sqlite3.Connection,
    album_artist_name: str,
    album_name: str,
) -> int | None:
    """Read-only: find the canonical album_id for (album_artist_name, album_name)
    via the alias tables, without creating anything. For Various Artists the
    owner resolves to the VA sentinel. Returns None if not found.

    NOTE: VA compilation *album_tracks* rows are keyed by per-track artist, so
    this returns the sentinel album which those rows do NOT carry — callers that
    select album_tracks for VA must select by album name instead of album_id.
    """
    if not album_artist_name or not album_name:
        return None
    owner = _lookup_artist_id(conn, album_artist_name)
    if owner is None:
        return None
    norm = _normalize_for_matching(album_name)
    row = conn.execute(
        "SELECT album_id FROM album_alias WHERE artist_id = ? AND norm_title = ?",
        (owner, norm),
    ).fetchone()
    return row[0] if row else None
