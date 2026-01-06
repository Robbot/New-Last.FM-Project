from flask import Blueprint

daterange_bp = Blueprint("daterange", __name__, url_prefix="/api/daterange")

from . import routes  # noqa

