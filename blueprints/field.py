"""Field Tracking module.

Table: field_visits. Free-text customer_name/purpose/location fields, no
separate lookup tables. Bespoke blueprint for the plan -> check-in -> check-out
workflow with self-service scoping.
"""
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from werkzeug.utils import secure_filename

import db
import audit
from auth import permission_required, has_permission
from helpers import paginate_args, today_iso, now_iso

bp = Blueprint("field", __name__)

UPLOAD_SUBDIR = "field"


def _upload_dir():
    import config
    d = os.path.join(config.UPLOAD_DIR, UPLOAD_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def _save_photo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    safe = secure_filename(file_storage.filename)
    if not safe:
        return None
    unique = f"{uuid.uuid4().hex}_{safe}"
    file_storage.save(os.path.join(_upload_dir(), unique))
    return f"{UPLOAD_SUBDIR}/{unique}"


def _scope_filter():
    """Returns (where_sql_fragment, args) restricting to own employee unless view_all."""
    if has_permission("field.visits.view_all"):
        return "", []
    return "AND fv.employee_id = ?", [g.employee["id"] if g.employee else -1]


# ---------------------------------------------------------------------------
# List / KPIs
# ---------------------------------------------------------------------------

@bp.route("/visits")
@permission_required("field.visits.view")
def visits_list():
    view_all = has_permission("field.visits.view_all")
    page, per_page = paginate_args(request)
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    employee_id = request.args.get("employee_id", type=int) if view_all else None

    where = ["1=1"]
    args = []
    if not view_all:
        where.append("fv.employee_id = ?")
        args.append(g.employee["id"] if g.employee else -1)
    elif employee_id:
        where.append("fv.employee_id = ?")
        args.append(employee_id)
    if from_date:
        where.append("fv.visit_date >= ?")
        args.append(from_date)
    if to_date:
        where.append("fv.visit_date <= ?")
        args.append(to_date)
    where_sql = "WHERE " + " AND ".join(where)

    total = db.query(f"SELECT COUNT(*) c FROM field_visits fv {where_sql}", args, one=True)["c"]
    offset = (page - 1) * per_page
    rows = db.query(
        f"""SELECT fv.*, e.first_name, e.last_name, e.employee_code
            FROM field_visits fv JOIN employees e ON e.id = fv.employee_id
            {where_sql}
            ORDER BY fv.visit_date DESC, fv.id DESC LIMIT ? OFFSET ?""",
        args + [per_page, offset],
    )
    pages = max(1, -(-total // per_page))

    scope_sql, scope_args = _scope_filter()
    today = today_iso()
    kpi_today = db.query(
        f"SELECT COUNT(*) c FROM field_visits fv WHERE fv.visit_date = ? {scope_sql}",
        [today] + scope_args, one=True,
    )["c"]
    kpi_in_field = db.query(
        f"SELECT COUNT(*) c FROM field_visits fv WHERE fv.check_in_time IS NOT NULL AND fv.check_out_time IS NULL {scope_sql}",
        scope_args, one=True,
    )["c"]
    kpi_completed_today = db.query(
        f"SELECT COUNT(*) c FROM field_visits fv WHERE fv.visit_date = ? AND fv.status = 'Completed' {scope_sql}",
        [today] + scope_args, one=True,
    )["c"]
    kpi_avg_distance = db.query(
        f"SELECT AVG(fv.travel_distance_km) a FROM field_visits fv WHERE fv.travel_distance_km IS NOT NULL {scope_sql}",
        scope_args, one=True,
    )["a"] or 0

    employees = []
    if view_all:
        employees = db.query("SELECT id, employee_code, first_name, last_name FROM employees WHERE is_deleted=0 ORDER BY first_name, last_name")

    return render_template(
        "field/visits_list.html",
        rows=rows, total=total, page=page, pages=pages, per_page=per_page,
        from_date=from_date, to_date=to_date, employee_id=employee_id, employees=employees,
        view_all=view_all,
        kpi_today=kpi_today, kpi_in_field=kpi_in_field,
        kpi_completed_today=kpi_completed_today, kpi_avg_distance=kpi_avg_distance,
        can_create=has_permission("field.visits.create"),
    )


# ---------------------------------------------------------------------------
# Plan / view a visit
# ---------------------------------------------------------------------------

@bp.route("/visits/new", methods=("GET", "POST"))
@permission_required("field.visits.create")
def visit_new():
    view_all = has_permission("field.visits.view_all")
    employees = []
    if view_all:
        employees = db.query("SELECT id, employee_code, first_name, last_name FROM employees WHERE is_deleted=0 ORDER BY first_name, last_name")

    if request.method == "POST":
        if view_all:
            employee_id = request.form.get("employee_id", type=int) or (g.employee["id"] if g.employee else None)
        else:
            employee_id = g.employee["id"] if g.employee else None
        visit_date = request.form.get("visit_date", "").strip()
        customer_name = request.form.get("customer_name", "").strip()
        if not employee_id:
            flash("Your account is not linked to an employee record.", "error")
            return render_template("field/visit_form.html", employees=employees, view_all=view_all, today=today_iso())
        if not visit_date or not customer_name:
            flash("Visit date and customer name are required.", "error")
            return render_template("field/visit_form.html", employees=employees, view_all=view_all, today=today_iso())

        new_id = db.execute(
            """INSERT INTO field_visits (employee_id, visit_date, customer_name, purpose, status)
               VALUES (?,?,?,?,'Planned')""",
            (employee_id, visit_date, customer_name, request.form.get("purpose", "").strip() or None),
        )
        audit.log("field", "visits", new_id, "create", f"Planned field visit to {customer_name} on {visit_date}")
        flash("Field visit planned.", "success")
        return redirect(url_for("field.visit_view", id=new_id))

    return render_template("field/visit_form.html", employees=employees, view_all=view_all, today=today_iso())


@bp.route("/visits/<int:id>")
@permission_required("field.visits.view")
def visit_view(id):
    row = db.query(
        """SELECT fv.*, e.first_name, e.last_name, e.employee_code
           FROM field_visits fv JOIN employees e ON e.id = fv.employee_id
           WHERE fv.id=?""",
        (id,), one=True,
    )
    if row is None:
        flash("Field visit not found.", "error")
        return redirect(url_for("field.visits_list"))
    view_all = has_permission("field.visits.view_all")
    is_owner = g.employee is not None and g.employee["id"] == row["employee_id"]
    if not view_all and not is_owner:
        flash("You don't have permission to view this visit.", "error")
        return redirect(url_for("field.visits_list"))

    can_act = has_permission("field.visits.edit") and (view_all or is_owner)
    return render_template("field/visit_view.html", row=row, can_act=can_act, now=now_iso())


@bp.route("/my-visits")
@permission_required("field.visits.view")
def my_visits():
    if g.employee is None:
        flash("Your account is not linked to an employee record.", "error")
        return redirect(url_for("dashboard.index"))
    rows = db.query(
        "SELECT * FROM field_visits WHERE employee_id=? ORDER BY visit_date DESC, id DESC",
        (g.employee["id"],),
    )
    return render_template("field/my_visits.html", rows=rows)


# ---------------------------------------------------------------------------
# Check-in / check-out
# ---------------------------------------------------------------------------

@bp.route("/visits/<int:id>/checkin", methods=("POST",))
@permission_required("field.visits.edit")
def checkin(id):
    row = db.query("SELECT * FROM field_visits WHERE id=?", (id,), one=True)
    if row is None:
        flash("Field visit not found.", "error")
        return redirect(url_for("field.visits_list"))
    view_all = has_permission("field.visits.view_all")
    is_owner = g.employee is not None and g.employee["id"] == row["employee_id"]
    if not view_all and not is_owner:
        flash("You don't have permission to check in on this visit.", "error")
        return redirect(url_for("field.visits_list"))
    if row["status"] != "Planned":
        flash("Only a planned visit can be checked in.", "error")
        return redirect(url_for("field.visit_view", id=id))

    photo_path = _save_photo(request.files.get("photo"))
    db.execute(
        """UPDATE field_visits
           SET check_in_time=?, check_in_location=?, status='In Progress', photo_path=COALESCE(?, photo_path)
           WHERE id=?""",
        (now_iso(), request.form.get("check_in_location", "").strip() or None, photo_path, id),
    )
    audit.log("field", "visits", id, "update", f"Checked in on visit #{id}")
    flash("Checked in successfully.", "success")
    return redirect(url_for("field.visit_view", id=id))


@bp.route("/visits/<int:id>/checkout", methods=("POST",))
@permission_required("field.visits.edit")
def checkout(id):
    row = db.query("SELECT * FROM field_visits WHERE id=?", (id,), one=True)
    if row is None:
        flash("Field visit not found.", "error")
        return redirect(url_for("field.visits_list"))
    view_all = has_permission("field.visits.view_all")
    is_owner = g.employee is not None and g.employee["id"] == row["employee_id"]
    if not view_all and not is_owner:
        flash("You don't have permission to check out on this visit.", "error")
        return redirect(url_for("field.visits_list"))
    if row["status"] != "In Progress":
        flash("Only a visit that is in progress can be checked out.", "error")
        return redirect(url_for("field.visit_view", id=id))

    distance = request.form.get("travel_distance_km", "").strip()
    db.execute(
        """UPDATE field_visits
           SET check_out_time=?, check_out_location=?, travel_distance_km=?, remarks=?, status='Completed'
           WHERE id=?""",
        (
            now_iso(),
            request.form.get("check_out_location", "").strip() or None,
            float(distance) if distance else None,
            request.form.get("remarks", "").strip() or None,
            id,
        ),
    )
    audit.log("field", "visits", id, "update", f"Checked out on visit #{id}")
    flash("Checked out successfully.", "success")
    return redirect(url_for("field.visit_view", id=id))
