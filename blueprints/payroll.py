"""Payroll module: salary structures, payroll runs, payslips and loans.

Tables owned: salary_structures, payroll_runs, payslips, loans.
Bespoke blueprint (not crud.py) because payroll run generation is a
multi-step workflow with computed fields, not simple CRUD.
"""
import calendar
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

import db
import audit
import notify
from auth import permission_required, has_permission, login_required
from helpers import now_iso, paginate_args

bp = Blueprint("payroll", __name__)

EARNING_COLS = ("basic", "hra", "conveyance", "medical", "special_allowance", "other_allowance")
STRUCTURE_FIELD_LABELS = {
    "basic": "Basic",
    "hra": "HRA",
    "conveyance": "Conveyance",
    "medical": "Medical",
    "special_allowance": "Special Allowance",
    "other_allowance": "Other Allowance",
}
MONTH_NAMES = [(m, calendar.month_name[m]) for m in range(1, 13)]


def _employee_name(e):
    return f"{e['first_name']} {e['last_name']}"


def _period_label(month, year):
    return f"{calendar.month_name[int(month)]} {year}"


# ----------------------------------------------------------------------------
# Salary Structures
# ----------------------------------------------------------------------------

@bp.route("/structures")
@permission_required("payroll.structures.view_all")
def structures_list():
    q = request.args.get("q", "").strip()
    page, per_page = paginate_args(request)
    where = ["e.is_deleted = 0"]
    args = []
    if q:
        where.append("(e.first_name LIKE ? OR e.last_name LIKE ? OR e.employee_code LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    where_sql = " AND ".join(where)
    total = db.query(f"SELECT COUNT(*) c FROM employees e WHERE {where_sql}", args, one=True)["c"]
    offset = (page - 1) * per_page
    rows = db.query(
        f"""SELECT e.id as employee_id, e.employee_code, e.first_name, e.last_name,
                   e.employment_status, d.name as department_name,
                   ss.id as structure_id, ss.basic, ss.hra, ss.conveyance, ss.medical,
                   ss.special_allowance, ss.other_allowance, ss.effective_from
            FROM employees e
            LEFT JOIN departments d ON d.id = e.department_id
            LEFT JOIN salary_structures ss ON ss.employee_id = e.id AND ss.is_active = 1
            WHERE {where_sql}
            ORDER BY e.first_name, e.last_name
            LIMIT ? OFFSET ?""",
        args + [per_page, offset],
    )
    display_rows = []
    for r in rows:
        d = dict(r)
        if d["structure_id"]:
            d["gross"] = sum(d[c] or 0 for c in EARNING_COLS)
        else:
            d["gross"] = None
        display_rows.append(d)
    import math
    pages = max(1, math.ceil(total / per_page))
    return render_template(
        "payroll/structures_list.html", rows=display_rows, q=q,
        page=page, pages=pages, total=total, per_page=per_page,
        can_edit=has_permission("payroll.structures.edit"),
    )


@bp.route("/structures/<int:employee_id>/edit", methods=("GET", "POST"))
@permission_required("payroll.structures.edit")
def structure_edit(employee_id):
    employee = db.query("SELECT * FROM employees WHERE id=? AND is_deleted=0", (employee_id,), one=True)
    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("payroll.structures_list"))

    current = db.query(
        "SELECT * FROM salary_structures WHERE employee_id=? AND is_active=1", (employee_id,), one=True
    )

    if request.method == "POST":
        def f(name, default=0):
            val = request.form.get(name, "").strip()
            try:
                return float(val) if val != "" else default
            except ValueError:
                return default

        effective_from = request.form.get("effective_from") or date.today().isoformat()
        values = {
            "basic": f("basic"), "hra": f("hra"), "conveyance": f("conveyance"),
            "medical": f("medical"), "special_allowance": f("special_allowance"),
            "other_allowance": f("other_allowance"), "pf_employee_pct": f("pf_employee_pct", 12),
            "esi_employee_pct": f("esi_employee_pct", 0.75), "professional_tax": f("professional_tax", 200),
            "income_tax_monthly": f("income_tax_monthly"),
        }
        if current:
            db.execute("UPDATE salary_structures SET is_active=0 WHERE id=?", (current["id"],))
        new_id = db.execute(
            """INSERT INTO salary_structures
               (employee_id, effective_from, basic, hra, conveyance, medical, special_allowance,
                other_allowance, pf_employee_pct, esi_employee_pct, professional_tax,
                income_tax_monthly, is_active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (
                employee_id, effective_from, values["basic"], values["hra"], values["conveyance"],
                values["medical"], values["special_allowance"], values["other_allowance"],
                values["pf_employee_pct"], values["esi_employee_pct"], values["professional_tax"],
                values["income_tax_monthly"],
            ),
        )
        audit.log(
            "payroll", "structures", new_id, "create" if current is None else "update",
            f"New salary structure for {_employee_name(employee)} effective {effective_from}"
            + (" (superseded previous structure)" if current else ""),
        )
        flash(f"Salary structure saved for {_employee_name(employee)}.", "success")
        return redirect(url_for("payroll.structures_list"))

    gross = sum((current[c] if current else 0) or 0 for c in EARNING_COLS) if current else 0
    return render_template(
        "payroll/structure_edit.html", employee=employee, current=current, gross=gross,
        earning_cols=EARNING_COLS, labels=STRUCTURE_FIELD_LABELS, today=date.today().isoformat(),
    )


# ----------------------------------------------------------------------------
# Payroll Runs
# ----------------------------------------------------------------------------

@bp.route("/runs")
@permission_required("payroll.runs.view_all")
def runs_list():
    rows = db.query("SELECT * FROM payroll_runs ORDER BY period_year DESC, period_month DESC, id DESC")
    display_rows = []
    for r in rows:
        d = dict(r)
        d["period_label"] = _period_label(d["period_month"], d["period_year"])
        display_rows.append(d)
    return render_template(
        "payroll/runs_list.html", rows=display_rows,
        can_create=has_permission("payroll.runs.create"),
    )


@bp.route("/runs/new", methods=("GET", "POST"))
@permission_required("payroll.runs.create")
def run_new():
    if request.method == "POST":
        try:
            month = int(request.form.get("period_month"))
            year = int(request.form.get("period_year"))
        except (TypeError, ValueError):
            flash("Please select a valid period.", "error")
            return redirect(url_for("payroll.run_new"))

        existing = db.query(
            "SELECT id FROM payroll_runs WHERE period_month=? AND period_year=?", (month, year), one=True
        )
        if existing:
            flash(f"A payroll run for {_period_label(month, year)} already exists.", "error")
            return redirect(url_for("payroll.run_view", id=existing["id"]))

        run_number = db.next_sequence("PAYROLL", "PR", 5)
        run_id = db.execute(
            """INSERT INTO payroll_runs (run_number, period_month, period_year, status)
               VALUES (?,?,?, 'Draft')""",
            (run_number, month, year),
        )

        employees = db.query(
            "SELECT * FROM employees WHERE employment_status='Active' AND is_deleted=0"
        )
        total_gross = total_deductions = total_net = 0.0
        paid_count = 0

        for emp in employees:
            structure = db.query(
                "SELECT * FROM salary_structures WHERE employee_id=? AND is_active=1", (emp["id"],), one=True
            )
            if structure is None:
                continue

            gross_earnings = sum(structure[c] or 0 for c in EARNING_COLS)
            pf_deduction = (structure["basic"] or 0) * (structure["pf_employee_pct"] or 0) / 100
            esi_deduction = (gross_earnings * (structure["esi_employee_pct"] or 0) / 100) if gross_earnings <= 21000 else 0
            professional_tax = structure["professional_tax"] or 0
            income_tax = structure["income_tax_monthly"] or 0

            loan_deduction = 0.0
            active_loans = db.query(
                "SELECT * FROM loans WHERE employee_id=? AND status='Active'", (emp["id"],)
            )
            for loan in active_loans:
                installment = min(loan["monthly_installment"] or 0, loan["remaining_balance"] or 0)
                if installment <= 0:
                    continue
                new_balance = round((loan["remaining_balance"] or 0) - installment, 2)
                loan_deduction += installment
                if new_balance <= 0:
                    db.execute(
                        "UPDATE loans SET remaining_balance=0, status='Closed' WHERE id=?", (loan["id"],)
                    )
                else:
                    db.execute(
                        "UPDATE loans SET remaining_balance=? WHERE id=?", (new_balance, loan["id"])
                    )

            deductions = pf_deduction + esi_deduction + professional_tax + income_tax + loan_deduction
            net_pay = gross_earnings - deductions

            db.execute(
                """INSERT INTO payslips
                   (payroll_run_id, employee_id, basic, hra, conveyance, medical, special_allowance,
                    other_allowance, overtime_amount, bonus, gross_earnings, pf_deduction, esi_deduction,
                    professional_tax, income_tax, loan_deduction, other_deduction, total_deductions,
                    net_pay, lop_days, status)
                   VALUES (?,?,?,?,?,?,?,?,0,0,?,?,?,?,?,?,0,?,?,0,'Generated')""",
                (
                    run_id, emp["id"], structure["basic"], structure["hra"], structure["conveyance"],
                    structure["medical"], structure["special_allowance"], structure["other_allowance"],
                    gross_earnings, pf_deduction, esi_deduction, professional_tax, income_tax,
                    loan_deduction, deductions, net_pay,
                ),
            )
            total_gross += gross_earnings
            total_deductions += deductions
            total_net += net_pay
            paid_count += 1

        db.execute(
            "UPDATE payroll_runs SET total_gross=?, total_deductions=?, total_net=? WHERE id=?",
            (total_gross, total_deductions, total_net, run_id),
        )
        audit.log(
            "payroll", "runs", run_id, "create",
            f"Generated payroll run {run_number} for {_period_label(month, year)} ({paid_count} employees paid)",
        )
        if paid_count == 0:
            flash(
                f"Payroll run {run_number} created, but no active employees had an active salary structure.",
                "info",
            )
        else:
            flash(f"Payroll run {run_number} generated for {paid_count} employee(s).", "success")
        return redirect(url_for("payroll.run_view", id=run_id))

    years = list(range(date.today().year - 1, date.today().year + 2))
    return render_template("payroll/run_new.html", months=MONTH_NAMES, years=years, today=date.today())


@bp.route("/runs/<int:id>")
@permission_required("payroll.runs.view")
def run_view(id):
    run = db.query("SELECT * FROM payroll_runs WHERE id=?", (id,), one=True)
    if run is None:
        flash("Payroll run not found.", "error")
        return redirect(url_for("payroll.runs_list"))
    payslips = db.query(
        """SELECT p.*, e.employee_code, e.first_name, e.last_name
           FROM payslips p JOIN employees e ON e.id = p.employee_id
           WHERE p.payroll_run_id=?
           ORDER BY e.first_name, e.last_name""",
        (id,),
    )
    return render_template(
        "payroll/run_view.html", run=run, payslips=payslips,
        period_label=_period_label(run["period_month"], run["period_year"]),
        can_process=has_permission("payroll.runs.process"),
    )


@bp.route("/runs/<int:id>/process", methods=("POST",))
@permission_required("payroll.runs.process")
def run_process(id):
    run = db.query("SELECT * FROM payroll_runs WHERE id=?", (id,), one=True)
    if run is None:
        flash("Payroll run not found.", "error")
        return redirect(url_for("payroll.runs_list"))
    if run["status"] != "Draft":
        flash(f"Payroll run {run['run_number']} has already been processed.", "error")
        return redirect(url_for("payroll.run_view", id=id))

    db.execute(
        "UPDATE payroll_runs SET status='Processed', processed_at=?, processed_by=? WHERE id=?",
        (now_iso(), g.user["id"], id),
    )
    db.execute("UPDATE payslips SET status='Processed' WHERE payroll_run_id=?", (id,))

    period_label = _period_label(run["period_month"], run["period_year"])
    payslips = db.query(
        """SELECT p.id, p.net_pay, p.employee_id, u.id as user_id
           FROM payslips p
           LEFT JOIN users u ON u.employee_id = p.employee_id
           WHERE p.payroll_run_id=?""",
        (id,),
    )
    for ps in payslips:
        if ps["user_id"]:
            notify.notify_user(
                ps["user_id"], "Payslip ready",
                f"Your payslip for {period_label} is ready. Net pay: {ps['net_pay']:,.2f}.",
                "success", url_for("payroll.my_payslips"),
            )
    audit.log("payroll", "runs", id, "process", f"Processed payroll run {run['run_number']} ({period_label})")
    flash(f"Payroll run {run['run_number']} processed and payslips published.", "success")
    return redirect(url_for("payroll.run_view", id=id))


# ----------------------------------------------------------------------------
# Payslips
# ----------------------------------------------------------------------------

@bp.route("/payslips/<int:id>")
@login_required
def payslip_view(id):
    payslip = db.query(
        """SELECT p.*, e.employee_code, e.first_name, e.last_name, e.department_id,
                  e.designation_id, d.name as department_name, des.title as designation_title
           FROM payslips p
           JOIN employees e ON e.id = p.employee_id
           LEFT JOIN departments d ON d.id = e.department_id
           LEFT JOIN designations des ON des.id = e.designation_id
           WHERE p.id=?""",
        (id,), one=True,
    )
    if payslip is None:
        flash("Payslip not found.", "error")
        return redirect(url_for("dashboard.index"))

    is_owner = g.employee is not None and g.employee["id"] == payslip["employee_id"]
    if not is_owner and not has_permission("payroll.payslips.view_all"):
        abort(403)

    run = db.query("SELECT * FROM payroll_runs WHERE id=?", (payslip["payroll_run_id"],), one=True)
    return render_template(
        "payroll/payslip_view.html", payslip=payslip, run=run,
        period_label=_period_label(run["period_month"], run["period_year"]),
    )


@bp.route("/my-payslips")
@permission_required("payroll.payslips.view")
def my_payslips():
    if g.employee is None:
        flash("No employee record is linked to your account.", "error")
        return redirect(url_for("dashboard.index"))
    rows = db.query(
        """SELECT p.*, r.period_month, r.period_year, r.run_number
           FROM payslips p JOIN payroll_runs r ON r.id = p.payroll_run_id
           WHERE p.employee_id=? AND r.status='Processed'
           ORDER BY r.period_year DESC, r.period_month DESC""",
        (g.employee["id"],),
    )
    display_rows = []
    for r in rows:
        d = dict(r)
        d["period_label"] = _period_label(d["period_month"], d["period_year"])
        display_rows.append(d)
    return render_template("payroll/my_payslips.html", rows=display_rows)


# ----------------------------------------------------------------------------
# Loans
# ----------------------------------------------------------------------------

@bp.route("/loans")
@permission_required("payroll.loans.view_all")
def loans_list():
    rows = db.query(
        """SELECT l.*, e.employee_code, e.first_name, e.last_name
           FROM loans l JOIN employees e ON e.id = l.employee_id
           ORDER BY l.status='Active' DESC, l.start_date DESC"""
    )
    return render_template(
        "payroll/loans_list.html", rows=rows, can_create=has_permission("payroll.loans.create")
    )


@bp.route("/loans/new", methods=("GET", "POST"))
@permission_required("payroll.loans.create")
def loan_new():
    employees = db.query(
        "SELECT id, employee_code, first_name, last_name FROM employees WHERE is_deleted=0 ORDER BY first_name, last_name"
    )
    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        loan_type = request.form.get("loan_type", "").strip()
        amount = request.form.get("amount", type=float)
        monthly_installment = request.form.get("monthly_installment", type=float)
        start_date = request.form.get("start_date") or date.today().isoformat()

        errors = []
        employee = db.query("SELECT * FROM employees WHERE id=? AND is_deleted=0", (employee_id,), one=True) if employee_id else None
        if not employee:
            errors.append("Please select a valid employee.")
        if not loan_type:
            errors.append("Loan type is required.")
        if not amount or amount <= 0:
            errors.append("Amount must be greater than zero.")
        if not monthly_installment or monthly_installment <= 0:
            errors.append("Monthly installment must be greater than zero.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "payroll/loan_new.html", employees=employees, today=date.today().isoformat(), form=request.form
            )

        new_id = db.execute(
            """INSERT INTO loans (employee_id, loan_type, amount, monthly_installment, start_date,
                                   remaining_balance, status)
               VALUES (?,?,?,?,?,?, 'Active')""",
            (employee_id, loan_type, amount, monthly_installment, start_date, amount),
        )
        audit.log(
            "payroll", "loans", new_id, "create",
            f"Created {loan_type} loan of {amount:,.2f} for {_employee_name(employee)}",
        )
        flash(f"Loan created for {_employee_name(employee)}.", "success")
        return redirect(url_for("payroll.loans_list"))

    return render_template("payroll/loan_new.html", employees=employees, today=date.today().isoformat(), form=None)
