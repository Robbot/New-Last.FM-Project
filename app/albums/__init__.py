from flask import Blueprint
albums_bp = Blueprint("albums", __name__)
from . import routes  # noqa
