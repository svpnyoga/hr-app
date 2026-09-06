"""Performance module: appraisal cycles, goals and appraisals.

Bespoke (non-CRUD) blueprint — appraisal cycles seed a lazy per-employee
appraisal row, goals/appraisals are self-service scoped, and appraisals move
through a Pending -> Self Review -> Manager Review -> Completed workflow.
"""
from datetime import datetime

from flask import Blueprint, g, render_template, request, redirect, url_for, flash

import db
import audit
import notify
from auth import permission_required, has_permission

bp = Blueprint("performance", __name__)

CYCLE_STATUSES = ["Planning", "Goal Setting", "In Progress", "Completed"]
GOAL_STATUSES = ["Not Started", "In Progress", "Completed"]
APPRAISAL_STATUS_ORDER = ["Pending", "Self Review", "Manager Review", "Completed"]


def _employee_options():
    rows = db.query(
        "SELECT id, first_name || ' ' || last_name AS full_name FROM employees "
        "WHERE is_deleted=0 ORDER BY first_name, last_name"
    )
    return [(r["id"], r["full_name"]) for r in rows]


def _cycle_options():
    rows = db.query("SELECT id, name FROM appraisal_cycles ORDER BY start_date DESC")
    return [(r["id"], r["name"]) for r in rows]


# ----------------------------------------------------------------------------
# Appraisal cycles
# ----------------------------------------------------------------------------

@bp.route("/cycles", endpoint="cycles_list")
@permission_required("performance.cycles.view")
def cycles_list():
    rows = db.query(
        """SELECT c.*,
                  (SELECT COUNT(*) FROM appraisals a WHERE a.cycle_id = c.id) AS participant_count
           FROM appraisal_cycles c
           ORDER BY c.start_date DESC"""
    )
    return render_template("performance/cycles_list.html", cycles=rows, statuses=CYCLE_STATUSES,
                            can_create=has_permission("performance.cycles.create"),
                            can_edit=has_permission("performance.cycles.edit"))


@bp.route("/cycles/new", methods=("GET", "POST"), endpoint="cycle_new")
@permission_required("performance.cycles.create")
def cycle_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        start_date = request.form.get("start_date") or None
        end_date = request.form.get("end_date") or None
        if not name or not start_date or not end_date:
            flash("Name, start date and end date are required.", "error")
            return render_template("performance/cycle_form.html")
        new_id = db.execute(
            "INSERT INTO appraisal_cycles (name, start_date, end_date, status) VALUES (?,?,?,'Planning')",
            (name, start_date, end_date),
        )
        audit.log("performance", "cycles", new_id, "create", f"Created appraisal cycle '{name}'")
        flash("Appraisal cycle created.", "success")
        return redirect(url_for("performance.cycle_view", id=new_id))
    return render_template("performance/cycle_form.html")


@bp.route("/cycles/<int:id>/status", methods=("POST",), endpoint="cycle_status")
@permission_required("performance.cycles.edit")
def cycle_status(id):
    cycle = db.query("SELECT * FROM appraisal_cycles WHERE id=?", (id,), one=True)
    if cycle is None:
        flash("Cycle not found.", "error")
        return redirect(url_for("performance.cycles_list"))
    status = request.form.get("status", "")
    if status not in CYCLE_STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("performance.cycle_view", id=id))
    db.execute("UPDATE appraisal_cycles SET status=? WHERE id=?", (status, id))
    audit.log("performance", "cycles", id, "update", f"Changed cycle '{cycle['name']}' status to {status}")
    flash("Cycle status updated.", "success")
    return redirect(url_for("performance.cycle_view", id=id))


@bp.route("/cycles/<int:id>", endpoint="cycle_view")
@permission_required("performance.cycles.view")
def cycle_view(id):
    cycle = db.query("SELECT * FROM appraisal_cycles WHERE id=?", (id,), one=True)
    if cycle is None:
        flash("Cycle not found.", "error")
        return redirect(url_for("performance.cycles_list"))

    # Lazily seed a blank appraisal row for every active employee, first view.
    employees = db.query(
        "SELECT id FROM employees WHERE is_deleted=0 AND employment_status='Active'"
    )
    if employees:
        db.executemany(
            "INSERT OR IGNORE INTO appraisals (cycle_id, employee_id, status) VALUES (?, ?, 'Pending')",
            [(id, e["id"]) for e in employees],
        )

    appraisals = db.query(
        """SELECT a.*, e.first_name, e.last_name, e.employee_code
           FROM appraisals a JOIN employees e ON e.id = a.employee_id
           WHERE a.cycle_id=? ORDER BY e.first_name, e.last_name""",
        (id,),
    )
    return render_template(
        "performance/cycle_view.html", cycle=cycle, appraisals=appraisals, statuses=CYCLE_STATUSES,
        can_edit=has_permission("performance.cycles.edit"),
    )


# ----------------------------------------------------------------------------
# Goals
# ----------------------------------------------------------------------------

@bp.route("/goals", endpoint="goals_list")
@permission_required("performance.goals.view")
def goals_list():
    view_all = has_permission("performance.goals.view_all")
    cycle_id = request.args.get("cycle_id", type=int)
    employee_id = request.args.get("employee_id", type=int)

    where = []
    args = []
    if not view_all:
        where.append("g.employee_id=?")
        args.append(g.employee["id"] if g.employee else -1)
    elif employee_id:
        where.append("g.employee_id=?")
        args.append(employee_id)
    if cycle_id:
        where.append("g.cycle_id=?")
        args.append(cycle_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = db.query(
        f"""SELECT g.*, c.name AS cycle_name, e.first_name, e.last_name
            FROM goals g
            JOIN appraisal_cycles c ON c.id = g.cycle_id
            JOIN employees e ON e.id = g.employee_id
            {where_sql}
            ORDER BY g.created_at DESC""",
        args,
    )
    return render_template(
        "performance/goals_list.html", goals=rows, view_all=view_all,
        cycles=_cycle_options(), employees=_employee_options() if view_all else [],
        cycle_id=cycle_id, employee_id=employee_id,
        can_create=has_permission("performance.goals.create"),
        can_edit=has_permission("performance.goals.edit"),
    )


@bp.route("/goals/new", methods=("GET", "POST"), endpoint="goal_new")
@permission_required("performance.goals.create")
def goal_new():
    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int) or (g.employee["id"] if g.employee else None)
        cycle_id = request.form.get("cycle_id", type=int)
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        kra = request.form.get("kra", "").strip() or None
        weight_pct = request.form.get("weight_pct", type=float) or 0
        target = request.form.get("target", "").strip() or None
        if not employee_id or not cycle_id or not title:
            flash("Employee, cycle and title are required.", "error")
            return render_template("performance/goal_form.html", goal=None,
                                    cycles=_cycle_options(), employees=_employee_options())
        new_id = db.execute(
            """INSERT INTO goals (cycle_id, employee_id, title, description, kra, weight_pct, target, status)
               VALUES (?,?,?,?,?,?,?,'Not Started')""",
            (cycle_id, employee_id, title, description, kra, weight_pct, target),
        )
        audit.log("performance", "goals", new_id, "create", f"Created goal '{title}'")
        flash("Goal created.", "success")
        return redirect(url_for("performance.goals_list"))
    return render_template("performance/goal_form.html", goal=None,
                            cycles=_cycle_options(), employees=_employee_options())


@bp.route("/goals/<int:id>/edit", methods=("GET", "POST"), endpoint="goal_edit")
@permission_required("performance.goals.edit")
def goal_edit(id):
    goal = db.query("SELECT * FROM goals WHERE id=?", (id,), one=True)
    if goal is None:
        flash("Goal not found.", "error")
        return redirect(url_for("performance.goals_list"))

    view_all = has_permission("performance.goals.view_all")
    is_owner = bool(g.employee and goal["employee_id"] == g.employee["id"])
    if not view_all and not is_owner:
        flash("You don't have access to this goal.", "error")
        return redirect(url_for("performance.goals_list"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        kra = request.form.get("kra", "").strip() or None
        weight_pct = request.form.get("weight_pct", type=float) or 0
        target = request.form.get("target", "").strip() or None
        status = request.form.get("status", goal["status"])
        if status not in GOAL_STATUSES:
            status = goal["status"]

        self_rating = goal["self_rating"]
        if is_owner:
            raw = request.form.get("self_rating", "")
            self_rating = int(raw) if raw else None

        manager_rating = goal["manager_rating"]
        if view_all:
            raw = request.form.get("manager_rating", "")
            manager_rating = int(raw) if raw else None

        db.execute(
            """UPDATE goals SET title=?, description=?, kra=?, weight_pct=?, target=?, status=?,
               self_rating=?, manager_rating=? WHERE id=?""",
            (title, description, kra, weight_pct, target, status, self_rating, manager_rating, id),
        )
        audit.log("performance", "goals", id, "update", f"Updated goal '{title}'")
        flash("Goal updated.", "success")
        return redirect(url_for("performance.goals_list"))

    return render_template(
        "performance/goal_form.html", goal=goal, cycles=_cycle_options(), employees=_employee_options(),
        statuses=GOAL_STATUSES, is_owner=is_owner, view_all=view_all,
    )


# ----------------------------------------------------------------------------
# Appraisals
# ----------------------------------------------------------------------------

@bp.route("/appraisals/<int:id>", endpoint="appraisal_view")
@permission_required("performance.appraisals.view")
def appraisal_view(id):
    appraisal = db.query(
        """SELECT a.*, c.name AS cycle_name, c.status AS cycle_status,
                  e.first_name, e.last_name, e.employee_code
           FROM appraisals a
           JOIN appraisal_cycles c ON c.id = a.cycle_id
           JOIN employees e ON e.id = a.employee_id
           WHERE a.id=?""",
        (id,), one=True,
    )
    if appraisal is None:
        flash("Appraisal not found.", "error")
        return redirect(url_for("performance.cycles_list"))

    view_all = has_permission("performance.appraisals.view_all")
    is_owner = bool(g.employee and appraisal["employee_id"] == g.employee["id"])
    if not view_all and not is_owner:
        flash("You don't have access to this appraisal.", "error")
        return redirect(url_for("performance.cycles_list"))

    goals = db.query(
        "SELECT * FROM goals WHERE cycle_id=? AND employee_id=? ORDER BY weight_pct DESC",
        (appraisal["cycle_id"], appraisal["employee_id"]),
    )
    can_approve = has_permission("performance.appraisals.approve")
    can_self_review = is_owner and appraisal["status"] in ("Pending", "Self Review")

    return render_template(
        "performance/appraisal_view.html", appraisal=appraisal, goals=goals,
        is_owner=is_owner, can_approve=can_approve, can_self_review=can_self_review,
        status_order=APPRAISAL_STATUS_ORDER,
    )


@bp.route("/appraisals/<int:id>/save", methods=("POST",), endpoint="appraisal_save")
@permission_required("performance.appraisals.edit")
def appraisal_save(id):
    appraisal = db.query("SELECT * FROM appraisals WHERE id=?", (id,), one=True)
    if appraisal is None:
        flash("Appraisal not found.", "error")
        return redirect(url_for("performance.cycles_list"))

    view_all = has_permission("performance.appraisals.view_all")
    is_owner = bool(g.employee and appraisal["employee_id"] == g.employee["id"])
    can_approve = has_permission("performance.appraisals.approve")
    if not view_all and not is_owner:
        flash("You don't have access to this appraisal.", "error")
        return redirect(url_for("performance.cycles_list"))

    form_action = request.form.get("form_action")

    if form_action == "self_review" and is_owner:
        self_review = request.form.get("self_review", "").strip()
        new_status = appraisal["status"]
        if self_review and appraisal["status"] == "Pending":
            new_status = "Self Review"
        db.execute("UPDATE appraisals SET self_review=?, status=? WHERE id=?", (self_review, new_status, id))
        audit.log("performance", "appraisals", id, "update", "Employee submitted self review")
        flash("Self review saved.", "success")

    elif form_action == "manager_review" and can_approve:
        manager_review = request.form.get("manager_review", "").strip()
        final_rating = request.form.get("final_rating", type=float)
        promotion_recommended = 1 if request.form.get("promotion_recommended") else 0
        increment_recommended_pct = request.form.get("increment_recommended_pct", type=float)
        now = datetime.utcnow().isoformat(timespec="seconds")
        db.execute(
            """UPDATE appraisals SET manager_review=?, final_rating=?, promotion_recommended=?,
               increment_recommended_pct=?, status='Completed', reviewer_id=?, completed_at=?
               WHERE id=?""",
            (manager_review, final_rating, promotion_recommended, increment_recommended_pct,
             g.user["id"], now, id),
        )
        audit.log("performance", "appraisals", id, "update", "Manager completed appraisal review")
        emp_user = db.query("SELECT id FROM users WHERE employee_id=?", (appraisal["employee_id"],), one=True)
        if emp_user:
            notify.notify_user(
                emp_user["id"], "Appraisal completed",
                "Your manager has completed and submitted your appraisal review.",
                ntype="success", link=url_for("performance.appraisal_view", id=id),
            )
        flash("Appraisal review saved.", "success")

    else:
        flash("You don't have permission to submit that section.", "error")

    return redirect(url_for("performance.appraisal_view", id=id))
