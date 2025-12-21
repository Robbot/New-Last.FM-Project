from flask import Blueprint
scrobbles_bp = Blueprint("scrobbles", __name__)
from . import routes  # noqa
