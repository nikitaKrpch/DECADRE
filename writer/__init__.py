"""Assistant de rédaction: the journalist-facing editor, as a Flask blueprint.

Registered in app.py. All of its code, templates and static files live in writer/.
"""
from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

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


@bp.route("/api/deep-check", methods=["POST"])
def deep_check_api():
    # Called by fetch(): answer with JSON errors, not the login page redirect.
    if not session.get("authenticated"):
        return jsonify(error="Session expirée : reconnectez-vous."), 401
    body = request.get_json(silent=True) or {}
    text = body.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Texte vide."), 400
    if len(text) > MAX_CHARS:
        return jsonify(error=f"Texte trop long (max. {MAX_CHARS} caractères)."), 413
    # Passages the rules already flag. Only short strings that really are in the text are kept,
    # so this can't be used to put arbitrary instructions in the prompt.
    already = body.get("already", [])
    if not isinstance(already, list):
        already = []
    already = [a for a in already if isinstance(a, str) and 0 < len(a) <= 100 and a in text][:60]
    try:
        return jsonify(llm.deep_check(text, already))
    except Exception as e:
        # Never log the article text, only what went wrong.
        current_app.logger.error(f"deep check failed: {type(e).__name__}: {e}")
        return jsonify(error="L'analyse IA n'a pas pu aboutir."), 502
