"""
Album-related database queries and album art management.
"""
import logging
import re
import io
import struct
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import requests
from flask import current_app, url_for

from .connections import get_db_connection
from .entities import Resolver, lookup_album_id

logger = logging.getLogger(__name__)

# Last.fm uses this specific hash for placeholder album art
LASTFM_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"


def get_album_stats():
    """Total distinct albums and total album scrobbles."""
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT album_id) AS total_albums,
            COUNT(*)                 AS total_scrobbles
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
          AND album_id IS NOT NULL
        """
    ).fetchone()
    conn.close()

    if row is None:
        return {"total_albums": 0, "total_scrobbles": 0}

    return {
        "total_albums": row["total_albums"],
        "total_scrobbles": row["total_scrobbles"],
    }


def get_top_albums(start: str = "", end: str = "", search_term: str = ""):
    """Albums sorted by plays (scrobbles) desc.

    Grouped by canonical album_id so name variants of the same album
    (e.g. 'Heroes' vs '"Heroes"', case/accent differences) count together.
    album_art is pre-collapsed to one row per album_id (MAX year_col) so the
    join never multiplies scrobble rows. Display columns (album/artist) are a
    representative spelling from the group.
    """
    conn = get_db_connection()

    sql = """
        SELECT
            s.album,
            s.artist,
            s.album_artist,
            COUNT(*) AS plays,
            aa.year_col
        FROM scrobble s
        LEFT JOIN (
            SELECT album_id, MAX(year_col) AS year_col
            FROM album_art
            WHERE album_id IS NOT NULL
            GROUP BY album_id
        ) aa ON aa.album_id = s.album_id
        WHERE s.album IS NOT NULL AND s.album != ''
          AND s.album_id IS NOT NULL
    """
    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    # Search filter - case-insensitive partial matching on album, artist, or album_artist
    if search_term:
        sql += """ AND (LOWER(s.album) LIKE ? OR LOWER(s.artist) LIKE ? OR LOWER(s.album_artist) LIKE ?)"""
        search_pattern = f"%{search_term.lower()}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    sql += """
        GROUP BY s.album_id
        ORDER BY plays DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_album_total_plays(album_artist_name: str, album_name: str, start: str = "", end: str = "", album_id: int | None = None) -> int:
    """Get total plays for an album, optionally filtered by date range."""
    conn = get_db_connection()
    if album_id is None:
        album_id = lookup_album_id(conn, album_artist_name, album_name)
    if album_id is None:
        conn.close()
        return 0

    sql = """
        SELECT COUNT(*) AS total
        FROM scrobble
        WHERE album_id = ?
    """
    params = [album_id]

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    row = conn.execute(sql, params).fetchone()
    conn.close()

    return row["total"] if row else 0


def get_album_art(album_artist_name: str, album_name: str, album_id: int | None = None):
    """Get album art information from database."""
    conn = get_db_connection()
    if album_id is None:
        album_id = lookup_album_id(conn, album_artist_name, album_name)
    if album_id is None:
        conn.close()
        return None
    rows = conn.execute(
        """
        SELECT album_id, album_mbid, artist_mbid, image_xlarge
        FROM album_art
        WHERE album_id = ?
        LIMIT 1
        """,
        (album_id,),
    ).fetchone()
    conn.close()
    return rows


def get_album_release_year(album_artist_name: str, album_name: str, table: str = "album_art", col: str = "year_col", album_id: int | None = None) -> str | None:
    """Get the release year for an album."""
    conn = get_db_connection()
    try:
        if album_id is None:
            album_id = lookup_album_id(conn, album_artist_name, album_name)
        if album_id is None:
            return None
        row = conn.execute(
            f"""
            SELECT {col}
            FROM {table}
            WHERE album_id = ?
            LIMIT 1
            """,
            (album_id,),
        ).fetchone()
        if not row:
            return None
        y = row[col]
        return str(y) if y is not None else None
    finally:
        conn.close()


def get_album_wikipedia_url(album_artist_name: str, album_name: str, album_id: int | None = None) -> str | None:
    """Get the Wikipedia URL for an album from the database."""
    conn = get_db_connection()
    try:
        if album_id is None:
            album_id = lookup_album_id(conn, album_artist_name, album_name)
        if album_id is None:
            return None
        row = conn.execute(
            """
            SELECT wikipedia_url
            FROM album_art
            WHERE album_id = ?
            LIMIT 1
            """,
            (album_id,),
        ).fetchone()
        if row and row["wikipedia_url"]:
            return row["wikipedia_url"]
        return None
    finally:
        conn.close()


def set_album_wikipedia_url(album_artist_name: str, album_name: str, wikipedia_url: str, album_id: int | None = None) -> bool:
    """Set the Wikipedia URL for an album in the database."""
    conn = get_db_connection()
    try:
        if album_id is None:
            album_id = lookup_album_id(conn, album_artist_name, album_name)
        if album_id is None:
            return False
        conn.execute(
            """
            UPDATE album_art
            SET wikipedia_url = ?
            WHERE album_id = ?
            """,
            (wikipedia_url, album_id),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def album_tracks_exist(album_artist_name: str, album_name: str, album_mbid: str = None, album_id: int | None = None) -> bool:
    """Check if album tracks exist in the database."""
    conn = get_db_connection()
    is_va = album_artist_name.lower() in ("various artists", "various artist")

    if is_va and album_mbid:
        # Compilations with MBID: tracks carry individual artists, so check by mbid.
        row = conn.execute(
            "SELECT 1 FROM album_tracks WHERE album_mbid = ? LIMIT 1",
            (album_mbid,),
        ).fetchone()
    elif is_va:
        # Compilation without MBID: album_tracks keyed by per-track artist, so
        # check by album name.
        row = conn.execute(
            "SELECT 1 FROM album_tracks WHERE album = ? LIMIT 1",
            (album_name,),
        ).fetchone()
    else:
        # Regular albums: check by canonical album_id.
        if album_id is None:
            album_id = lookup_album_id(conn, album_artist_name, album_name)
        if album_id is None:
            conn.close()
            return False
        row = conn.execute(
            "SELECT 1 FROM album_tracks WHERE album_id = ? LIMIT 1",
            (album_id,),
        ).fetchone()

    conn.close()
    return row is not None


def upsert_album_tracks(album_artist_name: str, album_name: str, tracks: list[dict[str, Any]], album_mbid: str = None):
    """
    Insert or replace album tracks in the database.

    Args:
        album_artist_name: The artist name (fallback if track lacks individual artist)
        album_name: The album name
        tracks: list of dicts: [
            {"artist": "Tool", "track": "The Grudge", "track_number": 1, "track_mbid": "..."},
            ...
        ]
        album_mbid: MusicBrainz release ID (optional)
    """
    conn = get_db_connection()
    resolver = Resolver(conn)
    # The album entity is shared across all tracks; key it under the album's
    # nominal artist. Each track resolves its own artist_id / track_id.
    album_owner_id = resolver.resolve_artist_id(album_artist_name)
    album_id = resolver.resolve_album_id(album_owner_id, album_name, album_mbid)
    rows = []
    for t in tracks:
        track_artist = t.get("artist", album_artist_name)
        artist_id = resolver.resolve_artist_id(track_artist)
        track_id = resolver.resolve_track_id(artist_id, t["track"], t.get("track_mbid"))
        rows.append((
            track_artist, album_name, t["track"], t["track_number"],
            t.get("track_mbid"), album_mbid,
            artist_id, album_id, track_id,
        ))
    conn.executemany(
        """
        INSERT OR REPLACE INTO album_tracks
            (artist, album, track, track_number, track_mbid, album_mbid,
             artist_id, album_id, track_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def ensure_album_mbid_consistency(artist_name: str, album_name: str, album_mbid: str = None) -> str | None:
    """
    Ensure MBID consistency across scrobble, album_art, and album_tracks tables.

    When updating album MBIDs, this function ensures all three tables use the same MBID:
    1. If album_art has an MBID, use that (most reliable source)
    2. Otherwise, use the provided album_mbid parameter
    3. Updates all three tables to use the consistent MBID

    Args:
        artist_name: Artist name
        album_name: Album name
        album_mbid: Optional MBID to set if album_art doesn't have one

    Returns:
        The final consistent MBID, or None if no MBID is available
    """
    conn = get_db_connection()

    # First, check if album_art has an MBID (preferred source)
    art_row = conn.execute(
        """
        SELECT album_mbid
        FROM album_art
        WHERE artist = ? AND album = ?
        LIMIT 1
        """,
        (artist_name, album_name)
    ).fetchone()

    if art_row and art_row["album_mbid"]:
        final_mbid = art_row["album_mbid"]
    else:
        final_mbid = album_mbid

    if not final_mbid:
        conn.close()
        return None

    # Update scrobbles that are missing MBID or have a different MBID
    conn.execute(
        """
        UPDATE scrobble
        SET album_mbid = ?
        WHERE artist = ? AND album = ?
          AND (album_mbid IS NULL OR album_mbid != ?)
        """,
        (final_mbid, artist_name, album_name, final_mbid)
    )

    # Update album_art MBID if missing
    conn.execute(
        """
        UPDATE album_art
        SET album_mbid = ?
        WHERE artist = ? AND album = ?
          AND (album_mbid IS NULL OR album_mbid = '')
        """,
        (final_mbid, artist_name, album_name)
    )

    # Update album_tracks MBID if missing
    conn.execute(
        """
        UPDATE album_tracks
        SET album_mbid = ?
        WHERE artist = ? AND album = ?
          AND (album_mbid IS NULL OR album_mbid = '')
        """,
        (final_mbid, artist_name, album_name)
    )

    conn.commit()
    conn.close()

    logger.info(f"Ensured MBID consistency for {artist_name} - {album_name}: {final_mbid}")
    return final_mbid


def get_album_tracks(album_artist_name: str, album_name: str, start: str = "", end: str = "", sort_by: str = "tracklist"):
    """
    Returns exactly ONE row per track, ordered by album track number (default)
    or by play count (if sort_by='plays'), with correct play counts.

    Play counts join scrobble on the canonical track_id, so name variants,
    escaped characters, and mistagged album_mbids no longer fragment counts.
    Regular albums select their tracklist by album_id (unifies album-name
    variants); Various Artists compilations select by album name (their
    album_tracks album_id is keyed by per-track artist).
    """
    conn = get_db_connection()

    is_various_artists = album_artist_name.lower() in ("various artists", "various artist")

    # Resolve the album's canonical id. Plays are scoped to this album_id, so
    # counts reflect THIS album only (no cross-album inflation for tracks that
    # appear elsewhere) while still uniting its album_mbid/name variants.
    album_id = lookup_album_id(conn, album_artist_name, album_name)
    if album_id is None:
        conn.close()
        return []

    # Date predicate lives in the LEFT JOIN's ON clause so tracks with 0 plays
    # in the range still appear.
    date_join = ""
    date_params: list = []
    if start and end:
        date_join = ("AND date(s.uts, 'unixepoch', 'localtime') >= ? "
                     "AND date(s.uts, 'unixepoch', 'localtime') <= ?")
        date_params = [start, end]

    if is_various_artists:
        # VA compilations: album_tracks.album_id is keyed by per-track artist, so
        # select the tracklist by album NAME (deduped to a real artist per track).
        # Plays still scope by the sentinel album_id on the scrobble side.
        tracklist = """
            FROM (
                SELECT track_number, track, artist, track_id
                FROM album_tracks
                WHERE album = ?
                  AND rowid IN (
                      SELECT rowid FROM (
                          SELECT rowid, ROW_NUMBER() OVER (
                              PARTITION BY track_number, track
                              ORDER BY CASE WHEN artist != 'Various Artists' THEN 0 ELSE 1 END, rowid
                          ) AS rn
                          FROM album_tracks
                          WHERE album = ?
                      )
                      WHERE rn = 1
                  )
            ) at
        """
        tracklist_params = [album_name, album_name]
    else:
        # Regular albums: select the tracklist by canonical album_id.
        tracklist = "FROM album_tracks at"
        tracklist_params = []

    sql = f"""
        SELECT at.track_number, at.track AS track_name, at.artist AS track_artist,
               COUNT(s.id) AS plays
        {tracklist}
        LEFT JOIN scrobble s
               ON s.track_id = at.track_id
              AND s.album_id = ?
              {date_join}
        {"WHERE at.album_id = ?" if not is_various_artists else ""}
        GROUP BY at.track_id, at.track_number, at.track, at.artist
        ORDER BY at.track_number
    """
    params = tracklist_params + [album_id] + date_params + ([] if is_various_artists else [album_id])

    results = conn.execute(sql, params).fetchall()
    conn.close()

    # Sort by play count if requested
    if sort_by == "plays":
        results = sorted(results, key=lambda r: (-r["plays"], r["track_number"]))

    return results


# Album Art Caching Functions

def _safe_slug(text: str) -> str:
    """Convert text to safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '_', text)
    return text[:100]


def _guess_ext_from_url(url: str) -> str:
    """Guess file extension from URL."""
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def ensure_album_art_cached(album_artist_name: str, album_name: str, album_id: int | None = None) -> str | None:
    """
    - Looks up album_art.image_xlarge for (artist_name, album_name)
    - Downloads it once into: <app static>/covers/<key>.<ext>
    - Returns a local static URL to be used in templates
    """
    conn = get_db_connection()

    if album_id is None:
        album_id = lookup_album_id(conn, album_artist_name, album_name)
    art_row = None
    if album_id is not None:
        art_row = conn.execute(
            """
            SELECT album_mbid, image_xlarge
            FROM album_art
            WHERE album_id = ?
            LIMIT 1
            """,
            (album_id,),
        ).fetchone()

    album_mbid = (art_row["album_mbid"] or "").strip() if art_row else ""
    cdn_url = (art_row["image_xlarge"] or "").strip() if art_row else ""

    # Check if the CDN URL is Last.fm's placeholder
    is_placeholder = LASTFM_PLACEHOLDER_HASH in cdn_url

    # Prefer MBID for stable filename; otherwise slug artist+album
    cache_key = album_mbid if album_mbid else f"{_safe_slug(album_artist_name)}__{_safe_slug(album_name)}"

    covers_rel_dir = Path("covers")
    covers_abs_dir = Path(current_app.static_folder) / covers_rel_dir
    covers_abs_dir.mkdir(parents=True, exist_ok=True)

    # Serve any existing local file for this cache key BEFORE the placeholder
    # logic below. This is critical: a user-uploaded cover is written to disk but
    # does not update album_art.image_xlarge, which may still hold Last.fm's
    # placeholder URL. If the placeholder cleanup ran first, it would unlink the
    # user's upload on every page load (the cover would vanish within a second of
    # uploading). Returning here also handles uploads whose extension differs from
    # the DB URL, and uploads made when no album_art row exists yet.
    logger.debug(f"ensure_album_art_cached: cache_key={cache_key}, static_folder={current_app.static_folder}")
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        abs_path = covers_abs_dir / f"{cache_key}{ext}"
        logger.debug(f"  Checking: {abs_path}, exists={abs_path.exists()}")
        if abs_path.exists() and abs_path.stat().st_size > 0:
            logger.debug(f"  Found local file: {cache_key}{ext}")
            return url_for("static", filename=f"covers/{cache_key}{ext}")

    # No local cover exists. If the album_art URL is Last.fm's placeholder, there
    # is nothing real to show or download — return None rather than caching the
    # placeholder image.
    if is_placeholder:
        return None

    # No local file found, proceed to download from CDN if available
    if not cdn_url:
        return None

    # No local file found, proceed to download
    ext = _guess_ext_from_url(cdn_url)
    filename = f"{cache_key}{ext}"
    abs_path = covers_abs_dir / filename

    # Download once
    try:
        r = requests.get(
            cdn_url,
            timeout=12,
            stream=True,
            headers={"User-Agent": "Scrobbles/1.0"},
        )
        if r.status_code != 200:
            return None

        # Refine extension from Content-Type if needed
        ct = (r.headers.get("Content-Type") or "").lower()
        if "image/png" in ct:
            ext = ".png"
        elif "image/webp" in ct:
            ext = ".webp"
        elif "image/jpeg" in ct or "image/jpg" in ct:
            ext = ".jpg"

        filename = f"{cache_key}{ext}"
        abs_path = covers_abs_dir / filename

        with open(abs_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)

        if abs_path.exists() and abs_path.stat().st_size > 0:
            return url_for("static", filename=f"covers/{filename}")

        return None

    except requests.RequestException:
        return None


def _is_valid_image(file_content: bytes) -> bool:
    """
    Validate file is an actual image using magic bytes.
    This prevents uploading non-image files with image extensions.
    """
    # Magic bytes for common image formats
    magic_bytes = {
        b"\xFF\xD8\xFF": "jpg",  # JPEG
        b"\x89\x50\x4E\x47\x0D\x0A\x1A\x0A": "png",  # PNG
        b"RIFF": "webp",  # WEBP (RIFF...WEBP)
    }

    if len(file_content) < 8:
        return False

    # Check each magic byte pattern
    for magic, fmt in magic_bytes.items():
        if file_content.startswith(magic):
            # For WEBP, need to verify the WEBP marker
            if fmt == "webp" and len(file_content) >= 12:
                return file_content[8:12] == b"WEBP"
            return True

    return False


def _save_cover_as_is(album_artist_name: str, album_name: str, file_content: bytes, ext: str) -> dict:
    """Save cover image without processing (Pillow not available fallback)."""
    # Normalize extension
    if ext == ".jpeg":
        ext = ".jpg"

    covers_rel_dir = Path("covers")
    covers_abs_dir = Path(current_app.static_folder) / covers_rel_dir
    covers_abs_dir.mkdir(parents=True, exist_ok=True)

    # Use same naming scheme as ensure_album_art_cached
    art_row = get_album_art(album_artist_name, album_name)
    album_mbid = (art_row["album_mbid"] or "").strip() if art_row else ""

    cache_key = album_mbid if album_mbid else f"{_safe_slug(album_artist_name)}__{_safe_slug(album_name)}"
    filename = f"{cache_key}{ext}"
    abs_path = covers_abs_dir / filename

    with open(abs_path, "wb") as f:
        f.write(file_content)

    if abs_path.exists() and abs_path.stat().st_size > 0:
        return {"cover_url": url_for("static", filename=f"covers/{filename}")}

    return {"error": "Failed to save image"}


def _save_cover_to_disk(album_artist_name: str, album_name: str, file_content: bytes, ext: str) -> dict:
    """Save processed cover image to disk."""
    covers_rel_dir = Path("covers")
    covers_abs_dir = Path(current_app.static_folder) / covers_rel_dir
    covers_abs_dir.mkdir(parents=True, exist_ok=True)

    # Use same naming scheme as ensure_album_art_cached
    art_row = get_album_art(album_artist_name, album_name)
    album_mbid = (art_row["album_mbid"] or "").strip() if art_row else ""

    cache_key = album_mbid if album_mbid else f"{_safe_slug(album_artist_name)}__{_safe_slug(album_name)}"
    filename = f"{cache_key}{ext}"
    abs_path = covers_abs_dir / filename

    with open(abs_path, "wb") as f:
        f.write(file_content)

    if abs_path.exists() and abs_path.stat().st_size > 0:
        return {"cover_url": url_for("static", filename=f"covers/{filename}")}

    return {"error": "Failed to save image"}


def save_uploaded_cover(album_artist_name: str, album_name: str, file_storage) -> dict:
    """
    Save an uploaded album cover image.

    Validates the file is an image, resizes to 220x220px, converts to JPG,
    and saves to the covers directory.

    Args:
        album_artist_name: The artist name
        album_name: The album name
        file_storage: Flask FileStorage object from request.files

    Returns:
        dict with "cover_url" on success, or {"error": "message"} on failure
    """
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
    ALLOWED_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    TARGET_SIZE = (220, 220)

    try:
        # Check file extension
        filename = file_storage.filename or ""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return {"error": f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}

        # Check MIME type
        content_type = (file_storage.content_type or "").lower()
        if content_type not in ALLOWED_MIME_TYPES:
            return {"error": f"Invalid content type. Allowed: {', '.join(ALLOWED_MIME_TYPES)}"}

        # Read file content
        file_content = file_storage.read()

        # Check file size
        if len(file_content) > MAX_FILE_SIZE:
            return {"error": f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"}

        # Validate it's actually an image by checking magic bytes
        if not _is_valid_image(file_content):
            return {"error": "File is not a valid image or is corrupted"}

        # Try to import Pillow for image processing
        try:
            from PIL import Image
        except ImportError:
            # Pillow not available - save as-is (will still have validated it's an image)
            logger.warning("Pillow not installed, saving cover without resizing/conversion")
            return _save_cover_as_is(album_artist_name, album_name, file_content, ext)

        # Process image with Pillow
        image = Image.open(io.BytesIO(file_content))

        # Convert to RGB (for PNG with alpha channel, etc.)
        if image.mode in ("RGBA", "LA", "P"):
            # Create white background for transparent images
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            if image.mode in ("RGBA", "LA"):
                background.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
                image = background
            else:
                image = image.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")

        # Resize to target size using high-quality resampling
        # Only resize if larger than target to avoid upscaling small images
        if image.width > TARGET_SIZE[0] or image.height > TARGET_SIZE[1]:
            image.thumbnail(TARGET_SIZE, Image.Resampling.LANCZOS)

        # Create canvas for exact 220x220 (center the image)
        final_image = Image.new("RGB", TARGET_SIZE, (255, 255, 255))
        paste_x = (TARGET_SIZE[0] - image.width) // 2
        paste_y = (TARGET_SIZE[1] - image.height) // 2
        final_image.paste(image, (paste_x, paste_y))

        # Save as JPG
        output = io.BytesIO()
        final_image.save(output, format="JPEG", quality=90, optimize=True)
        jpg_content = output.getvalue()

        # Save to file
        return _save_cover_to_disk(album_artist_name, album_name, jpg_content, ".jpg")

    except Exception as e:
        logger.error(f"Error processing uploaded cover: {e}", exc_info=True)
        return {"error": "Failed to process image"}


def get_compilation_stats():
    """Total distinct compilations and total compilation scrobbles."""
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT COALESCE(s.album_mbid, s.album)) AS total_compilations,
            COUNT(*)              AS total_scrobbles
        FROM scrobble s
        WHERE s.album_artist = 'Various Artists'
          AND s.album IS NOT NULL AND s.album != ''
        """
    ).fetchone()
    conn.close()

    if row is None:
        return {"total_compilations": 0, "total_scrobbles": 0}

    return {
        "total_compilations": row["total_compilations"],
        "total_scrobbles": row["total_scrobbles"],
    }


def get_top_compilations(start: str = "", end: str = "", search_term: str = ""):
    """Compilations sorted by plays (scrobbles) desc."""
    conn = get_db_connection()

    # Grouped by canonical album_id so a compilation fragmented by missing or
    # mistagged album_mbid (or album-name variants) still counts as one album.
    # album_art is pre-collapsed to one row per album_id so the join does not
    # multiply scrobble rows; a window function picks a representative artist.
    sql = """
        WITH compilation_stats AS (
            SELECT
                s.album_id AS album_key,
                MAX(s.album_mbid) AS album_mbid,
                MAX(s.album) AS album,
                COUNT(DISTINCT s.artist) AS artist_count,
                COUNT(*) AS plays,
                MAX(aa.year_col) AS year_col
            FROM scrobble s
            LEFT JOIN (
                SELECT album_id, MAX(year_col) AS year_col
                FROM album_art
                WHERE album_id IS NOT NULL
                GROUP BY album_id
            ) aa ON aa.album_id = s.album_id
            WHERE s.album_artist = 'Various Artists'
              AND s.album IS NOT NULL AND s.album != ''
              AND s.album_id IS NOT NULL
        """
    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    # Search filter - case-insensitive partial matching on album
    if search_term:
        sql += """ AND LOWER(s.album) LIKE ?"""
        search_pattern = f"%{search_term.lower()}%"
        params.append(search_pattern)

    sql += """
            GROUP BY s.album_id
        ),
        top_artists AS (
            SELECT
                s.album_id AS album_key,
                s.artist AS representative_artist
            FROM scrobble s
            WHERE s.album_artist = 'Various Artists'
              AND s.album IS NOT NULL AND s.album != ''
              AND s.album_id IS NOT NULL
            GROUP BY s.album_id, s.artist
        )
        SELECT
            cs.*,
            ta.representative_artist
        FROM compilation_stats cs
        LEFT JOIN (
            SELECT album_key, representative_artist,
                   ROW_NUMBER() OVER (PARTITION BY album_key ORDER BY representative_artist) AS rn
            FROM top_artists
        ) ta ON cs.album_key = ta.album_key AND ta.rn = 1
        ORDER BY cs.plays DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_compilation_artists(album_name: str, album_id: int | None = None) -> list[dict]:
    """Get all distinct artists for a compilation album."""
    conn = get_db_connection()
    if album_id is None:
        album_id = lookup_album_id(conn, "Various Artists", album_name)
    if album_id is None:
        conn.close()
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT artist
        FROM scrobble
        WHERE album_id = ?
        ORDER BY artist
        """,
        (album_id,),
    ).fetchall()
    conn.close()
    return rows


def get_album_total_plays_by_mbid(album_mbid: str, album_name: str, start: str = "", end: str = "", album_id: int | None = None) -> int:
    """Get total plays for an album by MBID, optionally filtered by date range."""
    conn = get_db_connection()
    if album_id is None:
        row = conn.execute(
            "SELECT album_id FROM scrobble WHERE album_mbid = ? AND album_id IS NOT NULL "
            "GROUP BY album_id ORDER BY COUNT(*) DESC LIMIT 1",
            (album_mbid,),
        ).fetchone()
        album_id = row[0] if row else None
    if album_id is None:
        conn.close()
        return 0

    sql = """
        SELECT COUNT(*) AS total
        FROM scrobble
        WHERE album_id = ?
    """
    params = [album_id]

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    row = conn.execute(sql, params).fetchone()
    conn.close()

    return row["total"] if row else 0


def get_album_tracks_by_mbid(
    album_mbid: str,
    album_name: str,
    start: str = "",
    end: str = "",
    sort_by: str = "tracklist",
    album_id: int | None = None,
):
    """
    Get album tracks by MBID.
    Returns exactly ONE row per track, ordered by album track number (default)
    or by play count (if sort_by='plays'), with correct play counts.

    The tracklist is selected by album_mbid (shared by every track of one
    release, VA compilations included). Plays join scrobble on the canonical
    track_id AND scope to this album's album_id (resolved from the scrobbles
    carrying this mbid), so a track scrobbled under a different album_mbid of
    the SAME album still counts, while plays from other albums do not inflate
    it. The old 0-plays album-name fallback is obsolete.
    (album_name is retained for signature compatibility but unused.)
    """
    if not album_mbid:
        return []

    conn = get_db_connection()

    # A known single-artist album_id is authoritative. MBIDs and generic album
    # names such as "Greatest Hits" can otherwise pull in unrelated releases.
    scope_tracklist_by_id = album_id is not None
    if album_id is None:
        aid_row = conn.execute(
            """
            SELECT album_id FROM scrobble
            WHERE album_mbid = ? AND album_id IS NOT NULL
            GROUP BY album_id ORDER BY COUNT(*) DESC LIMIT 1
            """,
            (album_mbid,),
        ).fetchone()
        if aid_row is None:
            conn.close()
            return []
        album_id = aid_row[0]

    track_scope = "album_id = ?" if scope_tracklist_by_id else "album_mbid = ?"
    track_scope_value = album_id if scope_tracklist_by_id else album_mbid

    date_join = ""
    date_params: list = []
    if start and end:
        date_join = ("AND date(s.uts, 'unixepoch', 'localtime') >= ? "
                     "AND date(s.uts, 'unixepoch', 'localtime') <= ?")
        date_params = [start, end]

    sql = f"""
        SELECT at.track_number, at.track AS track_name, at.artist AS track_artist,
               COUNT(s.id) AS plays
        FROM (
            SELECT track_number, track, artist, track_id
            FROM album_tracks
            WHERE {track_scope}
              AND rowid IN (
                  SELECT rowid FROM (
                      SELECT rowid, ROW_NUMBER() OVER (
                          PARTITION BY track_number, track
                          ORDER BY CASE WHEN artist != 'Various Artists' THEN 0 ELSE 1 END, rowid
                      ) AS rn
                      FROM album_tracks
                      WHERE {track_scope}
                  )
                  WHERE rn = 1
              )
        ) at
        LEFT JOIN scrobble s
               ON s.track_id = at.track_id
              AND s.album_id = ?
              {date_join}
        GROUP BY at.track_id, at.track_number, at.track, at.artist
        ORDER BY at.track_number
    """
    params = [track_scope_value, track_scope_value, album_id] + date_params

    results = conn.execute(sql, params).fetchall()
    conn.close()

    if sort_by == "plays":
        results = sorted(results, key=lambda r: (-r["plays"], r["track_number"]))

    return results


def get_compilation_artists_by_mbid(album_mbid: str, album_name: str, album_id: int | None = None) -> list[dict]:
    """Get all distinct artists for a compilation album by MBID."""
    conn = get_db_connection()
    if album_id is None:
        row = conn.execute(
            "SELECT album_id FROM scrobble WHERE album_mbid = ? AND album_id IS NOT NULL "
            "GROUP BY album_id ORDER BY COUNT(*) DESC LIMIT 1",
            (album_mbid,),
        ).fetchone()
        album_id = row[0] if row else None
    if album_id is None:
        conn.close()
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT artist
        FROM scrobble
        WHERE album_id = ?
        ORDER BY artist
        """,
        (album_id,),
    ).fetchall()
    conn.close()
    return rows
