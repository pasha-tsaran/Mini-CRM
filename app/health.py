from flask import Blueprint, jsonify
from sqlalchemy import text

from database.session import get_session


blueprint = Blueprint("health", __name__)


@blueprint.get("/healthz")
def health():
    get_session().execute(text("SELECT 1"))
    return jsonify(status="ok")
