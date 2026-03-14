import os
import glob
import sqlite3
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, current_app, redirect, url_for
from functools import wraps
from . import admin_bp
from app.logging_config import get_logger

logger = get_logger(__name__)

# Default: keep logs for 30 days
DEFAULT_LOG_RETENTION_DAYS = 30


def is_localhost_allowed(remote_addr):
    """Check if the request is from localhost or local network."""
    if not remote_addr:
        return False

    # Allow localhost variants
    localhost_addrs = {
        '127.0.0.1',
        'localhost',
        '::1',
    }

    if remote_addr in localhost_addrs:
        return True

    # Allow local network (192.168.x.x)
    if remote_addr.startswith('192.168.'):
        return True

    # Allow 10.x.x.x (private network)
    if remote_addr.startswith('10.'):
        return True

    return False


def require_localhost(f):
    """Decorator to restrict access to localhost only."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        remote_addr = request.remote_addr

        # Check X-Forwarded-For header for proxy setups
        if request.headers.get('X-Forwarded-For'):
            forwarded_ips = request.headers.get('X-Forwarded-For').split(',')
            remote_addr = forwarded_ips[0].strip()

        if not is_localhost_allowed(remote_addr):
            logger.warning(f"Admin access denied from {remote_addr}")

            # Return JSON for API requests, HTML for browser requests
            if request.path.startswith('/admin/database/execute') or request.path == '/admin/sync' or request.path == '/admin/logs/cleanup':
                return jsonify({
                    "error": "Access denied",
                    "message": "Admin panel is only accessible from localhost or local network (192.168.x.x or 10.x.x.x)"
                }), 403
            else:
                return render_template("admin/access_denied.html"), 403

        return f(*args, **kwargs)
    return decorated_function


def cleanup_old_logs(logs_dir, retention_days=DEFAULT_LOG_RETENTION_DAYS):
    """
    Remove log files older than the specified retention period.

    Args:
        logs_dir: Path to the logs directory
        retention_days: Number of days to keep logs (default: 30)

    Returns:
        dict: Summary of cleanup operation
    """
    if not os.path.exists(logs_dir):
        return {"deleted": 0, "freed_bytes": 0, "errors": []}

    cutoff_date = datetime.now() - timedelta(days=retention_days)
    deleted_files = []
    errors = []
    freed_bytes = 0

    for log_file in glob.glob(os.path.join(logs_dir, 'app_*.log')):
        try:
            # Extract date from filename (app_YYYYMMDD.log)
            basename = os.path.basename(log_file)
            date_str = basename.replace('app_', '').replace('.log', '')

            try:
                file_date = datetime.strptime(date_str, '%Y%m%d')

                # Skip if file is newer than cutoff
                if file_date >= cutoff_date:
                    continue

                # Delete old file
                file_size = os.path.getsize(log_file)
                os.remove(log_file)
                deleted_files.append(basename)
                freed_bytes += file_size
                logger.info(f"Deleted old log file: {basename}")

            except ValueError:
                # Filename doesn't match expected pattern, skip
                continue

        except Exception as e:
            errors.append(f"{basename}: {str(e)}")
            logger.error(f"Error deleting log file {log_file}: {e}")

    return {
        "deleted": len(deleted_files),
        "deleted_files": deleted_files,
        "freed_bytes": freed_bytes,
        "errors": errors
    }


@admin_bp.route("/admin")
@require_localhost
def admin_dashboard():
    """Admin dashboard with overview and quick actions."""
    # Get database info
    db_path = current_app.config.get('DATABASE_PATH', 'files/lastfmstats.sqlite')

    db_info = {
        "path": db_path,
        "exists": os.path.exists(db_path),
        "size": None
    }

    if os.path.exists(db_path):
        db_info["size"] = os.path.getsize(db_path)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Get table counts
            tables = {}
            for table in ['scrobble', 'album_art', 'album_tracks']:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                tables[table] = cursor.fetchone()[0]

            db_info["tables"] = tables
            conn.close()
        except sqlite3.Error as e:
            db_info["error"] = str(e)

    # Get log files info
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'logs')
    log_files = []

    if os.path.exists(logs_dir):
        for log_file in sorted(glob.glob(os.path.join(logs_dir, 'app_*.log')), reverse=True):
            stat = os.stat(log_file)
            log_files.append({
                "name": os.path.basename(log_file),
                "path": log_file,
                "size": stat.st_size,
                "modified": stat.st_mtime
            })

    # Get sync log if exists
    sync_log = os.path.join(logs_dir, 'sync_cron.log')
    sync_log_info = None
    if os.path.exists(sync_log):
        stat = os.stat(sync_log)
        sync_log_info = {
            "name": os.path.basename(sync_log),
            "path": sync_log,
            "size": stat.st_size,
            "modified": stat.st_mtime
        }

    return render_template("admin/dashboard.html",
                           db_info=db_info,
                           log_files=log_files,
                           sync_log=sync_log_info)


@admin_bp.route("/admin/logs")
@require_localhost
def admin_logs():
    """View log files."""
    log_name = request.args.get('file', '')
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'logs')

    # List all log files
    log_files = []
    if os.path.exists(logs_dir):
        for log_file in sorted(glob.glob(os.path.join(logs_dir, '*.log')), reverse=True):
            stat = os.stat(log_file)
            log_files.append({
                "name": os.path.basename(log_file),
                "size": stat.st_size,
                "modified": stat.st_mtime
            })

    content = None
    current_log = None
    lines = 100  # Default lines to show

    if log_name:
        # Sanitize the log name to prevent directory traversal
        log_name = os.path.basename(log_name)
        log_path = os.path.join(logs_dir, log_name)

        if os.path.exists(log_path) and log_path.endswith('.log'):
            current_log = log_name
            lines = request.args.get('lines', 100, type=int)
            lines = max(10, min(10000, lines))  # Limit between 10 and 10000 lines

            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    # Read last N lines
                    all_lines = f.readlines()
                    content = all_lines[-lines:] if len(all_lines) > lines else all_lines
            except Exception as e:
                content = [f"Error reading log file: {str(e)}\n"]

    return render_template("admin/logs.html",
                           log_files=log_files,
                           current_log=current_log,
                           content=content,
                           lines=lines)


@admin_bp.route("/admin/database")
@require_localhost
def admin_database():
    """Database browser and editor."""
    db_path = current_app.config.get('DATABASE_PATH', 'files/lastfmstats.sqlite')

    if not os.path.exists(db_path):
        return render_template("admin/database.html", error="Database file not found")

    table = request.args.get('table', 'scrobble')
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get list of tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    # Validate table name
    if table not in tables:
        table = tables[0] if tables else 'scrobble'

    # Get table schema
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row['name'] for row in cursor.fetchall()]

    # Get total count
    cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
    total_count = cursor.fetchone()['count']
    total_pages = (total_count + per_page - 1) // per_page

    # Get data with pagination
    cursor.execute(f"SELECT * FROM {table} ORDER BY rowid LIMIT ? OFFSET ?", (per_page, offset))
    rows = cursor.fetchall()

    conn.close()

    return render_template("admin/database.html",
                           tables=tables,
                           current_table=table,
                           columns=columns,
                           rows=rows,
                           page=page,
                           total_pages=total_pages,
                           total_count=total_count)


@admin_bp.route("/admin/database/execute", methods=['POST'])
@require_localhost
def admin_database_execute():
    """Execute a custom SQL query (read-only for safety)."""
    db_path = current_app.config.get('DATABASE_PATH', 'files/lastfmstats.sqlite')

    if not os.path.exists(db_path):
        return jsonify({"error": "Database file not found"}), 404

    query = request.form.get('query', '').strip()

    if not query:
        return jsonify({"error": "No query provided"}), 400

    # Safety check: only allow SELECT queries
    if not query.upper().startswith('SELECT'):
        return jsonify({"error": "Only SELECT queries are allowed for security"}), 400

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()

        return jsonify({
            "success": True,
            "columns": columns,
            "rows": [dict(row) for row in rows],
            "count": len(rows)
        })
    except sqlite3.Error as e:
        logger.error(f"Database query error: {e}")
        return jsonify({"error": str(e)}), 400


@admin_bp.route("/admin/sync", methods=['POST'])
@require_localhost
def admin_sync():
    """Trigger a Last.fm sync."""
    import subprocess

    try:
        result = subprocess.run(
            ['python', '-m', 'app.services.sync_lastfm'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        return jsonify({
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Sync timed out after 5 minutes"}), 500
    except Exception as e:
        logger.error(f"Sync error: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/admin/logs/cleanup", methods=['POST'])
@require_localhost
def admin_logs_cleanup():
    """Clean up old log files."""
    retention_days = request.json.get('days', DEFAULT_LOG_RETENTION_DAYS) if request.is_json else DEFAULT_LOG_RETENTION_DAYS

    # Validate retention days
    try:
        retention_days = int(retention_days)
        if retention_days < 1:
            retention_days = 1
        elif retention_days > 365:
            retention_days = 365
    except (ValueError, TypeError):
        retention_days = DEFAULT_LOG_RETENTION_DAYS

    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'logs')
    result = cleanup_old_logs(logs_dir, retention_days)

    return jsonify({
        "success": True,
        "deleted": result["deleted"],
        "freed_bytes": result["freed_bytes"],
        "freed_mb": round(result["freed_bytes"] / 1024 / 1024, 2),
        "deleted_files": result["deleted_files"],
        "errors": result["errors"],
        "retention_days": retention_days
    })
