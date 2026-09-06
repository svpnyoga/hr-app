"""Dashboard module: adaptive KPI home page and the unified approval queue.

Read-only across almost every table in the schema (no tables owned here).
Renders gracefully for any role/permission combination -- every section is
individually gated behind a permission check and simply omitted when the
user doesn't hold it.
"""
from datetime import date

from flask import Blueprint, render_template

import db
from auth import login_required, has_permission

bp = Blueprint("dashboard", __name__)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _count(sql, args=()):
    row = db.query(sql, args, one=True)
    return row["c"] if row else 0


def pending_approvals_count():
    """Count of everything awaiting action across the three approval-bearing
    entities, restricted to the ones the current user may approve."""
    total = 0
    if has_permission("leave.requests.approve"):
        total += _count("SELECT COUNT(*) c FROM leave_requests WHERE status='Pending'")
    if has_permission("attendance.regularization.approve"):
        total += _count("SELECT COUNT(*) c FROM attendance_regularization WHERE status='Pending'")
    if has_permission("claims.claims.approve"):
        total += _count(
            "SELECT COUNT(*) c FROM expense_claims WHERE status IN ('Submitted','Manager Approved','Finance Verified')"
        )
    return total


def _upcoming_by_month_day(rows, field, within_days=14):
    """Given rows exposing a partial-date column `field` (dob or
    date_of_joining), compute each row's next anniversary/birthday occurrence
    and keep only those landing within `within_days` days from today.
    Returns a list of dicts: {row, occurs_on (date), days_until} sorted by
    days_until ascending. Computed in Python since SQLite has no clean way to
    compare just month/day across a year boundary."""
    today = date.today()
    out = []
    for r in rows:
        raw = r[field]
        if not raw:
            continue
        try:
            d = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue

        def _occurrence(year):
            try:
                return date(year, d.month, d.day)
            except ValueError:
                # Feb 29 in a non-leap year -> observe on Feb 28
                return date(year, 2, 28)

        occ = _occurrence(today.year)
        if occ < today:
            occ = _occurrence(today.year + 1)
        days_until = (occ - today).days
        if 0 <= days_until <= within_days:
            out.append({"row": r, "occurs_on": occ, "days_until": days_until, "dob": d})
    out.sort(key=lambda x: x["days_until"])
    return out


# ----------------------------------------------------------------------------
# Home
# ----------------------------------------------------------------------------

@bp.route("/")
@login_required
def index():
    today_iso = date.today().isoformat()

    # ---- Employee / attendance KPI group (gated behind view_all) ----
    show_workforce_kpis = has_permission("employees.employees.view_all")
    total_employees = present_today = absent_today = on_leave_today = new_joiners = None
    attendance_chart_data = []
    if show_workforce_kpis:
        total_employees = _count(
            "SELECT COUNT(*) c FROM employees WHERE is_deleted=0 AND employment_status='Active'"
        )
        att_rows = db.query(
            "SELECT status, COUNT(*) c FROM attendance WHERE date=? GROUP BY status", (today_iso,)
        )
        att_by_status = {r["status"]: r["c"] for r in att_rows}
        present_today = att_by_status.get("Present", 0)
        absent_today = att_by_status.get("Absent", 0)
        on_leave_today = att_by_status.get("On Leave", 0)
        attendance_chart_data = [{"label": r["status"], "value": r["c"]} for r in att_rows]

        first_of_month = date.today().replace(day=1).isoformat()
        new_joiners = _count(
            "SELECT COUNT(*) c FROM employees WHERE is_deleted=0 AND date_of_joining >= ? AND date_of_joining <= ?",
            (first_of_month, today_iso),
        )

    # ---- Pending approvals KPI (gated behind holding at least one approve perm) ----
    show_approvals_kpi = (
        has_permission("leave.requests.approve")
        or has_permission("attendance.regularization.approve")
        or has_permission("claims.claims.approve")
    )
    approvals_count = pending_approvals_count() if show_approvals_kpi else None

    # ---- Recruitment KPI ----
    show_recruitment_kpi = has_permission("recruitment.requisitions.view_all") or has_permission(
        "recruitment.requisitions.view"
    )
    open_positions = None
    if show_recruitment_kpi:
        open_positions = _count("SELECT COUNT(*) c FROM job_requisitions WHERE status='Open'")

    # ---- Payroll KPI ----
    show_payroll_kpi = has_permission("payroll.runs.view_all") or has_permission("payroll.runs.view")
    payroll_summary = None
    if show_payroll_kpi:
        payroll_summary = db.query(
            "SELECT * FROM payroll_runs ORDER BY period_year DESC, period_month DESC LIMIT 1", one=True
        )

    # ---- Birthdays / anniversaries (only meaningful alongside workforce view) ----
    birthdays = []
    anniversaries = []
    if show_workforce_kpis:
        emp_dob_rows = db.query(
            """SELECT id, first_name, last_name, dob FROM employees
               WHERE is_deleted=0 AND employment_status='Active' AND dob IS NOT NULL"""
        )
        birthdays = _upcoming_by_month_day(emp_dob_rows, "dob")

        emp_doj_rows = db.query(
            """SELECT id, first_name, last_name, date_of_joining FROM employees
               WHERE is_deleted=0 AND employment_status='Active' AND date_of_joining IS NOT NULL"""
        )
        anniv_hits = _upcoming_by_month_day(emp_doj_rows, "date_of_joining")
        for hit in anniv_hits:
            years = hit["occurs_on"].year - hit["dob"].year
            hit["years"] = years
        anniversaries = anniv_hits

    # ---- Upcoming holidays (next 5) ----
    holidays = db.query(
        "SELECT * FROM holidays WHERE holiday_date >= ? ORDER BY holiday_date LIMIT 5", (today_iso,)
    )

    # ---- Recent activity (last 10 audit log rows) ----
    recent_activity = db.query(
        """SELECT al.*, u.full_name as actor_name FROM audit_log al
           LEFT JOIN users u ON u.id = al.user_id
           ORDER BY al.created_at DESC, al.id DESC LIMIT 10"""
    )

    return render_template(
        "dashboard/index.html",
        show_workforce_kpis=show_workforce_kpis,
        total_employees=total_employees,
        present_today=present_today,
        absent_today=absent_today,
        on_leave_today=on_leave_today,
        new_joiners=new_joiners,
        show_approvals_kpi=show_approvals_kpi,
        approvals_count=approvals_count,
        show_recruitment_kpi=show_recruitment_kpi,
        open_positions=open_positions,
        show_payroll_kpi=show_payroll_kpi,
        payroll_summary=payroll_summary,
        attendance_chart_data=attendance_chart_data,
        birthdays=birthdays,
        anniversaries=anniversaries,
        holidays=holidays,
        recent_activity=recent_activity,
    )


# ----------------------------------------------------------------------------
# My Approvals -- unified approval queue
# ----------------------------------------------------------------------------

CLAIM_NEXT_STATUS = {
    "Submitted": "Manager Approved",
    "Manager Approved": "Finance Verified",
    "Finance Verified": "Paid",
}


@bp.route("/approvals")
@login_required
def my_approvals():
    can_leave = has_permission("leave.requests.approve")
    can_attendance = has_permission("attendance.regularization.approve")
    can_claims = has_permission("claims.claims.approve")

    leave_rows = []
    if can_leave:
        leave_rows = db.query(
            """SELECT lr.*, e.first_name, e.last_name, e.employee_code, lt.name as leave_type_name
               FROM leave_requests lr
               JOIN employees e ON e.id = lr.employee_id
               JOIN leave_types lt ON lt.id = lr.leave_type_id
               WHERE lr.status='Pending'
               ORDER BY lr.created_at"""
        )

    attendance_rows = []
    if can_attendance:
        attendance_rows = db.query(
            """SELECT ar.*, e.first_name, e.last_name, e.employee_code
               FROM attendance_regularization ar
               JOIN employees e ON e.id = ar.employee_id
               WHERE ar.status='Pending'
               ORDER BY ar.created_at"""
        )

    claim_rows = []
    if can_claims:
        raw_claims = db.query(
            """SELECT ec.*, e.first_name, e.last_name, e.employee_code, ct.name as claim_type_name
               FROM expense_claims ec
               JOIN employees e ON e.id = ec.employee_id
               JOIN claim_types ct ON ct.id = ec.claim_type_id
               WHERE ec.status IN ('Submitted','Manager Approved','Finance Verified')
               ORDER BY ec.created_at"""
        )
        claim_rows = []
        for r in raw_claims:
            d = dict(r)
            d["next_status"] = CLAIM_NEXT_STATUS.get(r["status"])
            claim_rows.append(d)

    has_any = can_leave or can_attendance or can_claims

    return render_template(
        "dashboard/my_approvals.html",
        can_leave=can_leave,
        can_attendance=can_attendance,
        can_claims=can_claims,
        leave_rows=leave_rows,
        attendance_rows=attendance_rows,
        claim_rows=claim_rows,
        has_any=has_any,
    )
