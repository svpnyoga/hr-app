"""Leave module: apply/approve/cancel leave requests, leave balances and a
simple month calendar (approved leave + holidays).

Tables owned: leave_requests, leave_balances (read-only: leave_types, holidays).
"""
import os
import calendar as calendar_mod
from datetime import date, datetime, timedelta

from flask import Blueprint, g, request, redirect, url_for, render_template, flash
from werkzeug.utils import secure_filename

import config
import db
import audit
import notify
import helpers
from auth import permission_required, has_permission

bp = Blueprint("leave", __name__)

LEAVE_UPLOAD_DIR = os.path.join(config.UPLOAD_DIR, "leave")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _leave_balance_rows(employee_id, year):
    return db.query(
        """SELECT lt.id as leave_type_id, lt.name as leave_type_name, lt.days_per_year,
                  COALESCE(lb.allocated, lt.days_per_year) as allocated,
                  COALESCE(lb.used, 0) as used,
                  COALESCE(lb.balance, lt.days_per_year) as balance
           FROM leave_types lt
           LEFT JOIN leave_balances lb ON lb.leave_type_id = lt.id AND lb.employee_id=? AND lb.year=?
           WHERE lt.is_active=1
           ORDER BY lt.name""",
        (employee_id, year),
    )


def _ensure_balance_row(employee_id, leave_type_id, year):
    row = db.query(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year), one=True,
    )
    if row:
        return row
    lt = db.query("SELECT days_per_year FROM leave_types WHERE id=?", (leave_type_id,), one=True)
    allocated = lt["days_per_year"] if lt else 0
    new_id = db.execute(
        "INSERT INTO leave_balances (employee_id, leave_type_id, year, allocated, used, balance) VALUES (?,?,?,?,0,?)",
        (employee_id, leave_type_id, year, allocated, allocated),
    )
    return db.query("SELECT * FROM leave_balances WHERE id=?", (new_id,), one=True)


def _daterange(from_date, to_date):
    d0 = datetime.fromisoformat(from_date).date()
    d1 = datetime.fromisoformat(to_date).date()
    cur = d0
    while cur <= d1:
        yield cur.isoformat()
        cur += timedelta(days=1)


# ----------------------------------------------------------------------------
# List
# ----------------------------------------------------------------------------

@bp.route("/requests")
@permission_required("leave.requests.view")
def requests_list():
    view_all = has_permission("leave.requests.view_all")
    status_filter = request.args.get("status", "").strip()
    leave_type_filter = request.args.get("leave_type_id", "").strip()
    employee_id_filter = request.args.get("employee_id", "").strip()

    where = []
    args = []
    if view_all:
        if employee_id_filter:
            where.append("lr.employee_id=?")
            args.append(employee_id_filter)
    else:
        where.append("lr.employee_id=?")
        args.append(g.employee["id"] if g.employee else -1)
    if status_filter:
        where.append("lr.status=?")
        args.append(status_filter)
    if leave_type_filter:
        where.append("lr.leave_type_id=?")
        args.append(leave_type_filter)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = db.query(
        f"""SELECT lr.*, e.first_name, e.last_name, e.employee_code, lt.name as leave_type_name
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
            JOIN leave_types lt ON lt.id = lr.leave_type_id
            {where_sql}
            ORDER BY lr.created_at DESC""",
        args,
    )

    if request.args.get("export") == "csv" and has_permission("leave.requests.export"):
        header = ["Request #", "Employee", "Leave Type", "From", "To", "Days", "Status"]
        out = [
            [r["request_number"], f"{r['first_name']} {r['last_name']}", r["leave_type_name"],
             r["from_date"], r["to_date"], r["days"], r["status"]]
            for r in rows
        ]
        audit.log("leave", "requests", None, "export", "Exported leave requests to CSV")
        return helpers.csv_response("leave_requests.csv", header, out)

    leave_types = db.query("SELECT id, name FROM leave_types WHERE is_active=1 ORDER BY name")
    balance_rows = None
    if not view_all and g.employee:
        balance_rows = _leave_balance_rows(g.employee["id"], date.today().year)

    return render_template(
        "leave/requests_list.html", rows=rows, view_all=view_all, status_filter=status_filter,
        leave_type_filter=leave_type_filter, leave_types=leave_types, balance_rows=balance_rows,
        current_year=date.today().year,
        can_export=has_permission("leave.requests.export"), can_create=has_permission("leave.requests.create"),
    )


# ----------------------------------------------------------------------------
# Apply
# ----------------------------------------------------------------------------

@bp.route("/requests/new", methods=("GET", "POST"))
@permission_required("leave.requests.create")
def request_new():
    if not g.employee:
        flash("No employee profile is linked to your account.", "error")
        return redirect(url_for("dashboard.index"))

    leave_types = db.query("SELECT * FROM leave_types WHERE is_active=1 ORDER BY name")
    balance_rows = _leave_balance_rows(g.employee["id"], date.today().year)

    if request.method == "POST":
        leave_type_id = request.form.get("leave_type_id", type=int)
        from_date = request.form.get("from_date", "").strip()
        to_date = request.form.get("to_date", "").strip()
        reason = request.form.get("reason", "").strip() or None

        error = None
        if not leave_type_id or not from_date or not to_date:
            error = "Leave type, from date and to date are required."
        else:
            try:
                d0 = datetime.fromisoformat(from_date).date()
                d1 = datetime.fromisoformat(to_date).date()
            except ValueError:
                error = "Invalid dates."
            else:
                if d1 < d0:
                    error = "To date cannot be before from date."

        if error:
            flash(error, "error")
            return render_template(
                "leave/request_new.html", leave_types=leave_types, balance_rows=balance_rows,
                form=request.form, current_year=date.today().year,
            )

        days = (d1 - d0).days + 1

        document_path = None
        doc = request.files.get("document")
        if doc and doc.filename:
            os.makedirs(LEAVE_UPLOAD_DIR, exist_ok=True)
            safe_name = secure_filename(doc.filename)
            stored_name = f"{g.employee['id']}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_name}"
            doc.save(os.path.join(LEAVE_UPLOAD_DIR, stored_name))
            document_path = f"leave/{stored_name}"

        request_number = db.next_sequence("LEAVE", "LV", 5)
        new_id = db.execute(
            """INSERT INTO leave_requests
               (request_number, employee_id, leave_type_id, from_date, to_date, days, reason,
                document_path, status)
               VALUES (?,?,?,?,?,?,?,?, 'Pending')""",
            (request_number, g.employee["id"], leave_type_id, from_date, to_date, days, reason, document_path),
        )
        audit.log("leave", "requests", new_id, "create",
                   f"Submitted leave request {request_number} ({from_date} to {to_date}, {days} day(s))")
        notify.notify_manager(
            g.employee["id"], "New leave request",
            f"{g.employee['first_name']} {g.employee['last_name']} applied for leave from {from_date} to {to_date}.",
            "info", url_for("leave.request_view", id=new_id),
        )
        flash(f"Leave request {request_number} submitted.", "success")
        return redirect(url_for("leave.request_view", id=new_id))

    return render_template(
        "leave/request_new.html", leave_types=leave_types, balance_rows=balance_rows, form=None,
        current_year=date.today().year,
    )


# ----------------------------------------------------------------------------
# View / detail
# ----------------------------------------------------------------------------

@bp.route("/requests/<int:id>")
@permission_required("leave.requests.view")
def request_view(id):
    row = db.query(
        """SELECT lr.*, e.first_name, e.last_name, e.employee_code, e.department_id,
                  lt.name as leave_type_name
           FROM leave_requests lr
           JOIN employees e ON e.id = lr.employee_id
           JOIN leave_types lt ON lt.id = lr.leave_type_id
           WHERE lr.id=?""",
        (id,), one=True,
    )
    if row is None:
        flash("Leave request not found.", "error")
        return redirect(url_for("leave.requests_list"))

    view_all = has_permission("leave.requests.view_all")
    is_owner = bool(g.employee) and row["employee_id"] == g.employee["id"]
    if not view_all and not is_owner:
        flash("You don't have permission to view this leave request.", "error")
        return redirect(url_for("leave.requests_list"))

    can_approve = has_permission("leave.requests.approve") and row["status"] == "Pending"
    can_cancel = row["status"] == "Pending" and (is_owner or has_permission("leave.requests.edit"))

    return render_template("leave/request_view.html", row=row, can_approve=can_approve, can_cancel=can_cancel)


# ----------------------------------------------------------------------------
# Status transitions: Approve / Reject / Cancel
# ----------------------------------------------------------------------------

@bp.route("/requests/<int:id>/status", methods=("POST",))
@permission_required("leave.requests.view")
def request_status(id):
    row = db.query("SELECT * FROM leave_requests WHERE id=?", (id,), one=True)
    if row is None:
        flash("Leave request not found.", "error")
        return redirect(url_for("leave.requests_list"))
    if row["status"] != "Pending":
        flash("This request has already been processed.", "error")
        return redirect(url_for("leave.request_view", id=id))

    new_status = request.form.get("status", "").strip()
    is_owner = bool(g.employee) and row["employee_id"] == g.employee["id"]

    if new_status in ("Approved", "Rejected"):
        if not has_permission("leave.requests.approve"):
            flash("You don't have permission to do this (leave.requests.approve).", "error")
            return redirect(url_for("leave.request_view", id=id))
    elif new_status == "Cancelled":
        if not (is_owner or has_permission("leave.requests.edit")):
            flash("You don't have permission to cancel this request.", "error")
            return redirect(url_for("leave.request_view", id=id))
    else:
        flash("Invalid status.", "error")
        return redirect(url_for("leave.request_view", id=id))

    now = helpers.now_iso()
    db.execute(
        "UPDATE leave_requests SET status=?, approver_id=?, approved_at=? WHERE id=?",
        (new_status, g.user["id"] if new_status != "Cancelled" else row["approver_id"], now, id),
    )

    if new_status == "Approved":
        year = int(row["from_date"][:4])
        bal = _ensure_balance_row(row["employee_id"], row["leave_type_id"], year)
        new_used = (bal["used"] or 0) + row["days"]
        new_balance = (bal["allocated"] or 0) - new_used
        db.execute(
            "UPDATE leave_balances SET used=?, balance=? WHERE id=?",
            (new_used, new_balance, bal["id"]),
        )
        for d in _daterange(row["from_date"], row["to_date"]):
            existing = db.query(
                "SELECT id FROM attendance WHERE employee_id=? AND date=?", (row["employee_id"], d), one=True
            )
            if existing:
                continue
            db.execute(
                """INSERT INTO attendance (employee_id, date, status, source) VALUES (?,?, 'On Leave', 'Leave')""",
                (row["employee_id"], d),
            )

    audit.log("leave", "requests", id, "status_change", f"Leave request #{id} marked {new_status}")

    requester = db.query("SELECT id FROM users WHERE employee_id=?", (row["employee_id"],), one=True)
    if requester:
        ntype = "success" if new_status == "Approved" else ("warning" if new_status == "Rejected" else "info")
        notify.notify_user(
            requester["id"], f"Leave request {new_status.lower()}",
            f"Your leave request ({row['from_date']} to {row['to_date']}) was {new_status.lower()}.",
            ntype, url_for("leave.request_view", id=id),
        )

    flash(f"Leave request {new_status.lower()}.", "success")
    return redirect(url_for("leave.request_view", id=id))


# ----------------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------------

@bp.route("/calendar")
@permission_required("leave.requests.view")
def calendar():
    today = date.today()
    month = request.args.get("month", type=int) or today.month
    year = request.args.get("year", type=int) or today.year
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    num_days = calendar_mod.monthrange(year, month)[1]
    month_prefix = f"{year:04d}-{month:02d}-"
    first_day = f"{month_prefix}01"
    last_day = f"{month_prefix}{num_days:02d}"

    view_all = has_permission("leave.requests.view_all")
    where = ["lr.status='Approved'", "lr.from_date<=?", "lr.to_date>=?"]
    args = [last_day, first_day]
    if not view_all:
        where.append("lr.employee_id=?")
        args.append(g.employee["id"] if g.employee else -1)
    where_sql = " AND ".join(where)

    leave_rows = db.query(
        f"""SELECT lr.from_date, lr.to_date, e.first_name, e.last_name, lt.name as leave_type_name
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
            JOIN leave_types lt ON lt.id = lr.leave_type_id
            WHERE {where_sql}""",
        args,
    )
    holiday_rows = db.query(
        "SELECT * FROM holidays WHERE holiday_date >= ? AND holiday_date <= ? ORDER BY holiday_date",
        (first_day, last_day),
    )

    days_info = {d: {"leaves": [], "holiday": None} for d in range(1, num_days + 1)}
    for h in holiday_rows:
        day_num = int(h["holiday_date"][8:10])
        if day_num in days_info:
            days_info[day_num]["holiday"] = h["name"]
    for lr in leave_rows:
        for d in _daterange(max(lr["from_date"], first_day), min(lr["to_date"], last_day)):
            day_num = int(d[8:10])
            if day_num in days_info:
                days_info[day_num]["leaves"].append(f"{lr['first_name']} {lr['last_name']} ({lr['leave_type_name']})")

    first_weekday = calendar_mod.monthrange(year, month)[0]  # 0=Monday
    lead_blanks = (first_weekday + 1) % 7  # shift so week starts Sunday
    weeks = []
    week = [None] * lead_blanks
    for day_num in range(1, num_days + 1):
        week.append(day_num)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        week += [None] * (7 - len(week))
        weeks.append(week)

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    return render_template(
        "leave/calendar.html", weeks=weeks, days_info=days_info, month=month, year=year,
        month_name=calendar_mod.month_name[month], today=today,
        prev_month=prev_month, prev_year=prev_year, next_month=next_month, next_year=next_year,
    )
