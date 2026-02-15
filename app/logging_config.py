"""
Logging configuration for the Last.fm scrobble statistics application.

Provides structured logging with:
- File logging for persistence
- Console logging for development
- Request logging middleware
- Different log levels for different environments
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler


# Log directory
BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


def setup_logging(app=None, level=logging.INFO):
    """
    Configure logging for the application.

    Args:
        app: Flask app instance (optional)
        level: Logging level (default: INFO)

    Returns:
        Logger instance for the application
    """
    # Create formatters
    detailed_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s (%(funcName)s:%(lineno)d): %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )

    # File handler - detailed logs with rotation
    log_file = LOG_DIR / f"app_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)

    # Console handler - simpler format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(simple_formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()  # Remove any existing handlers

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Configure Flask app logger if provided
    if app:
        app.logger.setLevel(logging.DEBUG)
        app.logger.handlers.clear()
        app.logger.propagate = False
        app.logger.addHandler(file_handler)
        app.logger.addHandler(console_handler)

    # Configure urllib3 to reduce noise from requests
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    return logging.getLogger(__name__)


def setup_request_logging(app):
    """
    Add request logging middleware to the Flask app.

    Logs each request with method, path, status, and response time.
    """
    @app.before_request
    def log_request_start():
        import time
        import flask
        flask.g.start_time = time.time()

    @app.after_request
    def log_request_end(response):
        import time
        import flask
        from flask import request

        if hasattr(flask.g, 'start_time'):
            duration = time.time() - flask.g.start_time
        else:
            duration = 0

        # Skip logging for static files and health checks
        if request.path.startswith('/static') or request.path == '/health':
            return response

        app.logger.info(
            f'{request.method} {request.path} -> {response.status_code} '
            f'({duration*1000:.0f}ms)'
        )

        return response


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
