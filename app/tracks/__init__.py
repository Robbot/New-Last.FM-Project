from flask import Blueprint
tracks_bp = Blueprint("tracks", __name__)
from . import routes  # noqa
