"""Reports & Analytics module: a centralized, read-only reporting hub with
20 report types spanning every other module (workforce, attendance, leave,
payroll, recruitment, performance, learning, field & claims, CRM). Every
report is a plain SQL SELECT/aggregate against the shared schema plus an
optional CSV export.

Tables owned: none — this module only reads across the schema, it never
writes. Gated entirely by the single `reports.reports.{view,export}`
permission pair (see rbac.py).

To keep 20 report pages maintainable, most render through one shared
template pair (`reports/_layout.html` + `reports/generic_table.html`) driven
by small column/filter/kpi/chart specs built in Python below, rather than
20 bespoke templates. `management_summary_report` (the executive rollup)
gets its own dedicated dashboard template since it isn't a flat table.
"""
from datetime import date, timedelta

from flask import Blueprint, request, render_template

import db
from auth import permission_required, has_permission
from helpers import csv_response, today_iso

bp = Blueprint("reports", __name__)


# ----------------------------------------------------------------------------
# Small builder helpers shared by every report route
# ----------------------------------------------------------------------------

_KPI_PALETTE = {
    "brand": ("var(--brand-100)", "var(--brand-700)"),
    "green": ("var(--green-bg)", "var(--green)"),
    "red": ("var(--red-bg)", "var(--red)"),
    "amber": ("var(--amber-bg)", "var(--amber)"),
    "blue": ("var(--blue-bg)", "var(--blue)"),
    "indigo": ("var(--indigo-bg)", "var(--indigo)"),
    "gray": ("var(--gray-bg)", "var(--gray)"),
}


def _kpi(icon, value, label, color="brand"):
    bg, fg = _KPI_PALETTE.get(color, _KPI_PALETTE["brand"])
    return {"icon": icon, "bg": bg, "fg": fg, "value": value, "label": label}


def _col(key, label, type="text"):
    return {"key": key, "label": label, "type": type}


def _filter_date(name, label, value):
    return {"type": "date", "name": name, "label": label, "value": value or ""}


def _filter_select(name, label, options, value, all_label=None):
    return {"type": "select", "name": name, "label": label, "options": options,
            "value": value or "", "all_label": all_label or f"All {label.lower()}"}


def _filter_text(name, label, value):
    return {"type": "text", "name": name, "label": label, "value": value or ""}


def _int_arg(name):
    v = request.args.get(name, "").strip()
    return int(v) if v.isdigit() else None


def _str_arg(name):
    return request.args.get(name, "").strip()


def _default_month_range():
    """(first-of-month, today) as ISO date strings — the default window for
    date-range reports when the user hasn't picked from/to explicitly."""
    today = date.today()
    return today.replace(day=1).isoformat(), today.isoformat()


def _departments():
    rows = db.query("SELECT id, name FROM departments WHERE is_active=1 ORDER BY name")
    return [(r["id"], r["name"]) for r in rows]


def _distinct(table, col, where=""):
    """Distinct non-null values of a column, for building filter dropdowns
    from real data rather than guessing at hardcoded workflow states.
    table/col/where are always internal literals here, never request input."""
    rows = db.query(f"SELECT DISTINCT {col} as v FROM {table} {where} ORDER BY {col}")
    return [(r["v"], r["v"]) for r in rows if r["v"] not in (None, "")]


def _employee_cell(row, id_key="employee_id", first_key="first_name", last_key="last_name", code_key="employee_code"):
    if row[id_key] is None:
        return None
    return {"id": row[id_key], "name": f"{row[first_key]} {row[last_key]}", "code": row[code_key]}


def _csv_cell(col, value):
    if col["type"] == "employee":
        return f"{value['name']} ({value['code']})" if value else ""
    if col["type"] == "pct":
        return f"{(value or 0):.1f}%"
    if value is None:
        return ""
    return value


def _render_report(report_key, title, subtitle, columns, rows, filters=None, kpis=None,
                    chart=None, extra_tables=None, csv_name=None, template="reports/generic_table.html"):
    can_export = has_permission("reports.reports.export")
    if request.args.get("export") == "csv":
        if not can_export:
            return render_template(
                template, report_title=title, report_subtitle=subtitle, columns=columns, rows=[],
                filters=filters or [], kpis=kpis or [], chart=chart, extra_tables=extra_tables or [],
                can_export=can_export,
            )
        header = [c["label"] for c in columns]
        out = [[_csv_cell(c, row.get(c["key"])) for c in columns] for row in rows]
        return csv_response(csv_name or f"{report_key}.csv", header, out)
    return render_template(
        template, report_title=title, report_subtitle=subtitle, columns=columns, rows=rows,
        filters=filters or [], kpis=kpis or [], chart=chart, extra_tables=extra_tables or [],
        can_export=can_export,
    )


# ----------------------------------------------------------------------------
# Report registry (drives the landing page — also doubles as the count check:
# exactly 20 entries across 9 groups)
# ----------------------------------------------------------------------------

GROUPS = [
    "Workforce", "Attendance & Leave", "Payroll", "Recruitment", "Performance",
    "Learning", "Field & Claims", "Sales/CRM", "Management",
]

REPORTS = [
    {"group": "Workforce", "title": "Employee Roster", "subtitle": "Full headcount with department, designation, location & status.", "endpoint": "reports.employee_report", "icon": "id-card"},
    {"group": "Workforce", "title": "Department Headcount", "subtitle": "Active employee count per department.", "endpoint": "reports.department_headcount_report", "icon": "building"},
    {"group": "Workforce", "title": "Attrition", "subtitle": "Resignations & terminations in a date range.", "endpoint": "reports.attrition_report", "icon": "trending-up"},
    {"group": "Workforce", "title": "Documents Expiry", "subtitle": "HR documents expiring within N days.", "endpoint": "reports.documents_expiry_report", "icon": "folder"},
    {"group": "Attendance & Leave", "title": "Attendance", "subtitle": "Daily attendance in a date range with status breakdown.", "endpoint": "reports.attendance_report", "icon": "clock"},
    {"group": "Attendance & Leave", "title": "Leave Requests", "subtitle": "Leave requests in a date range by status & type.", "endpoint": "reports.leave_report", "icon": "umbrella"},
    {"group": "Attendance & Leave", "title": "Leave Balances", "subtitle": "Current-year leave balances by employee & type.", "endpoint": "reports.leave_balance_report", "icon": "calendar"},
    {"group": "Payroll", "title": "Payroll Run Detail", "subtitle": "Payslips for a payroll run — gross, deductions & net.", "endpoint": "reports.payroll_report", "icon": "wallet"},
    {"group": "Recruitment", "title": "Requisition Pipeline", "subtitle": "Open requisitions with applications by stage.", "endpoint": "reports.recruitment_report", "icon": "briefcase"},
    {"group": "Recruitment", "title": "Applications by Stage", "subtitle": "Candidate pipeline funnel across all requisitions.", "endpoint": "reports.applications_by_stage_report", "icon": "chart"},
    {"group": "Performance", "title": "Appraisals", "subtitle": "Final ratings, promotions & increments for a cycle.", "endpoint": "reports.performance_report", "icon": "target"},
    {"group": "Performance", "title": "Goals Completion", "subtitle": "Goal status breakdown & per-employee completion rate.", "endpoint": "reports.goals_completion_report", "icon": "flag"},
    {"group": "Performance", "title": "Engagement", "subtitle": "Recognitions by category & survey response counts.", "endpoint": "reports.engagement_report", "icon": "heart"},
    {"group": "Learning", "title": "Training", "subtitle": "Enrollments, attendance status & assessment scores.", "endpoint": "reports.training_report", "icon": "graduation"},
    {"group": "Learning", "title": "Skill Matrix", "subtitle": "Employee skills & proficiency levels.", "endpoint": "reports.skill_matrix_report", "icon": "award"},
    {"group": "Field & Claims", "title": "Field Activity", "subtitle": "Field visits in a date range by employee & customer.", "endpoint": "reports.field_activity_report", "icon": "map-pin"},
    {"group": "Field & Claims", "title": "Expense Claims", "subtitle": "Claims in a date range with total amount.", "endpoint": "reports.claims_report", "icon": "credit-card"},
    {"group": "Sales/CRM", "title": "CRM Pipeline", "subtitle": "Lead value by pipeline stage.", "endpoint": "reports.crm_pipeline_report", "icon": "handshake"},
    {"group": "Sales/CRM", "title": "CRM Customers", "subtitle": "Customers with contact & activity counts.", "endpoint": "reports.crm_customers_report", "icon": "users"},
    {"group": "Management", "title": "Management Summary", "subtitle": "Executive rollup — headcount, attrition, payroll, pipeline & more.", "endpoint": "reports.management_summary_report", "icon": "gauge"},
]


@bp.route("/")
@permission_required("reports.reports.view")
def index():
    return render_template("reports/index.html", groups=GROUPS, reports=REPORTS)


# ----------------------------------------------------------------------------
# Workforce
# ----------------------------------------------------------------------------

@bp.route("/employees")
@permission_required("reports.reports.view")
def employee_report():
    department_id = _int_arg("department_id")
    employment_status = _str_arg("employment_status")

    where = ["e.is_deleted=0"]
    args = []
    if department_id:
        where.append("e.department_id=?")
        args.append(department_id)
    if employment_status:
        where.append("e.employment_status=?")
        args.append(employment_status)
    where_sql = " AND ".join(where)

    rows_raw = db.query(
        f"""SELECT e.id, e.employee_code, e.first_name, e.last_name, d.name as department_name,
                   des.title as designation_title, l.name as location_name,
                   e.employment_type, e.employment_status, e.date_of_joining
            FROM employees e
            LEFT JOIN departments d ON d.id=e.department_id
            LEFT JOIN designations des ON des.id=e.designation_id
            LEFT JOIN locations l ON l.id=e.location_id
            WHERE {where_sql}
            ORDER BY e.first_name, e.last_name""",
        args,
    )
    rows = [{
        "employee": {"id": r["id"], "name": f"{r['first_name']} {r['last_name']}", "code": r["employee_code"]},
        "department_name": r["department_name"], "designation_title": r["designation_title"],
        "location_name": r["location_name"], "employment_type": r["employment_type"],
        "employment_status": r["employment_status"], "date_of_joining": r["date_of_joining"],
    } for r in rows_raw]

    columns = [
        _col("employee", "Employee", "employee"), _col("department_name", "Department"),
        _col("designation_title", "Designation"), _col("location_name", "Location"),
        _col("employment_type", "Type", "badge"), _col("employment_status", "Status", "badge"),
        _col("date_of_joining", "Joined", "date"),
    ]

    active_count = sum(1 for r in rows if (r["employment_status"] or "").lower() == "active")
    kpis = [
        _kpi("users", len(rows), "Total Employees", "brand"),
        _kpi("check", active_count, "Active", "green"),
        _kpi("close", len(rows) - active_count, "Inactive / Exited", "red"),
    ]
    filters = [
        _filter_select("department_id", "Department", _departments(), department_id),
        _filter_select("employment_status", "Status", _distinct("employees", "employment_status", "WHERE is_deleted=0"), employment_status),
    ]
    return _render_report("employees", "Employee Roster", "Full headcount with department, designation, location & status.",
                           columns, rows, filters=filters, kpis=kpis)


@bp.route("/department-headcount")
@permission_required("reports.reports.view")
def department_headcount_report():
    rows_raw = db.query(
        """SELECT d.name, COUNT(e.id) as headcount
           FROM departments d
           LEFT JOIN employees e ON e.department_id=d.id AND e.is_deleted=0 AND e.employment_status='Active'
           WHERE d.is_active=1
           GROUP BY d.id ORDER BY headcount DESC, d.name"""
    )
    rows = [{"name": r["name"], "headcount": r["headcount"]} for r in rows_raw]
    columns = [_col("name", "Department"), _col("headcount", "Active Headcount", "number")]
    kpis = [_kpi("building", len(rows), "Departments", "brand"),
            _kpi("users", sum(r["headcount"] for r in rows), "Total Active", "green")]
    chart = {"type": "donut", "svg_id": "deptHeadcountChart", "title": "Headcount by Department",
              "data": [{"label": r["name"], "value": r["headcount"]} for r in rows], "height": 220}
    return _render_report("department_headcount", "Department Headcount", "Active employee count per department.",
                           columns, rows, kpis=kpis, chart=chart)


@bp.route("/attrition")
@permission_required("reports.reports.view")
def attrition_report():
    default_from = f"{date.today().year}-01-01"
    from_date = _str_arg("from") or default_from
    to_date = _str_arg("to") or today_iso()
    department_id = _int_arg("department_id")

    where = ["e.employment_status IN ('Resigned','Terminated')", "e.date_of_exit BETWEEN ? AND ?"]
    args = [from_date, to_date]
    if department_id:
        where.append("e.department_id=?")
        args.append(department_id)
    where_sql = " AND ".join(where)

    rows_raw = db.query(
        f"""SELECT e.id, e.employee_code, e.first_name, e.last_name, d.name as department_name,
                   e.employment_status, e.date_of_joining, e.date_of_exit
            FROM employees e LEFT JOIN departments d ON d.id=e.department_id
            WHERE {where_sql}
            ORDER BY e.date_of_exit DESC""",
        args,
    )
    rows = [{
        "employee": {"id": r["id"], "name": f"{r['first_name']} {r['last_name']}", "code": r["employee_code"]},
        "department_name": r["department_name"], "employment_status": r["employment_status"],
        "date_of_joining": r["date_of_joining"], "date_of_exit": r["date_of_exit"],
    } for r in rows_raw]
    columns = [
        _col("employee", "Employee", "employee"), _col("department_name", "Department"),
        _col("employment_status", "Status", "badge"), _col("date_of_joining", "Joined", "date"),
        _col("date_of_exit", "Exit Date", "date"),
    ]

    resigned = sum(1 for r in rows if r["employment_status"] == "Resigned")
    terminated = sum(1 for r in rows if r["employment_status"] == "Terminated")
    active_now = db.query("SELECT COUNT(*) c FROM employees WHERE is_deleted=0 AND employment_status='Active'", one=True)["c"]
    attrition_rate = (len(rows) / active_now * 100) if active_now else 0
    kpis = [
        _kpi("trending-up", len(rows), "Total Exits", "red"),
        _kpi("close", resigned, "Resigned", "amber"),
        _kpi("close", terminated, "Terminated", "red"),
        _kpi("gauge", f"{attrition_rate:.1f}%", "Attrition Rate", "brand"),
    ]
    by_dept = {}
    for r in rows:
        key = r["department_name"] or "Unassigned"
        by_dept[key] = by_dept.get(key, 0) + 1
    extra_tables = [{
        "title": "By Department",
        "columns": [_col("department", "Department"), _col("count", "Exits", "number")],
        "rows": [{"department": k, "count": v} for k, v in sorted(by_dept.items(), key=lambda kv: -kv[1])],
    }]
    filters = [
        _filter_date("from", "From", from_date), _filter_date("to", "To", to_date),
        _filter_select("department_id", "Department", _departments(), department_id),
    ]
    return _render_report("attrition", "Attrition", "Resignations & terminations in a date range.",
                           columns, rows, filters=filters, kpis=kpis, extra_tables=extra_tables)


@bp.route("/documents-expiry")
@permission_required("reports.reports.view")
def documents_expiry_report():
    days = _int_arg("days") or 30
    cutoff = (date.today() + timedelta(days=days)).isoformat()
    today = today_iso()

    rows_raw = db.query(
        """SELECT hd.id, hd.title, hd.expiry_date, hd.is_verified, e.id as employee_id,
                  e.employee_code, e.first_name, e.last_name, dt.name as doc_type_name
           FROM hr_documents hd
           LEFT JOIN employees e ON e.id=hd.employee_id
           LEFT JOIN document_types dt ON dt.id=hd.document_type_id
           WHERE hd.expiry_date IS NOT NULL AND hd.expiry_date <= ?
           ORDER BY hd.expiry_date ASC""",
        (cutoff,),
    )
    rows = [{
        "employee": _employee_cell(r), "doc_type_name": r["doc_type_name"], "title": r["title"],
        "expiry_date": r["expiry_date"],
        "status": "Expired" if r["expiry_date"] < today else "Expiring Soon",
        "is_verified": "Verified" if r["is_verified"] else "Unverified",
    } for r in rows_raw]
    columns = [
        _col("employee", "Employee", "employee"), _col("doc_type_name", "Document Type"),
        _col("title", "Title"), _col("expiry_date", "Expiry Date", "date"),
        _col("status", "Status", "badge"), _col("is_verified", "Verification", "badge"),
    ]
    expired = sum(1 for r in rows if r["status"] == "Expired")
    kpis = [
        _kpi("folder", len(rows), f"Expiring Within {days}d", "brand"),
        _kpi("close", expired, "Already Expired", "red"),
        _kpi("clock", len(rows) - expired, "Expiring Soon", "amber"),
    ]
    filters = [_filter_select("days", "Window", [(7, "Next 7 days"), (14, "Next 14 days"),
               (30, "Next 30 days"), (60, "Next 60 days"), (90, "Next 90 days")], days)]
    return _render_report("documents_expiry", "Documents Expiry", f"HR documents expiring within {days} days.",
                           columns, rows, filters=filters, kpis=kpis)


# ----------------------------------------------------------------------------
# Attendance & Leave
# ----------------------------------------------------------------------------

@bp.route("/attendance")
@permission_required("reports.reports.view")
def attendance_report():
    default_from, default_to = _default_month_range()
    from_date = _str_arg("from") or default_from
    to_date = _str_arg("to") or default_to
    department_id = _int_arg("department_id")
    status = _str_arg("status")

    where = ["a.date BETWEEN ? AND ?"]
    args = [from_date, to_date]
    if department_id:
        where.append("e.department_id=?")
        args.append(department_id)
    if status:
        where.append("a.status=?")
        args.append(status)
    where_sql = " AND ".join(where)

    rows_raw = db.query(
        f"""SELECT a.date, e.id as employee_id, e.employee_code, e.first_name, e.last_name,
                   d.name as department_name, a.status, a.check_in, a.check_out,
                   a.late_minutes, a.overtime_minutes, a.work_hours
            FROM attendance a JOIN employees e ON e.id=a.employee_id
            LEFT JOIN departments d ON d.id=e.department_id
            WHERE {where_sql}
            ORDER BY a.date DESC, e.first_name""",
        args,
    )
    rows = [{
        "date": r["date"], "employee": _employee_cell(r), "department_name": r["department_name"],
        "status": r["status"], "check_in": r["check_in"], "check_out": r["check_out"],
        "late_minutes": r["late_minutes"], "overtime_minutes": r["overtime_minutes"], "work_hours": r["work_hours"],
    } for r in rows_raw]
    columns = [
        _col("date", "Date", "date"), _col("employee", "Employee", "employee"), _col("department_name", "Department"),
        _col("status", "Status", "badge"), _col("check_in", "Check In"), _col("check_out", "Check Out"),
        _col("late_minutes", "Late (min)", "number"), _col("overtime_minutes", "OT (min)", "number"),
        _col("work_hours", "Hours", "number"),
    ]
    kpi_rows = db.query(
        f"""SELECT a.status, COUNT(*) c FROM attendance a JOIN employees e ON e.id=a.employee_id
            WHERE {where_sql} GROUP BY a.status""",
        args,
    )
    by_status = {r["status"]: r["c"] for r in kpi_rows}
    kpis = [
        _kpi("check", by_status.get("Present", 0), "Present", "green"),
        _kpi("close", by_status.get("Absent", 0), "Absent", "red"),
        _kpi("umbrella", by_status.get("On Leave", 0), "On Leave", "indigo"),
        _kpi("clock", by_status.get("Half Day", 0), "Half Day", "amber"),
    ]
    filters = [
        _filter_date("from", "From", from_date), _filter_date("to", "To", to_date),
        _filter_select("department_id", "Department", _departments(), department_id),
        _filter_select("status", "Status", _distinct("attendance", "status"), status),
    ]
    return _render_report("attendance", "Attendance", "Daily attendance in a date range with status breakdown.",
                           columns, rows, filters=filters, kpis=kpis,
                           csv_name=f"attendance_{from_date}_to_{to_date}.csv")


@bp.route("/leave")
@permission_required("reports.reports.view")
def leave_report():
    default_from, default_to = _default_month_range()
    from_date = _str_arg("from") or default_from
    to_date = _str_arg("to") or default_to
    status = _str_arg("status")
    leave_type_id = _int_arg("leave_type_id")

    where = ["lr.from_date BETWEEN ? AND ?"]
    args = [from_date, to_date]
    if status:
        where.append("lr.status=?")
        args.append(status)
    if leave_type_id:
        where.append("lr.leave_type_id=?")
        args.append(leave_type_id)
    where_sql = " AND ".join(where)

    rows_raw = db.query(
        f"""SELECT lr.request_number, lr.from_date, lr.to_date, lr.days, lr.status, lr.created_at,
                   e.id as employee_id, e.employee_code, e.first_name, e.last_name, lt.name as leave_type_name
            FROM leave_requests lr
            JOIN employees e ON e.id=lr.employee_id
            JOIN leave_types lt ON lt.id=lr.leave_type_id
            WHERE {where_sql}
            ORDER BY lr.from_date DESC""",
        args,
    )
    rows = [{
        "request_number": r["request_number"], "employee": _employee_cell(r), "leave_type_name": r["leave_type_name"],
        "from_date": r["from_date"], "to_date": r["to_date"], "days": r["days"], "status": r["status"],
    } for r in rows_raw]
    columns = [
        _col("request_number", "Request #"), _col("employee", "Employee", "employee"),
        _col("leave_type_name", "Leave Type"), _col("from_date", "From", "date"), _col("to_date", "To", "date"),
        _col("days", "Days", "number"), _col("status", "Status", "badge"),
    ]
    total_days = sum(r["days"] or 0 for r in rows)
    approved = sum(1 for r in rows if r["status"] == "Approved")
    pending = sum(1 for r in rows if r["status"] == "Pending")
    kpis = [
        _kpi("umbrella", len(rows), "Total Requests", "brand"),
        _kpi("check", approved, "Approved", "green"),
        _kpi("clock", pending, "Pending", "amber"),
        _kpi("calendar", total_days, "Total Days", "indigo"),
    ]
    leave_types = db.query("SELECT id, name FROM leave_types WHERE is_active=1 ORDER BY name")
    filters = [
        _filter_date("from", "From", from_date), _filter_date("to", "To", to_date),
        _filter_select("status", "Status", _distinct("leave_requests", "status"), status),
        _filter_select("leave_type_id", "Leave Type", [(r["id"], r["name"]) for r in leave_types], leave_type_id),
    ]
    return _render_report("leave", "Leave Requests", "Leave requests in a date range by status & type.",
                           columns, rows, filters=filters, kpis=kpis)


@bp.route("/leave-balance")
@permission_required("reports.reports.view")
def leave_balance_report():
    year = _int_arg("year") or date.today().year
    leave_type_id = _int_arg("leave_type_id")

    where = ["lb.year=?"]
    args = [year]
    if leave_type_id:
        where.append("lb.leave_type_id=?")
        args.append(leave_type_id)
    where_sql = " AND ".join(where)

    rows_raw = db.query(
        f"""SELECT lb.year, lb.allocated, lb.used, lb.balance,
                   e.id as employee_id, e.employee_code, e.first_name, e.last_name, lt.name as leave_type_name
            FROM leave_balances lb
            JOIN employees e ON e.id=lb.employee_id
            JOIN leave_types lt ON lt.id=lb.leave_type_id
            WHERE {where_sql}
            ORDER BY e.first_name, lt.name""",
        args,
    )
    rows = [{
        "employee": _employee_cell(r), "leave_type_name": r["leave_type_name"],
        "allocated": r["allocated"], "used": r["used"], "balance": r["balance"],
    } for r in rows_raw]
    columns = [
        _col("employee", "Employee", "employee"), _col("leave_type_name", "Leave Type"),
        _col("allocated", "Allocated", "number"), _col("used", "Used", "number"), _col("balance", "Balance", "number"),
    ]
    kpis = [
        _kpi("umbrella", len(rows), "Balance Records", "brand"),
        _kpi("calendar", round(sum(r["allocated"] or 0 for r in rows), 1), "Total Allocated", "indigo"),
        _kpi("check", round(sum(r["used"] or 0 for r in rows), 1), "Total Used", "green"),
    ]
    leave_types = db.query("SELECT id, name FROM leave_types WHERE is_active=1 ORDER BY name")
    years = db.query("SELECT DISTINCT year FROM leave_balances ORDER BY year DESC")
    filters = [
        _filter_select("year", "Year", [(r["year"], str(r["year"])) for r in years] or [(year, str(year))], year),
        _filter_select("leave_type_id", "Leave Type", [(r["id"], r["name"]) for r in leave_types], leave_type_id),
    ]
    return _render_report("leave_balance", "Leave Balances", f"Leave balances for {year} by employee & type.",
                           columns, rows, filters=filters, kpis=kpis)


# ----------------------------------------------------------------------------
# Payroll
# ----------------------------------------------------------------------------

@bp.route("/payroll")
@permission_required("reports.reports.view")
def payroll_report():
    run_id = _int_arg("run_id")
    run = db.query("SELECT * FROM payroll_runs WHERE id=?", (run_id,), one=True) if run_id else None
    if run is None:
        run = db.query("SELECT * FROM payroll_runs ORDER BY period_year DESC, period_month DESC, id DESC LIMIT 1", one=True)

    rows_raw = []
    if run:
        rows_raw = db.query(
            """SELECT p.gross_earnings, p.total_deductions, p.net_pay, p.lop_days, p.status,
                      e.id as employee_id, e.employee_code, e.first_name, e.last_name, d.name as department_name
               FROM payslips p
               JOIN employees e ON e.id=p.employee_id
               LEFT JOIN departments d ON d.id=e.department_id
               WHERE p.payroll_run_id=?
               ORDER BY e.first_name, e.last_name""",
            (run["id"],),
        )
    rows = [{
        "employee": _employee_cell(r), "department_name": r["department_name"],
        "gross_earnings": r["gross_earnings"], "total_deductions": r["total_deductions"],
        "net_pay": r["net_pay"], "lop_days": r["lop_days"], "status": r["status"],
    } for r in rows_raw]
    columns = [
        _col("employee", "Employee", "employee"), _col("department_name", "Department"),
        _col("gross_earnings", "Gross", "money"), _col("total_deductions", "Deductions", "money"),
        _col("net_pay", "Net Pay", "money"), _col("lop_days", "LOP Days", "number"), _col("status", "Status", "badge"),
    ]
    kpis = [
        _kpi("wallet", run["run_number"] if run else "—", "Payroll Run", "brand"),
        _kpi("dollar", run["total_gross"] if run else 0, "Total Gross", "blue"),
        _kpi("dollar", run["total_deductions"] if run else 0, "Total Deductions", "red"),
        _kpi("dollar", run["total_net"] if run else 0, "Total Net", "green"),
    ]
    for k in kpis[1:]:
        k["value"] = f"{k['value']:,.2f}" if isinstance(k["value"], (int, float)) else k["value"]
    runs = db.query("SELECT id, run_number, period_month, period_year FROM payroll_runs ORDER BY period_year DESC, period_month DESC")
    run_options = [(r["id"], f"{r['run_number']} — {r['period_month']:02d}/{r['period_year']}") for r in runs]
    filters = [_filter_select("run_id", "Payroll Run", run_options, run["id"] if run else "", all_label="Select a run")]
    subtitle = f"Payslips for {run['run_number']} ({run['period_month']:02d}/{run['period_year']})" if run else "No payroll runs found."
    return _render_report("payroll", "Payroll Run Detail", subtitle, columns, rows, filters=filters, kpis=kpis)


# ----------------------------------------------------------------------------
# Recruitment
# ----------------------------------------------------------------------------

_APPLICATION_STAGES = ["Applied", "Screening", "Shortlisted", "Interview", "Offer", "Selected", "Rejected"]


@bp.route("/recruitment")
@permission_required("reports.reports.view")
def recruitment_report():
    department_id = _int_arg("department_id")
    status = _str_arg("status")

    where = []
    args = []
    if department_id:
        where.append("jr.department_id=?")
        args.append(department_id)
    if status:
        where.append("jr.status=?")
        args.append(status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    stage_sums = ", ".join(
        f"""SUM(CASE WHEN a.stage='{s}' THEN 1 ELSE 0 END) as stage_{i}""" for i, s in enumerate(_APPLICATION_STAGES)
    )
    rows_raw = db.query(
        f"""SELECT jr.id, jr.requisition_number, jr.title, d.name as department_name,
                   jr.num_openings, jr.status, COUNT(a.id) as total_applications, {stage_sums}
            FROM job_requisitions jr
            LEFT JOIN departments d ON d.id=jr.department_id
            LEFT JOIN applications a ON a.requisition_id=jr.id
            {where_sql}
            GROUP BY jr.id
            ORDER BY jr.created_at DESC""",
        args,
    )
    rows = []
    for r in rows_raw:
        d = {
            "requisition_number": r["requisition_number"], "title": r["title"], "department_name": r["department_name"],
            "num_openings": r["num_openings"], "status": r["status"], "total_applications": r["total_applications"],
        }
        for i, s in enumerate(_APPLICATION_STAGES):
            d[f"stage_{i}"] = r[f"stage_{i}"]
        rows.append(d)
    columns = [
        _col("requisition_number", "Requisition #"), _col("title", "Title"), _col("department_name", "Department"),
        _col("num_openings", "Openings", "number"), _col("status", "Status", "badge"),
        _col("total_applications", "Total Apps", "number"),
    ] + [_col(f"stage_{i}", s, "number") for i, s in enumerate(_APPLICATION_STAGES)]

    open_count = sum(1 for r in rows if r["status"] == "Open")
    kpis = [
        _kpi("briefcase", open_count, "Open Requisitions", "brand"),
        _kpi("users", sum(r["num_openings"] or 0 for r in rows), "Total Openings", "indigo"),
        _kpi("chart", sum(r["total_applications"] or 0 for r in rows), "Total Applications", "blue"),
    ]
    filters = [
        _filter_select("department_id", "Department", _departments(), department_id),
        _filter_select("status", "Status", _distinct("job_requisitions", "status"), status),
    ]
    return _render_report("recruitment", "Requisition Pipeline", "Open requisitions with applications by stage.",
                           columns, rows, filters=filters, kpis=kpis)


@bp.route("/applications-by-stage")
@permission_required("reports.reports.view")
def applications_by_stage_report():
    rows_raw = db.query("SELECT stage, COUNT(*) c FROM applications GROUP BY stage ORDER BY c DESC")
    rows = [{"stage": r["stage"], "count": r["c"]} for r in rows_raw]
    columns = [_col("stage", "Stage", "badge"), _col("count", "Applications", "number")]
    kpis = [_kpi("chart", sum(r["count"] for r in rows), "Total Applications", "brand"),
            _kpi("flag", len(rows), "Stages In Use", "indigo")]
    chart = {"type": "bar", "svg_id": "applicationsByStageChart", "title": "Applications by Stage",
              "data": [{"label": r["stage"], "value": r["count"]} for r in rows], "height": 240}
    return _render_report("applications_by_stage", "Applications by Stage", "Candidate pipeline funnel across all requisitions.",
                           columns, rows, kpis=kpis, chart=chart)


# ----------------------------------------------------------------------------
# Performance
# ----------------------------------------------------------------------------

def _resolve_cycle(cycle_id):
    cycle = db.query("SELECT * FROM appraisal_cycles WHERE id=?", (cycle_id,), one=True) if cycle_id else None
    if cycle is None:
        cycle = db.query("SELECT * FROM appraisal_cycles ORDER BY start_date DESC, id DESC LIMIT 1", one=True)
    return cycle


@bp.route("/performance")
@permission_required("reports.reports.view")
def performance_report():
    cycle = _resolve_cycle(_int_arg("cycle_id"))
    rows_raw = []
    if cycle:
        rows_raw = db.query(
            """SELECT ap.final_rating, ap.promotion_recommended, ap.increment_recommended_pct, ap.status,
                      e.id as employee_id, e.employee_code, e.first_name, e.last_name, d.name as department_name
               FROM appraisals ap
               JOIN employees e ON e.id=ap.employee_id
               LEFT JOIN departments d ON d.id=e.department_id
               WHERE ap.cycle_id=?
               ORDER BY ap.final_rating DESC""",
            (cycle["id"],),
        )
    rows = [{
        "employee": _employee_cell(r), "department_name": r["department_name"], "final_rating": r["final_rating"],
        "promotion_recommended": "Yes" if r["promotion_recommended"] else "No",
        "increment_recommended_pct": r["increment_recommended_pct"], "status": r["status"],
    } for r in rows_raw]
    columns = [
        _col("employee", "Employee", "employee"), _col("department_name", "Department"),
        _col("final_rating", "Final Rating", "number"), _col("promotion_recommended", "Promotion?", "badge"),
        _col("increment_recommended_pct", "Increment %", "number"), _col("status", "Status", "badge"),
    ]
    rated = [r["final_rating"] for r in rows if r["final_rating"] is not None]
    avg_rating = (sum(rated) / len(rated)) if rated else 0
    promos = sum(1 for r in rows if r["promotion_recommended"] == "Yes")
    kpis = [
        _kpi("target", len(rows), "Appraisals", "brand"),
        _kpi("star", f"{avg_rating:.2f}", "Avg Final Rating", "amber"),
        _kpi("trending-up", promos, "Promotions Recommended", "green"),
    ]
    cycles = db.query("SELECT id, name FROM appraisal_cycles ORDER BY start_date DESC")
    filters = [_filter_select("cycle_id", "Cycle", [(c["id"], c["name"]) for c in cycles], cycle["id"] if cycle else "")]
    subtitle = f"Appraisals for {cycle['name']}" if cycle else "No appraisal cycles found."
    return _render_report("performance", "Appraisals", subtitle, columns, rows, filters=filters, kpis=kpis)


@bp.route("/goals-completion")
@permission_required("reports.reports.view")
def goals_completion_report():
    status_rows = db.query("SELECT status, COUNT(*) c FROM goals GROUP BY status ORDER BY c DESC")
    cycle = _resolve_cycle(_int_arg("cycle_id"))

    rows_raw = []
    if cycle:
        rows_raw = db.query(
            """SELECT e.id as employee_id, e.employee_code, e.first_name, e.last_name,
                      COUNT(g.id) as total_goals,
                      SUM(CASE WHEN g.status='Completed' THEN 1 ELSE 0 END) as completed_goals
               FROM goals g JOIN employees e ON e.id=g.employee_id
               WHERE g.cycle_id=?
               GROUP BY e.id
               ORDER BY e.first_name, e.last_name""",
            (cycle["id"],),
        )
    rows = []
    for r in rows_raw:
        total = r["total_goals"] or 0
        completed = r["completed_goals"] or 0
        rows.append({
            "employee": _employee_cell(r), "total_goals": total, "completed_goals": completed,
            "completion_pct": (completed / total * 100) if total else 0,
        })
    columns = [
        _col("employee", "Employee", "employee"), _col("total_goals", "Total Goals", "number"),
        _col("completed_goals", "Completed", "number"), _col("completion_pct", "Completion", "pct"),
    ]
    kpis = [_kpi("flag", r["status"] or "Unspecified", r["c"], color) for r, color in
            zip(status_rows, ["brand", "amber", "indigo", "green", "gray", "red"])]
    # kpis built above is wrong shape fix below
    kpis = []
    palette_cycle = ["brand", "amber", "indigo", "green", "gray", "red"]
    for i, r in enumerate(status_rows):
        kpis.append(_kpi("flag", r["c"], r["status"] or "Unspecified", palette_cycle[i % len(palette_cycle)]))
    filters = [_filter_select("cycle_id", "Cycle",
               [(c["id"], c["name"]) for c in db.query("SELECT id, name FROM appraisal_cycles ORDER BY start_date DESC")],
               cycle["id"] if cycle else "")]
    subtitle = f"Per-employee goal completion for {cycle['name']}" if cycle else "No appraisal cycles found."
    return _render_report("goals_completion", "Goals Completion", subtitle, columns, rows, filters=filters, kpis=kpis)


@bp.route("/engagement")
@permission_required("reports.reports.view")
def engagement_report():
    by_category = db.query("SELECT category, COUNT(*) c FROM recognitions GROUP BY category ORDER BY c DESC")
    survey_rows = db.query(
        """SELECT s.title, s.status, COUNT(sr.id) as response_count
           FROM surveys s LEFT JOIN survey_responses sr ON sr.survey_id=s.id
           GROUP BY s.id ORDER BY s.created_at DESC"""
    )
    rows = [{"title": r["title"], "status": r["status"], "response_count": r["response_count"]} for r in survey_rows]
    columns = [_col("title", "Survey"), _col("status", "Status", "badge"), _col("response_count", "Responses", "number")]

    palette_cycle = ["brand", "amber", "indigo", "green", "gray", "red"]
    kpis = [_kpi("award", r["c"], r["category"], palette_cycle[i % len(palette_cycle)]) for i, r in enumerate(by_category)]
    extra_tables = [{
        "title": "Recognitions by Category",
        "columns": [_col("category", "Category"), _col("count", "Recognitions", "number")],
        "rows": [{"category": r["category"], "count": r["c"]} for r in by_category],
    }]
    return _render_report("engagement", "Engagement", "Recognitions by category & survey response counts.",
                           columns, rows, kpis=kpis, extra_tables=extra_tables)


# ----------------------------------------------------------------------------
# Learning
# ----------------------------------------------------------------------------

@bp.route("/training")
@permission_required("reports.reports.view")
def training_report():
    course_id = _int_arg("course_id")
    attendance_status = _str_arg("attendance_status")

    where = []
    args = []
    if course_id:
        where.append("c.id=?")
        args.append(course_id)
    if attendance_status:
        where.append("te.attendance_status=?")
        args.append(attendance_status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows_raw = db.query(
        f"""SELECT te.attendance_status, te.assessment_score, te.certificate_issued, te.feedback_rating,
                   c.title as course_title, ts.session_date,
                   e.id as employee_id, e.employee_code, e.first_name, e.last_name
            FROM training_enrollments te
            JOIN training_sessions ts ON ts.id=te.session_id
            JOIN courses c ON c.id=ts.course_id
            JOIN employees e ON e.id=te.employee_id
            {where_sql}
            ORDER BY ts.session_date DESC""",
        args,
    )
    rows = [{
        "employee": _employee_cell(r), "course_title": r["course_title"], "session_date": r["session_date"],
        "attendance_status": r["attendance_status"], "assessment_score": r["assessment_score"],
        "certificate_issued": "Yes" if r["certificate_issued"] else "No",
    } for r in rows_raw]
    columns = [
        _col("employee", "Employee", "employee"), _col("course_title", "Course"), _col("session_date", "Session Date", "date"),
        _col("attendance_status", "Attendance", "badge"), _col("assessment_score", "Score", "number"),
        _col("certificate_issued", "Certificate", "badge"),
    ]
    scores = [r["assessment_score"] for r in rows if r["assessment_score"] is not None]
    kpis = [
        _kpi("graduation", len(rows), "Enrollments", "brand"),
        _kpi("star", f"{(sum(scores)/len(scores)):.1f}" if scores else "—", "Avg Score", "amber"),
        _kpi("award", sum(1 for r in rows if r["certificate_issued"] == "Yes"), "Certificates Issued", "green"),
    ]
    courses = db.query("SELECT id, title FROM courses ORDER BY title")
    filters = [
        _filter_select("course_id", "Course", [(c["id"], c["title"]) for c in courses], course_id),
        _filter_select("attendance_status", "Attendance", _distinct("training_enrollments", "attendance_status"), attendance_status),
    ]
    return _render_report("training", "Training", "Enrollments, attendance status & assessment scores.",
                           columns, rows, filters=filters, kpis=kpis)


@bp.route("/skill-matrix")
@permission_required("reports.reports.view")
def skill_matrix_report():
    skill_name = _str_arg("skill_name")
    proficiency_level = _str_arg("proficiency_level")

    where = []
    args = []
    if skill_name:
        where.append("sm.skill_name LIKE ?")
        args.append(f"%{skill_name}%")
    if proficiency_level:
        where.append("sm.proficiency_level=?")
        args.append(proficiency_level)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows_raw = db.query(
        f"""SELECT sm.skill_name, sm.proficiency_level, sm.assessed_date,
                   e.id as employee_id, e.employee_code, e.first_name, e.last_name, d.name as department_name
            FROM skill_matrix sm
            JOIN employees e ON e.id=sm.employee_id
            LEFT JOIN departments d ON d.id=e.department_id
            {where_sql}
            ORDER BY sm.skill_name, e.first_name""",
        args,
    )
    rows = [{
        "employee": _employee_cell(r), "department_name": r["department_name"], "skill_name": r["skill_name"],
        "proficiency_level": r["proficiency_level"], "assessed_date": r["assessed_date"],
    } for r in rows_raw]
    columns = [
        _col("employee", "Employee", "employee"), _col("department_name", "Department"), _col("skill_name", "Skill"),
        _col("proficiency_level", "Proficiency", "badge"), _col("assessed_date", "Assessed On", "date"),
    ]
    expert_count = sum(1 for r in rows if (r["proficiency_level"] or "").lower() == "expert")
    kpis = [
        _kpi("award", len(rows), "Skill Records", "brand"),
        _kpi("star", expert_count, "Expert Level", "green"),
        _kpi("users", len({r["employee"]["id"] for r in rows if r["employee"]}), "Employees Assessed", "indigo"),
    ]
    filters = [
        _filter_text("skill_name", "Skill Name", skill_name),
        _filter_select("proficiency_level", "Proficiency", _distinct("skill_matrix", "proficiency_level"), proficiency_level),
    ]
    return _render_report("skill_matrix", "Skill Matrix", "Employee skills & proficiency levels.",
                           columns, rows, filters=filters, kpis=kpis)


# ----------------------------------------------------------------------------
# Field & Claims
# ----------------------------------------------------------------------------

@bp.route("/field-activity")
@permission_required("reports.reports.view")
def field_activity_report():
    default_from, default_to = _default_month_range()
    from_date = _str_arg("from") or default_from
    to_date = _str_arg("to") or default_to
    status = _str_arg("status")

    where = ["fv.visit_date BETWEEN ? AND ?"]
    args = [from_date, to_date]
    if status:
        where.append("fv.status=?")
        args.append(status)
    where_sql = " AND ".join(where)

    rows_raw = db.query(
        f"""SELECT fv.visit_date, fv.customer_name, fv.purpose, fv.status, fv.travel_distance_km,
                   e.id as employee_id, e.employee_code, e.first_name, e.last_name
            FROM field_visits fv JOIN employees e ON e.id=fv.employee_id
            WHERE {where_sql}
            ORDER BY fv.visit_date DESC""",
        args,
    )
    rows = [{
        "employee": _employee_cell(r), "visit_date": r["visit_date"], "customer_name": r["customer_name"],
        "purpose": r["purpose"], "status": r["status"], "travel_distance_km": r["travel_distance_km"],
    } for r in rows_raw]
    columns = [
        _col("employee", "Employee", "employee"), _col("visit_date", "Visit Date", "date"),
        _col("customer_name", "Customer"), _col("purpose", "Purpose"), _col("status", "Status", "badge"),
        _col("travel_distance_km", "Distance (km)", "number"),
    ]
    completed = sum(1 for r in rows if r["status"] == "Completed")
    kpis = [
        _kpi("map-pin", len(rows), "Total Visits", "brand"),
        _kpi("check", completed, "Completed", "green"),
        _kpi("trending-up", round(sum(r["travel_distance_km"] or 0 for r in rows), 1), "Total Distance (km)", "indigo"),
    ]
    filters = [
        _filter_date("from", "From", from_date), _filter_date("to", "To", to_date),
        _filter_select("status", "Status", _distinct("field_visits", "status"), status),
    ]
    return _render_report("field_activity", "Field Activity", "Field visits in a date range by employee & customer.",
                           columns, rows, filters=filters, kpis=kpis)


@bp.route("/claims")
@permission_required("reports.reports.view")
def claims_report():
    default_from, default_to = _default_month_range()
    from_date = _str_arg("from") or default_from
    to_date = _str_arg("to") or default_to
    status = _str_arg("status")
    claim_type_id = _int_arg("claim_type_id")

    where = ["ec.expense_date BETWEEN ? AND ?"]
    args = [from_date, to_date]
    if status:
        where.append("ec.status=?")
        args.append(status)
    if claim_type_id:
        where.append("ec.claim_type_id=?")
        args.append(claim_type_id)
    where_sql = " AND ".join(where)

    rows_raw = db.query(
        f"""SELECT ec.claim_number, ec.expense_date, ec.amount, ec.status, ct.name as claim_type_name,
                   e.id as employee_id, e.employee_code, e.first_name, e.last_name
            FROM expense_claims ec
            JOIN employees e ON e.id=ec.employee_id
            JOIN claim_types ct ON ct.id=ec.claim_type_id
            WHERE {where_sql}
            ORDER BY ec.expense_date DESC""",
        args,
    )
    rows = [{
        "claim_number": r["claim_number"], "employee": _employee_cell(r), "claim_type_name": r["claim_type_name"],
        "expense_date": r["expense_date"], "amount": r["amount"], "status": r["status"],
    } for r in rows_raw]
    columns = [
        _col("claim_number", "Claim #"), _col("employee", "Employee", "employee"), _col("claim_type_name", "Type"),
        _col("expense_date", "Date", "date"), _col("amount", "Amount", "money"), _col("status", "Status", "badge"),
    ]
    total_amount = sum(r["amount"] or 0 for r in rows)
    kpis = [
        _kpi("credit-card", len(rows), "Claims", "brand"),
        _kpi("dollar", f"{total_amount:,.2f}", "Total Amount", "blue"),
        _kpi("clock", sum(1 for r in rows if r["status"] == "Submitted"), "Pending", "amber"),
    ]
    claim_types = db.query("SELECT id, name FROM claim_types WHERE is_active=1 ORDER BY name")
    filters = [
        _filter_date("from", "From", from_date), _filter_date("to", "To", to_date),
        _filter_select("status", "Status", _distinct("expense_claims", "status"), status),
        _filter_select("claim_type_id", "Claim Type", [(c["id"], c["name"]) for c in claim_types], claim_type_id),
    ]
    return _render_report("claims", "Expense Claims", "Claims in a date range with total amount.",
                           columns, rows, filters=filters, kpis=kpis)


# ----------------------------------------------------------------------------
# Sales / CRM
# ----------------------------------------------------------------------------

@bp.route("/crm-pipeline")
@permission_required("reports.reports.view")
def crm_pipeline_report():
    rows_raw = db.query(
        """SELECT status, COUNT(*) c, SUM(COALESCE(estimated_value,0)) total_value
           FROM crm_leads GROUP BY status ORDER BY total_value DESC"""
    )
    rows = [{"status": r["status"], "lead_count": r["c"], "total_value": r["total_value"]} for r in rows_raw]
    columns = [_col("status", "Stage", "badge"), _col("lead_count", "Leads", "number"), _col("total_value", "Total Value", "money")]
    kpis = [
        _kpi("handshake", sum(r["lead_count"] for r in rows), "Total Leads", "brand"),
        _kpi("dollar", f"{sum(r['total_value'] or 0 for r in rows):,.2f}", "Total Pipeline Value", "green"),
    ]
    chart = {"type": "bar", "svg_id": "crmPipelineChart", "title": "Pipeline Value by Stage",
              "data": [{"label": r["status"], "value": round(r["total_value"] or 0)} for r in rows], "height": 240}
    return _render_report("crm_pipeline", "CRM Pipeline", "Lead value by pipeline stage.", columns, rows, kpis=kpis, chart=chart)


@bp.route("/crm-customers")
@permission_required("reports.reports.view")
def crm_customers_report():
    q = _str_arg("q")
    where = []
    args = []
    if q:
        where.append("cc.name LIKE ?")
        args.append(f"%{q}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows_raw = db.query(
        f"""SELECT cc.customer_code, cc.name, cc.industry, cc.city, cc.phone, cc.email,
                   COUNT(DISTINCT ct.id) as contact_count, COUNT(DISTINCT ca.id) as activity_count
            FROM crm_customers cc
            LEFT JOIN crm_contacts ct ON ct.customer_id=cc.id
            LEFT JOIN crm_activities ca ON ca.customer_id=cc.id
            {where_sql}
            GROUP BY cc.id
            ORDER BY cc.name""",
        args,
    )
    rows = [{
        "customer_code": r["customer_code"], "name": r["name"], "industry": r["industry"], "city": r["city"],
        "contact_count": r["contact_count"], "activity_count": r["activity_count"],
    } for r in rows_raw]
    columns = [
        _col("customer_code", "Code"), _col("name", "Customer"), _col("industry", "Industry"), _col("city", "City"),
        _col("contact_count", "Contacts", "number"), _col("activity_count", "Activities", "number"),
    ]
    kpis = [
        _kpi("users", len(rows), "Customers", "brand"),
        _kpi("handshake", sum(r["contact_count"] for r in rows), "Total Contacts", "indigo"),
        _kpi("chart", sum(r["activity_count"] for r in rows), "Total Activities", "blue"),
    ]
    filters = [_filter_text("q", "Search customer name", q)]
    return _render_report("crm_customers", "CRM Customers", "Customers with contact & activity counts.",
                           columns, rows, filters=filters, kpis=kpis)


# ----------------------------------------------------------------------------
# Management
# ----------------------------------------------------------------------------

@bp.route("/management-summary")
@permission_required("reports.reports.view")
def management_summary_report():
    year = date.today().year
    month_start, today = _default_month_range()

    headcount = db.query("SELECT COUNT(*) c FROM employees WHERE is_deleted=0 AND employment_status='Active'", one=True)["c"]
    exits_this_year = db.query(
        "SELECT COUNT(*) c FROM employees WHERE employment_status IN ('Resigned','Terminated') AND date_of_exit BETWEEN ? AND ?",
        (f"{year}-01-01", f"{year}-12-31"), one=True,
    )["c"]
    attrition_rate = (exits_this_year / headcount * 100) if headcount else 0

    att_counts = db.query(
        "SELECT COUNT(*) total, SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) present FROM attendance WHERE date BETWEEN ? AND ?",
        (month_start, today), one=True,
    )
    avg_attendance_pct = (att_counts["present"] / att_counts["total"] * 100) if att_counts["total"] else 0

    open_req = db.query("SELECT COUNT(*) c, COALESCE(SUM(num_openings),0) n FROM job_requisitions WHERE status='Open'", one=True)

    pending_leave = db.query("SELECT COUNT(*) c FROM leave_requests WHERE status='Pending'", one=True)["c"]
    pending_claims = db.query("SELECT COUNT(*) c FROM expense_claims WHERE status='Submitted'", one=True)["c"]
    pending_reg = db.query("SELECT COUNT(*) c FROM attendance_regularization WHERE status='Pending'", one=True)["c"]
    pending_total = pending_leave + pending_claims + pending_reg

    total_payroll_year = db.query("SELECT COALESCE(SUM(total_net),0) n FROM payroll_runs WHERE period_year=?", (year,), one=True)["n"]
    pipeline_value = db.query("SELECT COALESCE(SUM(estimated_value),0) n FROM crm_leads WHERE status NOT IN ('Lost','Won')", one=True)["n"]

    tiles = [
        _kpi("users", headcount, "Active Headcount", "brand"),
        _kpi("trending-up", f"{attrition_rate:.1f}%", f"Attrition Rate ({year})", "red"),
        _kpi("clock", f"{avg_attendance_pct:.1f}%", "Avg Attendance (MTD)", "green"),
        _kpi("briefcase", f"{open_req['c']} / {open_req['n']}", "Open Requisitions / Openings", "indigo"),
        _kpi("clipboard-check", pending_total, "Pending Approvals", "amber"),
        _kpi("wallet", f"{total_payroll_year:,.2f}", f"Total Payroll ({year})", "blue"),
        _kpi("handshake", f"{pipeline_value:,.2f}", "Active Pipeline Value", "gray"),
    ]

    if request.args.get("export") == "csv" and has_permission("reports.reports.export"):
        header = ["Metric", "Value"]
        out = [[t["label"], t["value"]] for t in tiles]
        return csv_response("management_summary.csv", header, out)

    return render_template(
        "reports/management_summary.html", report_title="Management Summary",
        report_subtitle="Executive rollup across every module.", tiles=tiles,
        can_export=has_permission("reports.reports.export"),
    )
