"""Claims & Expense Management blueprint.

Table: expense_claims. Master data `claim_types` is managed by the admin
module — this blueprint only reads it for dropdowns.
"""
import os
import uuid

from flask import Blueprint, g, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename

import db
import audit
import notify
import config
from auth import permission_required, has_permission, login_required
from helpers import now_iso, today_iso

bp = Blueprint("claims", __name__)

STATUS_FLOW = ["Submitted", "Manager Approved", "Finance Verified", "Approved", "Paid"]
TERMINAL_STATUSES = ("Paid", "Rejected")
VALID_TRANSITIONS = {"Manager Approved", "Finance Verified", "Approved", "Rejected", "Paid"}


def _save_receipt(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    folder = os.path.join(config.UPLOAD_DIR, "claims")
    os.makedirs(folder, exist_ok=True)
    safe_name = secure_filename(file_storage.filename)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    file_storage.save(os.path.join(folder, unique_name))
    return f"claims/{unique_name}"


def _user_id_for_employee(employee_id):
    row = db.query("SELECT id FROM users WHERE employee_id=?", (employee_id,), one=True)
    return row["id"] if row else None


@bp.route("/", endpoint="claims_list")
@permission_required("claims.claims.view")
def claims_list():
    view_all = has_permission("claims.claims.view_all")
    where = []
    args = []

    if view_all:
        emp_filter = request.args.get("employee_id", type=int)
        if emp_filter:
            where.append("ec.employee_id = ?")
            args.append(emp_filter)
    else:
        where.append("ec.employee_id = ?")
        args.append(g.employee["id"] if g.employee else -1)

    status_filter = request.args.get("status", "").strip()
    if status_filter:
        where.append("ec.status = ?")
        args.append(status_filter)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(
        f"""SELECT ec.*, e.first_name || ' ' || e.last_name AS employee_name,
                   ct.name AS claim_type_name
            FROM expense_claims ec
            JOIN employees e ON e.id = ec.employee_id
            JOIN claim_types ct ON ct.id = ec.claim_type_id
            {where_sql}
            ORDER BY ec.created_at DESC""",
        args,
    )

    kpis = None
    if view_all:
        pending = db.query(
            """SELECT COUNT(*) c, COALESCE(SUM(amount),0) amt FROM expense_claims
               WHERE status IN ('Submitted','Manager Approved','Finance Verified')""",
            one=True,
        )
        approved_month = db.query(
            """SELECT COUNT(*) c, COALESCE(SUM(amount),0) amt FROM expense_claims
               WHERE status = 'Approved' AND strftime('%Y-%m', approved_at) = strftime('%Y-%m','now')""",
            one=True,
        )
        paid_month = db.query(
            """SELECT COUNT(*) c, COALESCE(SUM(amount),0) amt FROM expense_claims
               WHERE status = 'Paid' AND strftime('%Y-%m', paid_at) = strftime('%Y-%m','now')""",
            one=True,
        )
        kpis = {"pending": pending, "approved_month": approved_month, "paid_month": paid_month}

    employees = db.query(
        "SELECT id, first_name || ' ' || last_name AS name FROM employees WHERE is_deleted=0 ORDER BY first_name"
    ) if view_all else []

    return render_template(
        "claims/list.html",
        rows=rows, view_all=view_all, kpis=kpis, employees=employees,
        status_filter=status_filter,
        employee_filter=request.args.get("employee_id", type=int),
        statuses=STATUS_FLOW + ["Rejected"],
    )


@bp.route("/new", methods=("GET", "POST"), endpoint="claim_new")
@permission_required("claims.claims.create")
def claim_new():
    if g.employee is None:
        flash("Your account is not linked to an employee record — you cannot submit claims.", "error")
        return redirect(url_for("claims.claims_list"))

    claim_types = db.query("SELECT id, name, max_amount FROM claim_types WHERE is_active=1 ORDER BY name")

    if request.method == "POST":
        claim_type_id = request.form.get("claim_type_id", type=int)
        expense_date = request.form.get("expense_date", "").strip()
        amount = request.form.get("amount", type=float)
        description = request.form.get("description", "").strip() or None
        project_or_department = request.form.get("project_or_department", "").strip() or None
        receipt_file = request.files.get("receipt")

        if not claim_type_id or not expense_date or not amount:
            flash("Claim type, expense date and amount are required.", "error")
            return render_template("claims/new.html", claim_types=claim_types, today=today_iso())

        receipt_path = _save_receipt(receipt_file)
        claim_number = db.next_sequence("CLAIM", "CLM", 5)

        new_id = db.execute(
            """INSERT INTO expense_claims
               (claim_number, employee_id, claim_type_id, expense_date, amount, description,
                receipt_path, project_or_department, status)
               VALUES (?,?,?,?,?,?,?,?, 'Submitted')""",
            (claim_number, g.employee["id"], claim_type_id, expense_date, amount, description,
             receipt_path, project_or_department),
        )
        audit.log("claims", "claims", new_id, "create", f"Submitted expense claim {claim_number}")

        notify.notify_manager(
            g.employee["id"],
            "New expense claim submitted",
            f"{g.employee['first_name']} {g.employee['last_name']} submitted claim {claim_number}.",
            link=url_for("claims.claim_view", id=new_id),
        )
        flash(f"Claim {claim_number} submitted successfully.", "success")
        return redirect(url_for("claims.claim_view", id=new_id))

    return render_template("claims/new.html", claim_types=claim_types, today=today_iso())


@bp.route("/<int:id>", endpoint="claim_view")
@permission_required("claims.claims.view")
def claim_view(id):
    row = db.query(
        """SELECT ec.*, e.first_name || ' ' || e.last_name AS employee_name, e.employee_code,
                  ct.name AS claim_type_name, u.full_name AS manager_name
           FROM expense_claims ec
           JOIN employees e ON e.id = ec.employee_id
           JOIN claim_types ct ON ct.id = ec.claim_type_id
           LEFT JOIN users u ON u.id = ec.manager_id
           WHERE ec.id=?""",
        (id,), one=True,
    )
    if row is None:
        flash("Claim not found.", "error")
        return redirect(url_for("claims.claims_list"))

    if not has_permission("claims.claims.view_all"):
        if g.employee is None or row["employee_id"] != g.employee["id"]:
            flash("You don't have permission to view this claim.", "error")
            return redirect(url_for("claims.claims_list"))

    can_approve = has_permission("claims.claims.approve")
    can_process = has_permission("claims.claims.process")

    next_action = None  # (target_status, button label, css class)
    if row["status"] == "Submitted" and can_approve:
        next_action = ("Manager Approved", "Manager approve", "primary")
    elif row["status"] == "Manager Approved" and can_approve:
        next_action = ("Finance Verified", "Finance verify", "primary")
    elif row["status"] == "Finance Verified" and can_approve:
        next_action = ("Approved", "Approve", "primary")
    elif row["status"] == "Approved" and can_process:
        next_action = ("Paid", "Mark paid", "success")

    can_reject = can_approve and row["status"] not in TERMINAL_STATUSES

    step_index = STATUS_FLOW.index(row["status"]) if row["status"] in STATUS_FLOW else -1

    return render_template(
        "claims/view.html", row=row, flow=STATUS_FLOW, step_index=step_index,
        next_action=next_action, can_reject=can_reject,
    )


@bp.route("/<int:id>/status", methods=("POST",), endpoint="claim_status")
@login_required
def claim_status(id):
    row = db.query("SELECT * FROM expense_claims WHERE id=?", (id,), one=True)
    if row is None:
        flash("Claim not found.", "error")
        return redirect(url_for("claims.claims_list"))

    new_status = request.form.get("status", "").strip()
    if new_status not in VALID_TRANSITIONS:
        flash("Invalid status transition.", "error")
        return redirect(url_for("claims.claim_view", id=id))

    if row["status"] in TERMINAL_STATUSES:
        flash("This claim has already been finalized and cannot be changed further.", "error")
        return redirect(url_for("claims.claim_view", id=id))

    required_perm = "claims.claims.process" if new_status == "Paid" else "claims.claims.approve"
    if not has_permission(required_perm):
        flash(f"You don't have permission to do this ({required_perm}).", "error")
        return redirect(url_for("claims.claim_view", id=id))

    sets = ["status=?"]
    values = [new_status]

    if new_status == "Manager Approved":
        sets.append("manager_id=?")
        values.append(g.user["id"])
    if new_status == "Approved" and not row["approved_at"]:
        sets.append("approved_at=?")
        values.append(now_iso())
    if new_status == "Paid":
        sets.append("paid_at=?")
        values.append(now_iso())

    values.append(id)
    db.execute(f"UPDATE expense_claims SET {','.join(sets)} WHERE id=?", values)

    action = "process" if new_status == "Paid" else "approve"
    audit.log("claims", "claims", id, action, f"Claim {row['claim_number']} status changed to {new_status}")

    requester_uid = _user_id_for_employee(row["employee_id"])
    if requester_uid:
        ntype = "success" if new_status not in ("Rejected",) else "warning"
        notify.notify_user(
            requester_uid,
            f"Claim {row['claim_number']} — {new_status}",
            f"Your expense claim {row['claim_number']} is now '{new_status}'.",
            ntype=ntype,
            link=url_for("claims.claim_view", id=id),
        )

    flash(f"Claim {row['claim_number']} marked as {new_status}.", "success")
    return redirect(url_for("claims.claim_view", id=id))
