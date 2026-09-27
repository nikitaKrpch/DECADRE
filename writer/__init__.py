"""Assistant de rédaction: the journalist-facing editor, as a Flask blueprint.

Registered in app.py. All of its code, templates and static files live in writer/.
"""
from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

from .analysis import find_issues
from . import llm

bp = Blueprint(
    "writer",
    __name__,
    url_prefix="/rediger",
    template_folder="templates",
    static_folder="static",
)


# Same check as login_required in app.py (importing it from there would be circular).
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@bp.route("/")
@login_required
def editor():
    return render_template("writer/editor.html")


MAX_CHARS = 20000


@bp.route("/api/analyse", methods=["POST"])
def analyse_api():
    # Called frequently while writing: answer with JSON errors, not a login redirect.
    if not session.get("authenticated"):
        return jsonify(error="Session expirée : reconnectez-vous."), 401
    text = (request.get_json(silent=True) or {}).get("text", "")
    if not isinstance(text, str):
        return jsonify(error="Texte invalide."), 400
    if len(text) > MAX_CHARS:
        return jsonify(error=f"Texte trop long (max. {MAX_CHARS} caractères)."), 413
    if not text.strip():
        return jsonify(issues=[])
    try:
        return jsonify(issues=find_issues(text))
    except Exception as e:
        # Never log the article text, only what went wrong.
        current_app.logger.error(f"rule analysis failed: {type(e).__name__}: {e}")
        return jsonify(error="L'analyse des règles n'a pas pu aboutir."), 502


@bp.route("/api/deep-check", methods=["POST"])
def deep_check_api():
    # Called by fetch(): answer with JSON errors, not the login page redirect.
    if not session.get("authenticated"):
        return jsonify(error="Session expirée : reconnectez-vous."), 401
    text = (request.get_json(silent=True) or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Texte vide."), 400
    if len(text) > MAX_CHARS:
        return jsonify(error=f"Texte trop long (max. {MAX_CHARS} caractères)."), 413
    try:
        return jsonify(llm.deep_check(text))
    except Exception as e:
        # Never log the article text, only what went wrong.
        current_app.logger.error(f"deep check failed: {type(e).__name__}: {e}")
        return jsonify(error="L'analyse IA n'a pas pu aboutir."), 502
