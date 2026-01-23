from flask import Blueprint
trackgaps_bp = Blueprint("trackgaps", __name__)
from . import routes  # noqa
