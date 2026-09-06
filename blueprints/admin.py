"""Administration module.

Owns the master-data lookup tables (departments, designations, locations,
shifts, leave types, holidays, claim types, document types) via crud.py's
generic CRUD engine, plus Company Settings, Users, Roles & Permissions and
the Audit Log viewer. Courses (Learning module) are intentionally NOT
managed here.
"""
import os
import uuid

from flask import Blueprint, g, request, render_template, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

import db
import audit
import config
import rbac
from auth import permission_required, has_permission, login_required
from crud import register_crud, EntityConfig, Field

bp = Blueprint("admin", __name__)


# ----------------------------------------------------------------------------
# MASTER DATA — generic CRUD registrations
# ----------------------------------------------------------------------------

register_crud(bp, EntityConfig(
    key="departments", table="departments", module="admin", entity="masterdata",
    name_singular="Department", name_plural="Departments", icon="building",
    order_by="name",
    fields=[
        Field("name", required=True, searchable=True),
        Field("code"),
        Field("parent_id", label="Parent Department", type="select", fk_table="departments", fk_label="name"),
        Field("head_employee_id", label="Head of Department", type="select", fk_table="employees", fk_label="first_name"),
        Field("is_active", type="checkbox", default=1),
    ],
))

register_crud(bp, EntityConfig(
    key="designations", table="designations", module="admin", entity="masterdata",
    name_singular="Designation", name_plural="Designations", icon="badge",
    order_by="title",
    fields=[
        Field("title", required=True, searchable=True),
        Field("department_id", label="Department", type="select", fk_table="departments", fk_label="name"),
        Field("level"),
        Field("is_active", type="checkbox", default=1),
    ],
))

register_crud(bp, EntityConfig(
    key="locations", table="locations", module="admin", entity="masterdata",
    name_singular="Location", name_plural="Locations", icon="map-pin",
    order_by="name",
    fields=[
        Field("name", required=True, searchable=True),
        Field("address"),
        Field("city"),
        Field("state"),
        Field("country"),
        Field("pincode"),
        Field("is_active", type="checkbox", default=1),
    ],
))

register_crud(bp, EntityConfig(
    key="shifts", table="shifts", module="attendance", entity="shifts",
    name_singular="Shift", name_plural="Shifts", icon="clock",
    order_by="name",
    fields=[
        Field("name", required=True, searchable=True),
        Field("start_time", help="24-hour format, e.g. 09:00"),
        Field("end_time", help="24-hour format, e.g. 18:00"),
        Field("break_minutes", type="number", default=60),
        Field("grace_minutes", type="number", default=10),
        Field("is_active", type="checkbox", default=1),
    ],
))

register_crud(bp, EntityConfig(
    key="leavetypes", table="leave_types", module="leave", entity="types",
    name_singular="Leave Type", name_plural="Leave Types", icon="umbrella",
    order_by="name",
    fields=[
        Field("name", required=True, searchable=True),
        Field("code", required=True),
        Field("days_per_year", type="number", default=12),
        Field("is_paid", type="checkbox", default=1),
        Field("carry_forward", type="checkbox"),
        Field("is_active", type="checkbox", default=1),
    ],
))

register_crud(bp, EntityConfig(
    key="holidays", table="holidays", module="leave", entity="holidays",
    name_singular="Holiday", name_plural="Holidays", icon="calendar",
    order_by="holiday_date DESC",
    fields=[
        Field("name", required=True, searchable=True),
        Field("holiday_date", type="date", required=True),
        Field("location_id", label="Location (optional)", type="select", fk_table="locations", fk_label="name"),
        Field("is_optional", type="checkbox"),
    ],
))

register_crud(bp, EntityConfig(
    key="claimtypes", table="claim_types", module="claims", entity="types",
    name_singular="Claim Type", name_plural="Claim Types", icon="credit-card",
    order_by="name",
    fields=[
        Field("name", required=True, searchable=True),
        Field("category"),
        Field("max_amount", type="number"),
        Field("is_active", type="checkbox", default=1),
    ],
))

register_crud(bp, EntityConfig(
    key="doctypes", table="document_types", module="documents", entity="types",
    name_singular="Document Type", name_plural="Document Types", icon="folder",
    order_by="name",
    fields=[
        Field("name", required=True, searchable=True),
        Field("category"),
        Field("requires_expiry", type="checkbox"),
    ],
))


MASTERDATA_LINKS = [
    ("departments", "Departments", "building"),
    ("designations", "Designations", "badge"),
    ("locations", "Locations", "map-pin"),
    ("shifts", "Shifts", "clock"),
    ("leavetypes", "Leave Types", "umbrella"),
    ("holidays", "Holidays", "calendar"),
    ("claimtypes", "Claim Types", "credit-card"),
    ("doctypes", "Document Types", "folder"),
]


# ----------------------------------------------------------------------------
# COMPANY SETTINGS — landing page
# ----------------------------------------------------------------------------

def _save_logo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    folder = os.path.join(config.UPLOAD_DIR, "company")
    os.makedirs(folder, exist_ok=True)
    safe_name = secure_filename(file_storage.filename)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    file_storage.save(os.path.join(folder, unique_name))
    return f"company/{unique_name}"


SETTINGS_TEXT_FIELDS = [
    "company_name", "address", "city", "state", "country", "pincode",
    "phone", "email", "website", "gstin", "pan", "currency_symbol",
]


@bp.route("/settings", methods=("GET", "POST"), endpoint="settings")
@login_required
def settings():
    if request.method == "POST" and not has_permission("admin.settings.edit"):
        flash("You don't have permission to do this (admin.settings.edit).", "error")
        return redirect(url_for("admin.settings"))
    if request.method == "GET" and not has_permission("admin.settings.view"):
        flash("You don't have permission to do this (admin.settings.view).", "error")
        return redirect(url_for("dashboard.index"))

    row = db.query("SELECT * FROM company_settings WHERE id=1", one=True)
    if row is None:
        db.execute("INSERT INTO company_settings (id, company_name) VALUES (1, 'Your Company')")
        row = db.query("SELECT * FROM company_settings WHERE id=1", one=True)

    if request.method == "POST":
        data = {f: (request.form.get(f, "").strip() or None) for f in SETTINGS_TEXT_FIELDS}
        try:
            fy_month = int(request.form.get("fiscal_year_start_month") or 4)
        except ValueError:
            fy_month = 4
        fy_month = min(12, max(1, fy_month))

        logo_file = request.files.get("logo")
        logo_path = _save_logo(logo_file)

        sets = [f"{c}=?" for c in SETTINGS_TEXT_FIELDS] + ["fiscal_year_start_month=?", "updated_at=CURRENT_TIMESTAMP"]
        values = [data[c] for c in SETTINGS_TEXT_FIELDS] + [fy_month]
        if logo_path:
            sets.append("logo_path=?")
            values.append(logo_path)
        db.execute(f"UPDATE company_settings SET {','.join(sets)} WHERE id=1", values)
        audit.log("admin", "settings", 1, "update", "Updated company settings")
        flash("Company settings updated successfully.", "success")
        return redirect(url_for("admin.settings"))

    counts = {}
    for key, _, _ in MASTERDATA_LINKS:
        table = {
            "departments": "departments", "designations": "designations", "locations": "locations",
            "shifts": "shifts", "leavetypes": "leave_types", "holidays": "holidays",
            "claimtypes": "claim_types", "doctypes": "document_types",
        }[key]
        counts[key] = db.query(f"SELECT COUNT(*) c FROM {table}", one=True)["c"]

    user_count = db.query("SELECT COUNT(*) c FROM users", one=True)["c"]
    role_count = db.query("SELECT COUNT(*) c FROM roles", one=True)["c"]
    audit_count = db.query("SELECT COUNT(*) c FROM audit_log", one=True)["c"]

    return render_template(
        "admin/settings.html", row=row, months=range(1, 13),
        masterdata_links=MASTERDATA_LINKS, counts=counts,
        user_count=user_count, role_count=role_count, audit_count=audit_count,
        can_edit=has_permission("admin.settings.edit"),
    )


# ----------------------------------------------------------------------------
# USERS
# ----------------------------------------------------------------------------

@bp.route("/users", endpoint="users_list")
@permission_required("admin.users.view")
def users_list():
    rows = db.query(
        """SELECT u.*, r.name AS role_name,
                  (e.first_name || ' ' || e.last_name) AS employee_name
           FROM users u
           JOIN roles r ON r.id = u.role_id
           LEFT JOIN employees e ON e.id = u.employee_id
           ORDER BY u.username"""
    )
    return render_template(
        "admin/users_list.html", rows=rows,
        can_create=has_permission("admin.users.create"),
        can_edit=has_permission("admin.users.edit"),
        can_delete=has_permission("admin.users.delete"),
    )


def _user_form_options():
    roles = db.query("SELECT id, name FROM roles ORDER BY name")
    employees = db.query(
        "SELECT id, (first_name || ' ' || last_name || ' (' || employee_code || ')') AS name "
        "FROM employees WHERE is_deleted=0 ORDER BY first_name"
    )
    return roles, employees


@bp.route("/users/new", methods=("GET", "POST"), endpoint="user_new")
@permission_required("admin.users.create")
def user_new():
    roles, employees = _user_form_options()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip() or None
        phone = request.form.get("phone", "").strip() or None
        role_id = request.form.get("role_id", type=int)
        employee_id = request.form.get("employee_id", type=int) or None
        password = request.form.get("password", "")

        if not username or not full_name or not role_id or not password:
            flash("Username, full name, role and password are required.", "error")
            return render_template("admin/user_form.html", row=None, roles=roles, employees=employees)

        existing = db.query("SELECT id FROM users WHERE username=?", (username,), one=True)
        if existing:
            flash("That username is already taken.", "error")
            return render_template("admin/user_form.html", row=None, roles=roles, employees=employees)

        new_id = db.execute(
            """INSERT INTO users (username, password_hash, full_name, email, phone, role_id, employee_id, is_active)
               VALUES (?,?,?,?,?,?,?,1)""",
            (username, generate_password_hash(password), full_name, email, phone, role_id, employee_id),
        )
        audit.log("admin", "users", new_id, "create", f"Created user '{username}'")
        flash("User created successfully.", "success")
        return redirect(url_for("admin.users_list"))

    return render_template("admin/user_form.html", row=None, roles=roles, employees=employees)


@bp.route("/users/<int:id>/edit", methods=("GET", "POST"), endpoint="user_edit")
@permission_required("admin.users.edit")
def user_edit(id):
    row = db.query("SELECT * FROM users WHERE id=?", (id,), one=True)
    if row is None:
        flash("User not found.", "error")
        return redirect(url_for("admin.users_list"))
    roles, employees = _user_form_options()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip() or None
        phone = request.form.get("phone", "").strip() or None
        role_id = request.form.get("role_id", type=int)
        employee_id = request.form.get("employee_id", type=int) or None
        password = request.form.get("password", "")

        if not username or not full_name or not role_id:
            flash("Username, full name and role are required.", "error")
            return render_template("admin/user_form.html", row=row, roles=roles, employees=employees)

        dupe = db.query("SELECT id FROM users WHERE username=? AND id!=?", (username, id), one=True)
        if dupe:
            flash("That username is already taken.", "error")
            return render_template("admin/user_form.html", row=row, roles=roles, employees=employees)

        if password:
            db.execute(
                """UPDATE users SET username=?, password_hash=?, full_name=?, email=?, phone=?,
                       role_id=?, employee_id=? WHERE id=?""",
                (username, generate_password_hash(password), full_name, email, phone, role_id, employee_id, id),
            )
        else:
            db.execute(
                """UPDATE users SET username=?, full_name=?, email=?, phone=?,
                       role_id=?, employee_id=? WHERE id=?""",
                (username, full_name, email, phone, role_id, employee_id, id),
            )
        audit.log("admin", "users", id, "update", f"Updated user '{username}'")
        flash("User updated successfully.", "success")
        return redirect(url_for("admin.users_list"))

    return render_template("admin/user_form.html", row=row, roles=roles, employees=employees)


@bp.route("/users/<int:id>/toggle-active", methods=("POST",), endpoint="user_deactivate")
@permission_required("admin.users.delete")
def user_deactivate(id):
    row = db.query("SELECT * FROM users WHERE id=?", (id,), one=True)
    if row is None:
        flash("User not found.", "error")
        return redirect(url_for("admin.users_list"))
    new_state = 0 if row["is_active"] else 1
    if new_state == 0 and g.user and g.user["id"] == id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users_list"))
    db.execute("UPDATE users SET is_active=? WHERE id=?", (new_state, id))
    audit.log("admin", "users", id, "update", f"{'Activated' if new_state else 'Deactivated'} user '{row['username']}'")
    flash(f"User {'activated' if new_state else 'deactivated'}.", "success")
    return redirect(url_for("admin.users_list"))


# ----------------------------------------------------------------------------
# ROLES & PERMISSIONS
# ----------------------------------------------------------------------------

@bp.route("/roles", endpoint="roles_list")
@permission_required("admin.roles.view")
def roles_list():
    rows = db.query(
        """SELECT r.*,
                  (SELECT COUNT(*) FROM users u WHERE u.role_id = r.id) AS user_count,
                  (SELECT COUNT(*) FROM role_permissions rp WHERE rp.role_id = r.id) AS perm_count
           FROM roles r ORDER BY r.name"""
    )
    return render_template("admin/roles_list.html", rows=rows, can_edit=has_permission("admin.roles.edit"))


@bp.route("/roles/<int:id>/permissions", methods=("GET", "POST"), endpoint="role_permissions")
@permission_required("admin.roles.edit")
def role_permissions(id):
    role = db.query("SELECT * FROM roles WHERE id=?", (id,), one=True)
    if role is None:
        flash("Role not found.", "error")
        return redirect(url_for("admin.roles_list"))

    if role["name"] == "Super Admin":
        return render_template("admin/role_permissions.html", role=role, super_admin=True, groups=None)

    if request.method == "POST":
        selected_codes = request.form.getlist("perm")
        all_perms = db.query("SELECT id, code FROM permissions")
        code_to_id = {p["code"]: p["id"] for p in all_perms}
        db.execute("DELETE FROM role_permissions WHERE role_id=?", (id,))
        writes = [(id, code_to_id[c]) for c in selected_codes if c in code_to_id]
        if writes:
            db.executemany("INSERT INTO role_permissions (role_id, permission_id) VALUES (?,?)", writes)
        audit.log("admin", "roles", id, "update", f"Updated permissions for role '{role['name']}' ({len(writes)} grants)")
        flash(f"Permissions updated for {role['name']}.", "success")
        return redirect(url_for("admin.role_permissions", id=id))

    all_perms = db.query("SELECT * FROM permissions ORDER BY module, code")
    granted = db.query("SELECT permission_id FROM role_permissions WHERE role_id=?", (id,))
    granted_ids = {r["permission_id"] for r in granted}
    granted_codes = {p["code"] for p in all_perms if p["id"] in granted_ids}

    # Group into module -> entity -> {action: permission row}
    groups = {}
    for p in all_perms:
        parts = p["code"].split(".")
        entity = parts[1] if len(parts) > 1 else p["code"]
        action = parts[2] if len(parts) > 2 else ""
        groups.setdefault(p["module"], {}).setdefault(entity, {})[action] = p

    entity_labels = {}
    for module, entities in rbac.MODULES.items():
        entity_labels[module] = entities

    return render_template(
        "admin/role_permissions.html", role=role, super_admin=False,
        groups=groups, actions=rbac.ACTIONS, granted_codes=granted_codes,
        entity_labels=entity_labels,
    )


# ----------------------------------------------------------------------------
# AUDIT LOG
# ----------------------------------------------------------------------------

@bp.route("/audit-log", endpoint="audit_log")
@permission_required("admin.audit.view")
def audit_log():
    entity_type = request.args.get("entity_type", "").strip()
    user_id = request.args.get("user_id", type=int)

    where = []
    args = []
    if entity_type:
        where.append("a.entity_type LIKE ?")
        args.append(f"%{entity_type}%")
    if user_id:
        where.append("a.user_id = ?")
        args.append(user_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = db.query(
        f"""SELECT a.*, u.full_name AS actor_name, u.username AS actor_username
            FROM audit_log a
            LEFT JOIN users u ON u.id = a.user_id
            {where_sql}
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT 200""",
        args,
    )
    users = db.query("SELECT id, full_name FROM users ORDER BY full_name")

    return render_template(
        "admin/audit_log.html", rows=rows, users=users,
        entity_type=entity_type, user_id=user_id,
    )
