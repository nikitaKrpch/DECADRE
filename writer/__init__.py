"""Assistant de rédaction: the journalist-facing editor, as a Flask blueprint.

Registered in app.py. All of its code, templates and static files live in writer/.
"""
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for

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
