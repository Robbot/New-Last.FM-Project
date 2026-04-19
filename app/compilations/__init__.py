from flask import Blueprint
compilations_bp = Blueprint("compilations", __name__)
from . import routes  # noqa
