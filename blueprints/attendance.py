"""Attendance module: daily manager/HR roster, self check-in/out, monthly
self-service view, and attendance regularization workflow.

Tables owned: attendance, attendance_regularization (read-only: shifts,
employee_shifts).
"""
from datetime import datetime, date, timedelta

from flask import Blueprint, g, request, redirect, url_for, render_template, flash

import db
import audit
import notify
import helpers
from auth import permission_required, has_permission, login_required

bp = Blueprint("attendance", __name__)

ATTENDANCE_STATUSES = ["Present", "Absent", "Half Day", "On Leave", "Week Off", "Holiday"]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _parse_hm(value):
    """Parse an 'HH:MM' string into a naive datetime.time-bearing datetime
    (fixed arbitrary date so we can do arithmetic). Returns None on failure."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:5], "%H:%M")
    except ValueError:
        return None


def _employee_shift(employee_id, date_str):
    """Best-effort lookup of the shift effective for an employee on a date."""
    return db.query(
        """SELECT s.* FROM employee_shifts es JOIN shifts s ON s.id = es.shift_id
           WHERE es.employee_id=? AND es.effective_from <= ?
           ORDER BY es.effective_from DESC LIMIT 1""",
        (employee_id, date_str), one=True,
    )


def compute_metrics(employee_id, date_str, check_in, check_out):
    """Best-effort late_minutes / overtime_minutes / work_hours calculation
    from check_in/check_out vs the employee's shift (if any)."""
    late_minutes = 0
    overtime_minutes = 0
    work_hours = 0.0
    shift = _employee_shift(employee_id, date_str)

    ci = _parse_hm(check_in)
    co = _parse_hm(check_out)

    if ci and co:
        delta_min = (co - ci).total_seconds() / 60
        if delta_min < 0:
            delta_min += 24 * 60  # crossed midnight, best-effort
        break_min = shift["break_minutes"] if shift else 0
        work_hours = round(max(0, delta_min - break_min) / 60, 2)

    if shift and ci:
        shift_start = _parse_hm(shift["start_time"])
        if shift_start:
            diff = (ci - shift_start).total_seconds() / 60
            late_minutes = int(max(0, diff - (shift["grace_minutes"] or 0)))

    if shift and co:
        shift_end = _parse_hm(shift["end_time"])
        if shift_end:
            diff = (co - shift_end).total_seconds() / 60
            overtime_minutes = int(max(0, diff))

    return late_minutes, overtime_minutes, work_hours


def _upsert_attendance(employee_id, date_str, status, check_in=None, check_out=None,
                        source="Manual", shift_id=None):
    existing = db.query(
        "SELECT * FROM attendance WHERE employee_id=? AND date=?", (employee_id, date_str), one=True
    )
    ci = check_in if check_in else (existing["check_in"] if existing else None)
    co = check_out if check_out else (existing["check_out"] if existing else None)
    late_minutes, overtime_minutes, work_hours = compute_metrics(employee_id, date_str, ci, co)
    if shift_id is None and existing:
        shift_id = existing["shift_id"]
    if shift_id is None:
        shift = _employee_shift(employee_id, date_str)
        shift_id = shift["id"] if shift else None

    if existing:
        db.execute(
            """UPDATE attendance SET status=?, check_in=?, check_out=?, shift_id=?,
               late_minutes=?, overtime_minutes=?, work_hours=?, source=? WHERE id=?""",
            (status, ci, co, shift_id, late_minutes, overtime_minutes, work_hours, source, existing["id"]),
        )
        return existing["id"], False
    else:
        new_id = db.execute(
            """INSERT INTO attendance (employee_id, date, shift_id, check_in, check_out, status,
               late_minutes, overtime_minutes, work_hours, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (employee_id, date_str, shift_id, ci, co, status, late_minutes, overtime_minutes, work_hours, source),
        )
        return new_id, True


def _safe_redirect(target, fallback):
    if target and target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(fallback)


# ----------------------------------------------------------------------------
# Daily roster (manager/HR view)
# ----------------------------------------------------------------------------

@bp.route("/daily")
@permission_required("attendance.attendance.view")
def daily():
    if not has_permission("attendance.attendance.view_all"):
        return redirect(url_for("attendance.my_attendance"))

    date_str = request.args.get("date") or helpers.today_iso()
    department_id = request.args.get("department_id", "").strip()
    status_filter = request.args.get("status", "").strip()

    where = ["e.is_deleted=0"]
    args = [date_str]
    if department_id:
        where.append("e.department_id=?")
        args.append(department_id)
    if status_filter:
        if status_filter == "Not Marked":
            where.append("a.id IS NULL")
        else:
            where.append("a.status=?")
            args.append(status_filter)
    where_sql = " AND ".join(where)

    rows = db.query(
        f"""SELECT e.id as employee_id, e.employee_code, e.first_name, e.last_name, e.photo_path,
                   d.name as department_name, a.id as att_id, a.check_in, a.check_out, a.status,
                   a.late_minutes, a.overtime_minutes, a.work_hours
            FROM employees e
            LEFT JOIN departments d ON d.id = e.department_id
            LEFT JOIN attendance a ON a.employee_id = e.id AND a.date = ?
            WHERE {where_sql}
            ORDER BY e.first_name, e.last_name""",
        args,
    )

    kpi_args = [date_str]
    kpi_where = "e.is_deleted=0"
    if department_id:
        kpi_where += " AND e.department_id=?"
        kpi_args.append(department_id)
    kpi_rows = db.query(
        f"""SELECT COALESCE(a.status, 'Not Marked') as status, COUNT(*) as c
            FROM employees e
            LEFT JOIN attendance a ON a.employee_id = e.id AND a.date = ?
            WHERE {kpi_where}
            GROUP BY COALESCE(a.status, 'Not Marked')""",
        kpi_args,
    )
    kpi = {r["status"]: r["c"] for r in kpi_rows}
    late_count = db.query(
        f"""SELECT COUNT(*) as c FROM attendance a JOIN employees e ON e.id=a.employee_id
            WHERE a.date=? AND a.late_minutes > 0 AND {kpi_where}""",
        kpi_args,
    )[0]["c"]

    kpi_summary = {
        "present": kpi.get("Present", 0),
        "absent": kpi.get("Absent", 0),
        "late": late_count,
        "on_leave": kpi.get("On Leave", 0),
        "not_marked": kpi.get("Not Marked", 0),
    }

    departments = db.query("SELECT id, name FROM departments WHERE is_active=1 ORDER BY name")

    if request.args.get("export") == "csv" and has_permission("attendance.attendance.export"):
        header = ["Employee Code", "Name", "Department", "Status", "Check In", "Check Out", "Late (min)", "Overtime (min)", "Work Hours"]
        out = [
            [r["employee_code"], f"{r['first_name']} {r['last_name']}", r["department_name"] or "-",
             r["status"] or "Not Marked", r["check_in"] or "", r["check_out"] or "",
             r["late_minutes"] or 0, r["overtime_minutes"] or 0, r["work_hours"] or 0]
            for r in rows
        ]
        audit.log("attendance", "attendance", None, "export", f"Exported daily attendance for {date_str}")
        return helpers.csv_response(f"attendance_{date_str}.csv", header, out)

    return render_template(
        "attendance/daily.html", rows=rows, date_str=date_str, departments=departments,
        department_id=department_id, status_filter=status_filter, statuses=ATTENDANCE_STATUSES,
        kpi=kpi_summary, can_edit=has_permission("attendance.attendance.edit"),
        can_export=has_permission("attendance.attendance.export"),
    )


@bp.route("/mark", methods=("POST",))
@permission_required("attendance.attendance.edit")
def mark():
    employee_id = request.form.get("employee_id", type=int)
    date_str = request.form.get("date", "").strip()
    status = request.form.get("status", "Present").strip() or "Present"
    check_in = request.form.get("check_in", "").strip() or None
    check_out = request.form.get("check_out", "").strip() or None
    next_url = request.form.get("next")

    if not employee_id or not date_str:
        flash("Employee and date are required to mark attendance.", "error")
        return _safe_redirect(next_url, url_for("attendance.daily"))

    att_id, created = _upsert_attendance(employee_id, date_str, status, check_in, check_out, source="Manual")
    emp = db.query("SELECT first_name, last_name FROM employees WHERE id=?", (employee_id,), one=True)
    emp_name = f"{emp['first_name']} {emp['last_name']}" if emp else f"#{employee_id}"
    audit.log("attendance", "attendance", att_id, "create" if created else "update",
               f"Marked {emp_name} as {status} on {date_str}")
    flash(f"Attendance updated for {emp_name} on {date_str}.", "success")
    return _safe_redirect(next_url, url_for("attendance.daily", date=date_str))


# ----------------------------------------------------------------------------
# Self-service: my attendance
# ----------------------------------------------------------------------------

@bp.route("/my")
@permission_required("attendance.attendance.view")
def my_attendance():
    if not g.employee:
        flash("No employee profile is linked to your account.", "error")
        return redirect(url_for("dashboard.index"))

    today = date.today()
    month = request.args.get("month", type=int) or today.month
    year = request.args.get("year", type=int) or today.year
    month_prefix = f"{year:04d}-{month:02d}-"

    rows = db.query(
        "SELECT * FROM attendance WHERE employee_id=? AND date LIKE ? ORDER BY date",
        (g.employee["id"], f"{month_prefix}%"),
    )

    summary = {"present": 0, "absent": 0, "leave": 0, "half_day": 0}
    for r in rows:
        s = (r["status"] or "").lower()
        if s == "present":
            summary["present"] += 1
        elif s == "absent":
            summary["absent"] += 1
        elif s == "on leave":
            summary["leave"] += 1
        elif s == "half day":
            summary["half_day"] += 1

    last14 = db.query(
        "SELECT date, work_hours FROM attendance WHERE employee_id=? ORDER BY date DESC LIMIT 14",
        (g.employee["id"],),
    )
    chart_data = [
        {"label": r["date"][5:], "value": round(r["work_hours"] or 0, 2)} for r in reversed(last14)
    ]

    today_row = db.query(
        "SELECT * FROM attendance WHERE employee_id=? AND date=?", (g.employee["id"], helpers.today_iso()), one=True
    )

    return render_template(
        "attendance/my_attendance.html", rows=rows, month=month, year=year, summary=summary,
        chart_data=chart_data, today_row=today_row, today_iso=helpers.today_iso(),
    )


@bp.route("/my/check-in", methods=("POST",))
@permission_required("attendance.attendance.create")
def check_in():
    if not g.employee:
        flash("No employee profile is linked to your account.", "error")
        return redirect(url_for("dashboard.index"))
    today_str = helpers.today_iso()
    now_time = datetime.now().strftime("%H:%M")
    existing = db.query(
        "SELECT * FROM attendance WHERE employee_id=? AND date=?", (g.employee["id"], today_str), one=True
    )
    if existing and existing["check_in"]:
        flash("You have already checked in today.", "error")
        return redirect(url_for("attendance.my_attendance"))
    att_id, created = _upsert_attendance(g.employee["id"], today_str, "Present", check_in=now_time, source="Self")
    audit.log("attendance", "attendance", att_id, "create" if created else "update",
               f"Self check-in at {now_time} on {today_str}")
    flash(f"Checked in at {now_time}.", "success")
    return redirect(url_for("attendance.my_attendance"))


@bp.route("/my/check-out", methods=("POST",))
@permission_required("attendance.attendance.create")
def check_out():
    if not g.employee:
        flash("No employee profile is linked to your account.", "error")
        return redirect(url_for("dashboard.index"))
    today_str = helpers.today_iso()
    now_time = datetime.now().strftime("%H:%M")
    existing = db.query(
        "SELECT * FROM attendance WHERE employee_id=? AND date=?", (g.employee["id"], today_str), one=True
    )
    if not existing or not existing["check_in"]:
        flash("Please check in before checking out.", "error")
        return redirect(url_for("attendance.my_attendance"))
    att_id, created = _upsert_attendance(
        g.employee["id"], today_str, existing["status"] or "Present", check_out=now_time, source="Self"
    )
    audit.log("attendance", "attendance", att_id, "update", f"Self check-out at {now_time} on {today_str}")
    flash(f"Checked out at {now_time}.", "success")
    return redirect(url_for("attendance.my_attendance"))


# ----------------------------------------------------------------------------
# Regularization
# ----------------------------------------------------------------------------

@bp.route("/regularization")
@permission_required("attendance.regularization.view")
def regularization_list():
    view_all = has_permission("attendance.regularization.view_all")
    status_filter = request.args.get("status", "").strip()

    where = []
    args = []
    if not view_all:
        where.append("ar.employee_id=?")
        args.append(g.employee["id"] if g.employee else -1)
    if status_filter:
        where.append("ar.status=?")
        args.append(status_filter)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = db.query(
        f"""SELECT ar.*, e.first_name, e.last_name, e.employee_code
            FROM attendance_regularization ar JOIN employees e ON e.id = ar.employee_id
            {where_sql}
            ORDER BY ar.created_at DESC""",
        args,
    )
    return render_template(
        "attendance/regularization_list.html", rows=rows, view_all=view_all, status_filter=status_filter,
        can_approve=has_permission("attendance.regularization.approve"),
    )


@bp.route("/regularization/new", methods=("GET", "POST"))
@permission_required("attendance.regularization.create")
def regularization_new():
    if not g.employee:
        flash("No employee profile is linked to your account.", "error")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        attendance_date = request.form.get("attendance_date", "").strip()
        requested_check_in = request.form.get("requested_check_in", "").strip() or None
        requested_check_out = request.form.get("requested_check_out", "").strip() or None
        reason = request.form.get("reason", "").strip()

        if not attendance_date or not reason:
            flash("Attendance date and reason are required.", "error")
            return render_template("attendance/regularization_new.html", today_iso=helpers.today_iso())

        new_id = db.execute(
            """INSERT INTO attendance_regularization
               (employee_id, attendance_date, requested_check_in, requested_check_out, reason, status)
               VALUES (?,?,?,?,?, 'Pending')""",
            (g.employee["id"], attendance_date, requested_check_in, requested_check_out, reason),
        )
        audit.log("attendance", "regularization", new_id, "create",
                   f"Submitted regularization request for {attendance_date}")
        notify.notify_manager(
            g.employee["id"], "Attendance regularization request",
            f"{g.employee['first_name']} {g.employee['last_name']} requested a correction for {attendance_date}.",
            "info", url_for("attendance.regularization_list"),
        )
        flash("Regularization request submitted.", "success")
        return redirect(url_for("attendance.regularization_list"))

    return render_template("attendance/regularization_new.html", today_iso=helpers.today_iso())


@bp.route("/regularization/<int:id>/status", methods=("POST",))
@permission_required("attendance.regularization.approve")
def regularization_status(id):
    row = db.query("SELECT * FROM attendance_regularization WHERE id=?", (id,), one=True)
    if row is None:
        flash("Regularization request not found.", "error")
        return redirect(url_for("attendance.regularization_list"))
    if row["status"] != "Pending":
        flash("This request has already been processed.", "error")
        return redirect(url_for("attendance.regularization_list"))

    new_status = request.form.get("status", "").strip()
    if new_status not in ("Approved", "Rejected"):
        flash("Invalid status.", "error")
        return redirect(url_for("attendance.regularization_list"))

    now = helpers.now_iso()
    db.execute(
        "UPDATE attendance_regularization SET status=?, approver_id=?, approved_at=? WHERE id=?",
        (new_status, g.user["id"], now, id),
    )

    if new_status == "Approved":
        _upsert_attendance(
            row["employee_id"], row["attendance_date"], "Present",
            check_in=row["requested_check_in"], check_out=row["requested_check_out"], source="Regularization",
        )

    audit.log("attendance", "regularization", id, "status_change",
               f"Regularization request #{id} marked {new_status}")

    requester = db.query("SELECT id FROM users WHERE employee_id=?", (row["employee_id"],), one=True)
    if requester:
        notify.notify_user(
            requester["id"], f"Attendance regularization {new_status.lower()}",
            f"Your regularization request for {row['attendance_date']} was {new_status.lower()}.",
            "success" if new_status == "Approved" else "warning",
            url_for("attendance.regularization_list"),
        )

    flash(f"Request {new_status.lower()}.", "success")
    return redirect(url_for("attendance.regularization_list"))
