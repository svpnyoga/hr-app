import functools
import secrets
from datetime import datetime
from flask import Blueprint, g, session, redirect, url_for, request, render_template, flash
from werkzeug.security import generate_password_hash, check_password_hash

import db

bp = Blueprint("auth", __name__)


def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        g.permissions = set()
        g.employee = None
        return
    user = db.query(
        """SELECT u.*, r.name as role_name FROM users u
           JOIN roles r ON r.id = u.role_id WHERE u.id=? AND u.is_active=1""",
        (user_id,), one=True,
    )
    g.user = user
    if user is None:
        g.permissions = set()
        g.employee = None
        return
    if user["role_name"] == "Super Admin":
        g.permissions = {"*"}
    else:
        rows = db.query(
            """SELECT p.code FROM role_permissions rp
               JOIN permissions p ON p.id = rp.permission_id
               WHERE rp.role_id=?""",
            (user["role_id"],),
        )
        g.permissions = {r["code"] for r in rows}
    g.employee = None
    if user["employee_id"]:
        g.employee = db.query("SELECT * FROM employees WHERE id=?", (user["employee_id"],), one=True)


def has_permission(code):
    if g.get("user") is None:
        return False
    perms = g.get("permissions", set())
    if "*" in perms:
        return True
    return code in perms


def can_view_all(module, entity):
    return has_permission(f"{module}.{entity}.view_all")


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


def permission_required(code):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(**kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if not has_permission(code):
                flash(f"You don't have permission to do this ({code}).", "error")
                return redirect(url_for("dashboard.index"))
            return view(**kwargs)
        return wrapped
    return decorator


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.get("user"):
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.query(
            "SELECT * FROM users WHERE (username=? OR email=?) AND is_active=1",
            (identifier, identifier), one=True,
        )
        error = None
        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Invalid username or password."
        if error is None:
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            db.execute("UPDATE users SET last_login_at=? WHERE id=?", (datetime.utcnow().isoformat(), user["id"]))
            nxt = request.args.get("next") or url_for("dashboard.index")
            return redirect(nxt)
        flash(error, "error")
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/forgot-password", methods=("GET", "POST"))
def forgot_password():
    token_preview = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        user = db.query("SELECT * FROM users WHERE email=?", (email,), one=True)
        if user:
            token = secrets.token_urlsafe(24)
            session[f"reset_{user['id']}"] = token
            token_preview = url_for("auth.reset_password", token=token, uid=user["id"], _external=False)
        flash(
            "If that email exists in our system, a password reset link has been generated. "
            "(This demo has no outbound email, so the link is shown below.)",
            "info",
        )
    return render_template("auth/forgot_password.html", token_preview=token_preview)


@bp.route("/reset-password/<token>", methods=("GET", "POST"))
def reset_password(token):
    uid = request.args.get("uid", type=int)
    user = db.query("SELECT * FROM users WHERE id=?", (uid,), one=True) if uid else None
    if user is None or session.get(f"reset_{uid}") != token:
        flash("Invalid or expired reset link.", "error")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
        else:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(password), user["id"]))
            session.pop(f"reset_{uid}", None)
            flash("Password updated. Please log in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", token=token)


@bp.route("/account/change-password", methods=("GET", "POST"))
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        if not check_password_hash(g.user["password_hash"], current):
            flash("Current password is incorrect.", "error")
        elif len(new) < 6:
            flash("New password must be at least 6 characters.", "error")
        else:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), g.user["id"]))
            flash("Password changed successfully.", "success")
            return redirect(url_for("dashboard.index"))
    return render_template("auth/change_password.html")
