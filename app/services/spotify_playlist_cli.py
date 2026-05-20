#!/usr/bin/env python3
"""
CLI interface for Spotify playlist generation.

Provides command-line tools for:
- Spotify authentication
- Manual playlist generation
- Playlist management

Usage:
    # Authenticate with Spotify
    python -m app.services.spotify_playlist_cli --auth

    # Generate a specific playlist type
    python -m app.services.spotify_playlist_cli forgotten --days 180 --limit 50
    python -m app.services.spotify_playlist_cli top-tracks --days 30 --limit 50

    # Generate AI mix
    python -m app.services.spotify_playlist_cli ai-mix --style forgotten --diversity medium

    # Dry run (show what would be generated)
    python -m app.services.spotify_playlist_cli forgotten --dry-run

    # List available playlist types
    python -m app.services.spotify_playlist_cli --list
"""

import argparse
import sys
import logging
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.logging_config import setup_logging, get_logger
from app.services.spotify_config import get_spotify_credentials
from app.services.spotify_api import SpotifyAPI
from app.services.playlist_generator import PlaylistGenerator, get_generator

setup_logging()
logger = get_logger(__name__)


def cmd_auth(args):
    """Handle authentication command."""
    from urllib.parse import urlencode

    logger.info("Spotify Authentication")
    logger.info("=" * 60)

    try:
        client_id, client_secret, redirect_uri = get_spotify_credentials()

        api = SpotifyAPI()
        auth_url = api.get_auth_url()

        logger.info("\n1. Visit this URL to authorize the application:")
        logger.info(f"\n   {auth_url}\n")

        logger.info("2. After authorizing, you'll be redirected to a URL like:")
        logger.info(f"   {redirect_uri}?code=...")
        logger.info("\n3. Copy the 'code' parameter from that URL")
        logger.info("\n4. Paste it below when prompted\n")

        # For CLI use, we'll need to get the callback URL
        logger.info("Alternatively, use the web interface at /admin/spotify/auth")
        logger.info("for a smoother authentication experience.\n")

        code = input("Enter the authorization code: ").strip()

        if code:
            logger.info("\nExchanging authorization code for access token...")
            token_data = api.exchange_code_for_token(code)

            logger.info("\n✓ Authentication successful!")
            logger.info(f"   Access token expires in: {token_data.get('expires_in')} seconds")
            logger.info("\nYou can now generate playlists using the CLI.")
        else:
            logger.error("No authorization code provided")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Authentication failed: {e}", exc_info=True)
        sys.exit(1)


def cmd_forgotten(args):
    """Generate forgotten albums playlist."""
    logger.info("Generating Forgotten Albums playlist...")

    generator = get_generator()

    result = generator.generate_forgotten_albums_playlist(
        days_threshold=args.days,
        track_limit=args.limit,
        name=args.name,
        description=args.description,
        create_on_spotify=not args.dry_run,
    )

    print_result(result, args.dry_run)


def cmd_top_tracks(args):
    """Generate top tracks playlist."""
    logger.info("Generating Top Tracks playlist...")

    generator = get_generator()

    result = generator.generate_top_tracks_playlist(
        period_days=args.days,
        limit=args.limit,
        name=args.name,
        description=args.description,
        create_on_spotify=not args.dry_run,
    )

    print_result(result, args.dry_run)


def cmd_deep_cuts(args):
    """Generate deep cuts playlist."""
    logger.info("Generating Deep Cuts playlist...")

    generator = get_generator()

    result = generator.generate_deep_cuts_playlist(
        min_plays=args.min_plays,
        max_plays=args.max_plays,
        limit=args.limit,
        create_on_spotify=not args.dry_run,
    )

    print_result(result, args.dry_run)


def cmd_high_rotation(args):
    """Generate high rotation playlist."""
    logger.info("Generating High Rotation playlist...")

    generator = get_generator()

    result = generator.generate_high_rotation_playlist(
        days=args.days,
        min_plays=args.min_plays,
        limit=args.limit,
        create_on_spotify=not args.dry_run,
    )

    print_result(result, args.dry_run)


def cmd_track_gaps(args):
    """Generate track gaps playlist."""
    logger.info("Generating Track Gaps (Rediscover) playlist...")

    generator = get_generator()

    result = generator.generate_track_gaps_playlist(
        limit=args.limit,
        create_on_spotify=not args.dry_run,
    )

    print_result(result, args.dry_run)


def cmd_recent_discoveries(args):
    """Generate recent discoveries playlist."""
    logger.info("Generating Recent Discoveries playlist...")

    generator = get_generator()

    result = generator.generate_recent_discoveries_playlist(
        days=args.days,
        limit=args.limit,
        create_on_spotify=not args.dry_run,
    )

    print_result(result, args.dry_run)


def cmd_ai_mix(args):
    """Generate AI mix playlist."""
    logger.info("Generating AI Mix playlist...")

    generator = get_generator()

    result = generator.generate_ai_mix(
        style=args.style,
        diversity=args.diversity,
        limit=args.limit,
        create_on_spotify=not args.dry_run,
    )

    print_result(result, args.dry_run)


def print_result(result: dict, dry_run: bool):
    """Print playlist generation result."""
    print("\n" + "=" * 60)
    print(f"Playlist: {result['name']}")
    print("=" * 60)
    print(f"Description: {result['description']}")
    print(f"Type: {result['playlist_type']}")
    print(f"Tracks: {result['track_count']}")

    if result.get('matched_tracks'):
        print(f"Matched to Spotify: {result['matched_tracks']} tracks")

    if result.get('spotify_url'):
        print(f"Spotify URL: {result['spotify_url']}")

    if dry_run:
        print("\n[DRY RUN] Playlist was not created on Spotify")
        print("Use --apply flag to create the playlist")

    print("=" * 60)


def cmd_list(args):
    """List available playlist types."""
    print("\n" + "=" * 60)
    print("Available Playlist Types")
    print("=" * 60)
    print("\n  forgotten")
    print("      Albums not played in a long time")
    print("      Options: --days, --limit")
    print("\n  top-tracks")
    print("      Most played tracks in a time period")
    print("      Options: --days, --limit")
    print("\n  deep-cuts")
    print("      Lesser-played tracks from favorite artists")
    print("      Options: --min-plays, --max-plays, --limit")
    print("\n  high-rotation")
    print("      Tracks played frequently recently")
    print("      Options: --days, --min-plays, --limit")
    print("\n  track-gaps")
    print("      Tracks not played in the longest time")
    print("      Options: --limit")
    print("\n  recent-discoveries")
    print("      Tracks first played recently")
    print("      Options: --days, --limit")
    print("\n  ai-mix")
    print("      AI-generated mix based on listening patterns")
    print("      Options: --style, --diversity, --limit")
    print("\n" + "=" * 60)
    print("\nGlobal Options:")
    print("  --dry-run    Show what would be generated without creating")
    print("  --name       Custom playlist name")
    print("  --description Custom playlist description")
    print("\nExamples:")
    print("  python -m app.services.spotify_playlist_cli forgotten --days 180")
    print("  python -m app.services.spotify_playlist_cli top-tracks --days 7 --limit 20")
    print("  python -m app.services.spotify_playlist_cli ai-mix --style discovery")
    print("  python -m app.services.spotify_playlist_cli deep-cuts --dry-run")
    print()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Spotify Playlist Generator - Create playlists based on Last.fm statistics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global options
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated without creating on Spotify")
    parser.add_argument("--name", type=str, help="Custom playlist name")
    parser.add_argument("--description", type=str, help="Custom playlist description")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Auth command
    auth_parser = subparsers.add_parser("auth", help="Authenticate with Spotify")

    # List command
    list_parser = subparsers.add_parser("list", help="List available playlist types")

    # Forgotten albums command
    forgotten_parser = subparsers.add_parser("forgotten", help="Generate forgotten albums playlist")
    forgotten_parser.add_argument("--days", type=int, default=180, help="Days since last play (default: 180)")
    forgotten_parser.add_argument("--limit", type=int, default=50, help="Maximum tracks (default: 50)")

    # Top tracks command
    top_parser = subparsers.add_parser("top-tracks", help="Generate top tracks playlist")
    top_parser.add_argument("--days", type=int, default=30, help="Period in days (default: 30)")
    top_parser.add_argument("--limit", type=int, default=50, help="Maximum tracks (default: 50)")

    # Deep cuts command
    deep_cuts_parser = subparsers.add_parser("deep-cuts", help="Generate deep cuts playlist")
    deep_cuts_parser.add_argument("--min-plays", type=int, default=3, help="Minimum plays (default: 3)")
    deep_cuts_parser.add_argument("--max-plays", type=int, default=20, help="Maximum plays (default: 20)")
    deep_cuts_parser.add_argument("--limit", type=int, default=50, help="Maximum tracks (default: 50)")

    # High rotation command
    high_rotation_parser = subparsers.add_parser("high-rotation", help="Generate high rotation playlist")
    high_rotation_parser.add_argument("--days", type=int, default=7, help="Period in days (default: 7)")
    high_rotation_parser.add_argument("--min-plays", type=int, default=3, help="Minimum plays (default: 3)")
    high_rotation_parser.add_argument("--limit", type=int, default=50, help="Maximum tracks (default: 50)")

    # Track gaps command
    track_gaps_parser = subparsers.add_parser("track-gaps", help="Generate track gaps playlist")
    track_gaps_parser.add_argument("--limit", type=int, default=50, help="Maximum tracks (default: 50)")

    # Recent discoveries command
    discoveries_parser = subparsers.add_parser("recent-discoveries", help="Generate recent discoveries playlist")
    discoveries_parser.add_argument("--days", type=int, default=30, help="Period in days (default: 30)")
    discoveries_parser.add_argument("--limit", type=int, default=50, help="Maximum tracks (default: 50)")

    # AI mix command
    ai_mix_parser = subparsers.add_parser("ai-mix", help="Generate AI mix playlist")
    ai_mix_parser.add_argument(
        "--style",
        type=str,
        choices=["forgotten", "discovery", "familiar", "balanced"],
        default="forgotten",
        help="Playlist style (default: forgotten)",
    )
    ai_mix_parser.add_argument(
        "--diversity", type=str, choices=["low", "medium", "high"], default="medium", help="Artist diversity (default: medium)"
    )
    ai_mix_parser.add_argument("--limit", type=int, default=50, help="Maximum tracks (default: 50)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Route to appropriate command handler
    command_handlers = {
        "auth": cmd_auth,
        "list": cmd_list,
        "forgotten": cmd_forgotten,
        "top-tracks": cmd_top_tracks,
        "deep-cuts": cmd_deep_cuts,
        "high-rotation": cmd_high_rotation,
        "track-gaps": cmd_track_gaps,
        "recent-discoveries": cmd_recent_discoveries,
        "ai-mix": cmd_ai_mix,
    }

    handler = command_handlers.get(args.command)

    if handler:
        try:
            handler(args)
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Command failed: {e}", exc_info=True)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
