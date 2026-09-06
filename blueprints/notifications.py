"""Notifications module: the full notification list page and mark-read
actions for the logged-in user.

Tables owned: notifications (shared with notify.py, which does the
inserting from every other module).
"""
from flask import Blueprint, g, request, redirect, url_for, render_template, flash

import db
from auth import login_required

bp = Blueprint("notifications", __name__)

PAGE_SIZE = 50


@bp.route("/")
@login_required
def index():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    offset = (page - 1) * PAGE_SIZE

    total = db.query(
        "SELECT COUNT(*) c FROM notifications WHERE user_id=?", (g.user["id"],), one=True
    )["c"]
    rows = db.query(
        """SELECT * FROM notifications WHERE user_id=?
           ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""",
        (g.user["id"], PAGE_SIZE, offset),
    )
    has_more = offset + len(rows) < total

    return render_template(
        "notifications/index.html",
        rows=rows,
        page=page,
        total=total,
        has_more=has_more,
        page_size=PAGE_SIZE,
    )


@bp.route("/<int:id>/read", methods=("POST",))
@login_required
def mark_read(id):
    row = db.query(
        "SELECT * FROM notifications WHERE id=? AND user_id=?", (id, g.user["id"]), one=True
    )
    if row is None:
        flash("Notification not found.", "error")
    else:
        db.execute("UPDATE notifications SET is_read=1 WHERE id=?", (id,))
    return redirect(request.referrer or url_for("notifications.index"))


@bp.route("/read-all", methods=("POST",))
@login_required
def mark_all_read():
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0", (g.user["id"],))
    flash("All notifications marked as read.", "success")
    return redirect(request.referrer or url_for("notifications.index"))
