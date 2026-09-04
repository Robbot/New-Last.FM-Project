#!/usr/bin/env bash

# Run a Last.fm maintenance command with the same environment used by the
# systemd web service. Cron starts with a minimal environment and does not read
# EnvironmentFile= from lastfm-web.service.
set -euo pipefail

readonly APP_ROOT="/home/roju/New-Last.FM-Project"
readonly ENV_FILE="/etc/lastfm/lastfm.env"

if [[ ! -r "$ENV_FILE" ]]; then
    printf 'Cannot read Last.fm environment file: %s\n' "$ENV_FILE" >&2
    exit 1
fi

if (( $# == 0 )); then
    printf 'Usage: %s COMMAND [ARG ...]\n' "$0" >&2
    exit 2
fi

# systemd EnvironmentFile entries are not automatically exported by a shell.
# Export every assignment while loading the shared credential file.
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

cd "$APP_ROOT"
exec "$@"
