#!/usr/bin/env python3
"""
Spotify playlist generation scheduler.

Provides automated/scheduled playlist generation with configurable
settings and integration with the notification system.

Usage:
    python -m app.services.spotify_playlist_scheduler

    Or run via cron/systemd for automated scheduling:
    # Weekly playlist generation
    0 2 * * 0 cd /path/to/project && python -m app.services.spotify_playlist_scheduler
"""

import logging
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.logging_config import setup_logging, get_logger
from app.services.spotify_config import get_playlist_settings
from app.services.spotify_api import get_spotify_client
from app.services.playlist_generator import get_generator
from app.db.notifications import create_notification

setup_logging()
logger = get_logger(__name__)


def generate_scheduled_playlists():
    """
    Generate playlists based on configured schedule.

    Reads settings from environment variables and generates appropriate playlists:
    - Daily: High rotation (last 7 days)
    - Weekly: Top tracks (last 30 days), Forgotten albums (180 days)
    - Monthly: Top tracks (last 90 days), Deep cuts, Track gaps
    """
    logger.info("Starting scheduled playlist generation...")

    try:
        # Get settings
        settings = get_playlist_settings()

        if not settings.get("auto_generate", False):
            logger.info("Auto-generation is disabled in settings")
            return

        schedule = settings.get("schedule", "weekly")
        default_limit = settings.get("default_limit", 50)

        generator = get_generator()
        generated = []

        # Generate playlists based on schedule
        if schedule == "daily":
            logger.info("Generating daily playlists...")

            # High rotation from last 7 days
            result = generator.generate_high_rotation_playlist(
                days=7,
                min_plays=3,
                limit=default_limit,
                create_on_spotify=True,
            )

            if result.get("spotify_id"):
                generated.append(result["name"])

        elif schedule == "weekly":
            logger.info("Generating weekly playlists...")

            # Top tracks from last 30 days
            result1 = generator.generate_top_tracks_playlist(
                period_days=settings.get("top_tracks_days", 30),
                limit=default_limit,
                create_on_spotify=True,
            )

            if result1.get("spotify_id"):
                generated.append(result1["name"])

            # Forgotten albums
            result2 = generator.generate_forgotten_albums_playlist(
                days_threshold=settings.get("forgotten_days", 180),
                track_limit=default_limit,
                create_on_spotify=True,
            )

            if result2.get("spotify_id"):
                generated.append(result2["name"])

        elif schedule == "monthly":
            logger.info("Generating monthly playlists...")

            # Top tracks from last 90 days
            result1 = generator.generate_top_tracks_playlist(
                period_days=90,
                limit=default_limit,
                create_on_spotify=True,
            )

            if result1.get("spotify_id"):
                generated.append(result1["name"])

            # Deep cuts
            result2 = generator.generate_deep_cuts_playlist(
                min_plays=3,
                max_plays=20,
                limit=default_limit,
                create_on_spotify=True,
            )

            if result2.get("spotify_id"):
                generated.append(result2["name"])

            # Track gaps
            result3 = generator.generate_track_gaps_playlist(
                limit=default_limit,
                create_on_spotify=True,
            )

            if result3.get("spotify_id"):
                generated.append(result3["name"])

        # Create notification
        if generated:
            playlist_list = ", ".join(generated)
            create_notification(
                notification_type="playlist_schedule",
                title=f"Scheduled playlists generated",
                message=f"Successfully created {len(generated)} playlist(s): {playlist_list}",
                severity="info",
            )

            logger.info(f"✓ Generated {len(generated)} scheduled playlists: {playlist_list}")
        else:
            logger.warning("No playlists were generated (possibly authentication or matching issues)")

    except Exception as e:
        logger.error(f"Scheduled playlist generation failed: {e}", exc_info=True)

        create_notification(
            notification_type="playlist_schedule_error",
            title="Scheduled playlist generation failed",
            message=f"Error: {str(e)}",
            severity="error",
        )


def main():
    """Main entry point."""
    try:
        logger.info(f"Spotify playlist scheduler started at {datetime.now()}")

        # Check if authenticated
        try:
            client = get_spotify_client()
            logger.info("✓ Spotify authentication verified")
        except Exception as e:
            logger.warning(f"Spotify not authenticated: {e}")
            create_notification(
                notification_type="spotify_auth",
                title="Spotify not authenticated",
                message="Scheduled playlist generation failed - please authenticate with Spotify first",
                severity="warning",
            )
            return

        generate_scheduled_playlists()

        logger.info("Playlist scheduler completed")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Scheduler failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
