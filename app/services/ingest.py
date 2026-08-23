"""Shared single-scrobble ingest: clean + validate + resolve + INSERT.

One pipeline used by three callers so scrobbles are stored identically regardless
of origin:

  - the Last.fm pull sync          (``sync_lastfm.sync_lastfm``)
  - the periodic gap-fill          (``periodic_full_sync``)
  - the direct-ingest API endpoint (``app.api`` — Last.fm-compatible push)

Keeping one path means pull and push can never drift (the root cause of the
duplicate-entity class of bugs), and new scrobbles are normalized once at write
time.

Behaviorally identical to the inline body of ``sync_lastfm.sync_lastfm`` lines
~1019-1145 plus the INSERT at ~1188-1202. The pull sync passes the defaults
(``run_album_autocorrect=True`` — it is already on the network); the endpoint and
the gap-fill pass ``run_album_autocorrect=False`` because album autocorrect makes
Last.fm/MusicBrainz API calls (``validate_albums.find_correct_album_from_lastfm``)
that would be too slow / re-introduce a Last.fm dependency on the push path.

The caller owns the transaction (``commit=False`` by default) and the ``Resolver``
(one per connection/request, reused — never per-scrobble; the module-level free
functions in ``app.db.entities`` spin up throwaways and discard their cache).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from app.db.entities import Resolver
from app.db.notifications import create_notification
from app.services.sync_lastfm import (
    _is_album_compilation_with_fallback,
    _is_single_artist_album,
    apply_scrobble_metadata_mapping,
    clean_album_name,
    clean_artist_name,
    clean_title,
    validate_scrobble_track,
)

logger = logging.getLogger(__name__)


class AlbumlessScrobbleError(ValueError):
    """Raised when a scrobble has no album and must not be persisted."""

    def __init__(self, raw: "RawScrobble") -> None:
        self.raw = raw
        super().__init__(
            f"Albumless scrobble: {raw.artist_name} - {raw.track_name} ({raw.uts})"
        )


@dataclass
class RawScrobble:
    """A not-yet-cleaned scrobble from any source."""

    artist_name: str
    track_name: str
    uts: int
    artist_mbid: str | None = None
    album_name: str | None = None
    album_mbid: str | None = None
    track_mbid: str | None = None
    source: str = "lastfm"
    album_artist_override: str | None = None  # if set, skip compilation detection
    images: dict | None = None  # pull path only: {"small":..,"medium":..,"large":..,"xlarge":..}


@dataclass
class IngestResult:
    """Outcome of ingesting one scrobble."""

    inserted: bool  # True only when a new listen is created
    reconciled: bool  # existing listen had metadata updated
    artist_id: int
    album_id: int | None
    track_id: int
    album_artist: str  # value actually stored
    album_art_record: dict | None = None  # for the pull path's album_art batch; else None
    # Cleaned (canonical) field values, for forwarders / API responses:
    artist_name: str = ""
    album_name: str | None = None
    track_name: str = ""


def _norm_optional(value: str | None) -> str | None:
    """Empty-string MBIDs (common from Last.fm) become NULL."""
    if not value:
        return None
    value = value.strip()
    return value or None


def ingest_scrobble(
    conn: sqlite3.Connection,
    resolver: Resolver,
    raw: RawScrobble,
    *,
    run_album_autocorrect: bool = True,
    run_track_validation: bool = True,
    commit: bool = False,
) -> IngestResult:
    """Transform + validate + resolve + INSERT one scrobble.

    Returns an :class:`IngestResult`; ``inserted`` is True iff a new listen was
    written. A matching ``(uts, artist, track)`` updates correctable metadata
    and returns ``reconciled=True`` when anything changed. Does not commit
    unless ``commit=True`` — callers batch many scrobbles in one transaction.
    """
    # --- timestamp sanity (Last.fm gives seconds; guard against ms) ----------
    uts = int(raw.uts)
    if uts > 2_000_000_000:
        uts //= 1000

    # Exact source corrections can optionally override the artist and album as
    # well as the title (for example, a cover mistagged under its performer).
    (
        mapped_artist, mapped_album, mapped_track,
        mapped_artist_mbid, mapped_album_mbid, mapped_track_mbid,
    ) = apply_scrobble_metadata_mapping(
        raw.artist_name, raw.album_name, raw.track_name,
        raw.artist_mbid, raw.album_mbid, raw.track_mbid,
    )

    # --- artist --------------------------------------------------------------
    artist_name = clean_artist_name(mapped_artist)
    artist_mbid = _norm_optional(mapped_artist_mbid)

    # --- album: clean_title (separators/remaster) then name mappings ---------
    album_name = clean_title(mapped_album) if mapped_album else mapped_album
    album_name = clean_album_name(artist_name, album_name) if album_name else album_name
    album_mbid = _norm_optional(mapped_album_mbid)
    if not album_name:
        raise AlbumlessScrobbleError(raw)

    # --- track: clean_title WITH artist+album context (applies spotify maps) -
    track_name = clean_title(mapped_track, artist_name, album_name)
    track_mbid = _norm_optional(mapped_track_mbid)

    # --- album autocorrect (NETWORK — pull sync only) ------------------------
    # Suspicious album names (often a track name mistagged as the album) are
    # corrected via a Last.fm + MusicBrainz lookup. Disabled on the push path.
    # A source-supplied album MBID is stronger evidence than the heuristic.
    # In particular, legitimate title tracks often have album == track; using
    # historical majority in that case can perpetuate a transient wrong album.
    if run_album_autocorrect and album_name and not album_mbid:
        from app.services.validate_albums import (
            is_album_name_suspicious,
            log_data_quality_issue,
            validate_and_correct_album,
        )

        if is_album_name_suspicious(album_name, track_name, artist_name):
            is_valid, correct_album, confidence = validate_and_correct_album(
                artist_name,
                album_name,
                track_name,
                artist_mbid,
                auto_correct=True,
            )
            if not is_valid and correct_album:
                original_album = album_name  # capture BEFORE reassignment (was: bug)
                album_name = correct_album
                log_data_quality_issue(
                    artist_name,
                    f"(was: {original_album})",
                    track_name,
                    correct_album,
                    confidence,
                    auto_corrected=True,
                )
                logger.info(
                    "Auto-corrected album for %s - %s: %r (confidence: %s%%)",
                    artist_name, track_name, correct_album, confidence,
                )

    # --- album_artist: compilation detection (local, reads existing scrobbles) -
    if raw.album_artist_override:
        album_artist = raw.album_artist_override
    elif _is_album_compilation_with_fallback(conn, album_name, album_mbid, artist_name):
        album_artist = (
            artist_name
            if _is_single_artist_album(conn, album_name, album_mbid, artist_name)
            else "Various Artists"
        )
    else:
        album_artist = artist_name

    # --- track validation (local, reads album_tracks) + mismatch notice -----
    if run_track_validation:
        track_validation = validate_scrobble_track(
            conn, artist_name, album_name, track_name, track_mbid
        )
        if not track_validation["is_valid"]:
            create_notification(
                notification_type="track_mismatch",
                title=f"Track mismatch: {artist_name} - {track_name}",
                message=(
                    f'Scrobble track "{track_name}" does not match any track in '
                    f"album_tracks for {artist_name} - {album_name}"
                ),
                details={
                    "artist": artist_name,
                    "album": album_name,
                    "scrobble_track": track_name,
                    "track_mbid": track_mbid,
                    "album_tracks": track_validation.get("album_tracks", []),
                },
                severity="warning",
                conn=conn,  # share the caller's transaction (avoids "database is locked")
            )
            logger.warning('Track mismatch: %s - %s - "%s"', artist_name, album_name, track_name)
        elif track_validation.get("issue_type") == "normalized_match":
            logger.info(
                'Track name variation: "%s" -> "%s" for %s - %s',
                track_name, track_validation.get("matched_track"), artist_name, album_name,
            )

    # --- canonical entity ids (Resolver writes entities + aliases on miss) ---
    artist_id = resolver.resolve_artist_id(artist_name, artist_mbid)
    album_id = resolver.resolve_album_id(artist_id, album_name, album_mbid, album_artist)
    track_id = resolver.resolve_track_id(artist_id, track_name, track_mbid)

    # --- UPSERT: album is correctable metadata, not listen identity ----------
    existing = conn.execute(
        """SELECT artist_mbid, album, album_mbid, track_mbid, album_artist,
                  source, artist_id, album_id, track_id
           FROM scrobble WHERE uts = ? AND artist = ? AND track = ?""",
        (uts, artist_name, track_name),
    ).fetchone()
    cur = conn.execute(
        """
        INSERT INTO scrobble
            (artist, artist_mbid, album, album_mbid,
             track, track_mbid, uts, album_artist, source,
             artist_id, album_id, track_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uts, artist, track) DO UPDATE SET
            artist_mbid = COALESCE(excluded.artist_mbid, scrobble.artist_mbid),
            album = excluded.album,
            album_mbid = excluded.album_mbid,
            track_mbid = COALESCE(excluded.track_mbid, scrobble.track_mbid),
            album_artist = excluded.album_artist,
            source = excluded.source,
            artist_id = excluded.artist_id,
            album_id = excluded.album_id,
            track_id = excluded.track_id
        """,
        (
            artist_name, artist_mbid, album_name, album_mbid,
            track_name, track_mbid, uts, album_artist, raw.source,
            artist_id, album_id, track_id,
        ),
    )
    inserted = existing is None
    new_metadata = (
        artist_mbid or (existing[0] if existing else None),
        album_name,
        album_mbid,
        track_mbid or (existing[3] if existing else None),
        album_artist,
        raw.source, artist_id, album_id, track_id,
    )
    reconciled = existing is not None and tuple(existing) != new_metadata
    if reconciled:
        logger.info(
            "Reconciled scrobble metadata at %s for %s - %s: album %r -> %r",
            uts, artist_name, track_name, existing[1], album_name,
        )

    # --- album_art record (pull path only, when the source carried images) ---
    album_art_record = None
    if album_name and raw.images:
        album_art_record = {
            "artist": artist_name,
            "album": album_name,
            "album_mbid": album_mbid,
            "artist_mbid": artist_mbid,
            "artist_id": artist_id,
            "album_id": album_id,
            "image_small": raw.images.get("small"),
            "image_medium": raw.images.get("medium"),
            "image_large": raw.images.get("large"),
            "image_xlarge": raw.images.get("xlarge"),
        }

    if commit:
        conn.commit()

    return IngestResult(
        inserted=inserted,
        reconciled=reconciled,
        artist_id=artist_id,
        album_id=album_id,
        track_id=track_id,
        album_artist=album_artist,
        album_art_record=album_art_record,
        artist_name=artist_name,
        album_name=album_name,
        track_name=track_name,
    )
