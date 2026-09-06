"""Employees module — the People/HR-core blueprint.

Owns: employees, employee_education, employee_experience, employee_documents,
employee_assets. Every other module hangs off employees.id, so this module
provides the employee directory, full profile (with tabbed sections that
read-only-summarize other modules' tables), and the create/edit/deactivate
workflow. See rbac.py MODULES["employees"] for the permission entities:
employees.employees, employees.documents, employees.assets.
"""
import math
import os
import secrets

from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from werkzeug.utils import secure_filename

import config
import db
import audit
import notify
from auth import permission_required, has_permission
from helpers import paginate_args, csv_response

bp = Blueprint("employees", __name__)

# ---------------------------------------------------------------------------
# Static option lists used across the create/edit form and filters
# ---------------------------------------------------------------------------
GENDERS = ["Male", "Female", "Other"]
MARITAL_STATUSES = ["Single", "Married", "Divorced", "Widowed"]
BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Contract", "Intern"]
EMPLOYMENT_STATUSES = ["Active", "On Leave", "Resigned", "Terminated"]
ASSET_CONDITIONS = ["New", "Good", "Fair", "Damaged", "Lost"]
DOC_TYPES = [
    "ID Proof", "Address Proof", "Educational Certificate", "Offer Letter",
    "Resignation Letter", "Contract", "Resume", "PAN Card", "Aadhaar Card",
    "Bank Proof", "Other",
]

UPLOAD_SUBDIR = "employees"

EMPLOYEE_FORM_COLUMNS = [
    "first_name", "last_name", "gender", "dob", "marital_status", "blood_group",
    "personal_email", "personal_phone", "emergency_contact_name", "emergency_contact_phone",
    "department_id", "designation_id", "location_id", "reporting_manager_id",
    "employment_type", "employment_status", "date_of_joining", "date_of_confirmation", "date_of_exit",
    "work_email", "work_phone",
    "current_address", "permanent_address", "city", "state", "country", "pincode",
    "bank_name", "bank_account_no", "bank_ifsc", "pan_number", "aadhaar_number", "uan_number", "pf_number",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _can_access_employee(employee_id, base_perm):
    """base_perm e.g. 'employees.employees' / 'employees.documents' / 'employees.assets'.
    Self-service scoping: view_all (or equivalent) sees everyone, otherwise
    only the logged-in user's own linked employee record."""
    if has_permission(f"{base_perm}.view_all"):
        return True
    return g.employee is not None and g.employee["id"] == employee_id


def _save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    dest_dir = os.path.join(config.UPLOAD_DIR, UPLOAD_SUBDIR)
    os.makedirs(dest_dir, exist_ok=True)
    fname = f"{secrets.token_hex(8)}_{secure_filename(file_storage.filename)}"
    file_storage.save(os.path.join(dest_dir, fname))
    return f"{UPLOAD_SUBDIR}/{fname}"


def _form_options(exclude_id=None):
    departments = db.query("SELECT * FROM departments WHERE is_active=1 ORDER BY name")
    designations = db.query("SELECT * FROM designations WHERE is_active=1 ORDER BY title")
    locations = db.query("SELECT * FROM locations WHERE is_active=1 ORDER BY name")
    if exclude_id:
        managers = db.query(
            "SELECT * FROM employees WHERE is_deleted=0 AND id != ? ORDER BY first_name, last_name",
            (exclude_id,),
        )
    else:
        managers = db.query("SELECT * FROM employees WHERE is_deleted=0 ORDER BY first_name, last_name")
    return dict(
        departments=departments, designations=designations, locations=locations, managers=managers,
        genders=GENDERS, marital_statuses=MARITAL_STATUSES, blood_groups=BLOOD_GROUPS,
        employment_types=EMPLOYMENT_TYPES, employment_statuses=EMPLOYMENT_STATUSES,
    )


def _s(name):
    v = (request.form.get(name) or "").strip()
    return v or None


def _i(name):
    v = (request.form.get(name) or "").strip()
    try:
        return int(v) if v else None
    except ValueError:
        return None


def _collect_employee_form():
    return {
        "first_name": (request.form.get("first_name") or "").strip(),
        "last_name": (request.form.get("last_name") or "").strip(),
        "gender": _s("gender"),
        "dob": _s("dob"),
        "marital_status": _s("marital_status"),
        "blood_group": _s("blood_group"),
        "personal_email": _s("personal_email"),
        "personal_phone": _s("personal_phone"),
        "emergency_contact_name": _s("emergency_contact_name"),
        "emergency_contact_phone": _s("emergency_contact_phone"),
        "department_id": _i("department_id"),
        "designation_id": _i("designation_id"),
        "location_id": _i("location_id"),
        "reporting_manager_id": _i("reporting_manager_id"),
        "employment_type": (request.form.get("employment_type") or "Full-time").strip() or "Full-time",
        "employment_status": (request.form.get("employment_status") or "Active").strip() or "Active",
        "date_of_joining": _s("date_of_joining"),
        "date_of_confirmation": _s("date_of_confirmation"),
        "date_of_exit": _s("date_of_exit"),
        "work_email": _s("work_email"),
        "work_phone": _s("work_phone"),
        "current_address": _s("current_address"),
        "permanent_address": _s("permanent_address"),
        "city": _s("city"),
        "state": _s("state"),
        "country": _s("country"),
        "pincode": _s("pincode"),
        "bank_name": _s("bank_name"),
        "bank_account_no": _s("bank_account_no"),
        "bank_ifsc": _s("bank_ifsc"),
        "pan_number": _s("pan_number"),
        "aadhaar_number": _s("aadhaar_number"),
        "uan_number": _s("uan_number"),
        "pf_number": _s("pf_number"),
    }


# ---------------------------------------------------------------------------
# Directory (list) + create + view + edit + deactivate
# ---------------------------------------------------------------------------
@bp.route("", endpoint="list_view")
@permission_required("employees.employees.view")
def list_view():
    if not has_permission("employees.employees.view_all"):
        if g.employee:
            return redirect(url_for("employees.view", id=g.employee["id"]))
        flash("No employee profile is linked to your account.", "error")
        return redirect(url_for("dashboard.index"))

    q = request.args.get("q", "").strip()
    department_id = request.args.get("department_id", type=int)
    designation_id = request.args.get("designation_id", type=int)
    location_id = request.args.get("location_id", type=int)
    employment_status = request.args.get("employment_status", "").strip()
    page, per_page = paginate_args(request)

    where = ["e.is_deleted = 0"]
    args = []
    if q:
        where.append(
            "(e.first_name LIKE ? OR e.last_name LIKE ? OR (e.first_name || ' ' || e.last_name) LIKE ? "
            "OR e.employee_code LIKE ? OR e.personal_email LIKE ? OR e.work_email LIKE ? "
            "OR e.personal_phone LIKE ? OR e.work_phone LIKE ?)"
        )
        like = f"%{q}%"
        args.extend([like] * 8)
    if department_id:
        where.append("e.department_id = ?")
        args.append(department_id)
    if designation_id:
        where.append("e.designation_id = ?")
        args.append(designation_id)
    if location_id:
        where.append("e.location_id = ?")
        args.append(location_id)
    if employment_status:
        where.append("e.employment_status = ?")
        args.append(employment_status)
    where_sql = "WHERE " + " AND ".join(where)

    from_sql = f"""FROM employees e
        LEFT JOIN departments d ON d.id = e.department_id
        LEFT JOIN designations ds ON ds.id = e.designation_id
        LEFT JOIN locations l ON l.id = e.location_id
        LEFT JOIN employees m ON m.id = e.reporting_manager_id
        {where_sql}"""

    total = db.query(f"SELECT COUNT(*) c {from_sql}", args, one=True)["c"]

    if request.args.get("export") == "csv" and has_permission("employees.employees.export"):
        all_rows = db.query(
            f"""SELECT e.*, d.name as department_name, ds.title as designation_name, l.name as location_name
                {from_sql} ORDER BY e.first_name, e.last_name""",
            args,
        )
        header = ["Employee Code", "Name", "Department", "Designation", "Location",
                  "Employment Type", "Employment Status", "Joining Date", "Work Email", "Work Phone"]
        out = [
            [r["employee_code"], f"{r['first_name']} {r['last_name']}", r["department_name"] or "",
             r["designation_name"] or "", r["location_name"] or "", r["employment_type"],
             r["employment_status"], r["date_of_joining"] or "", r["work_email"] or "", r["work_phone"] or ""]
            for r in all_rows
        ]
        audit.log("employees", "employees", None, "export", "Exported employee directory to CSV")
        return csv_response("employees.csv", header, out)

    offset = (page - 1) * per_page
    rows = db.query(
        f"""SELECT e.*, d.name as department_name, ds.title as designation_name, l.name as location_name,
                   (m.first_name || ' ' || m.last_name) as manager_name
            {from_sql}
            ORDER BY e.first_name, e.last_name
            LIMIT ? OFFSET ?""",
        args + [per_page, offset],
    )
    pages = max(1, math.ceil(total / per_page))
    departments = db.query("SELECT * FROM departments WHERE is_active=1 ORDER BY name")
    designations = db.query("SELECT * FROM designations WHERE is_active=1 ORDER BY title")
    locations = db.query("SELECT * FROM locations WHERE is_active=1 ORDER BY name")
    return render_template(
        "employees/list.html", rows=rows, total=total, page=page, pages=pages, per_page=per_page,
        q=q, department_id=department_id, designation_id=designation_id, location_id=location_id,
        employment_status=employment_status, departments=departments, designations=designations,
        locations=locations, employment_statuses=EMPLOYMENT_STATUSES,
        can_create=has_permission("employees.employees.create"),
        can_export=has_permission("employees.employees.export"),
    )


@bp.route("/new", methods=["GET", "POST"], endpoint="new")
@permission_required("employees.employees.create")
def new():
    if request.method == "POST":
        data = _collect_employee_form()
        if not data["first_name"] or not data["last_name"]:
            flash("First name and last name are required.", "error")
            options = _form_options()
            return render_template("employees/form.html", row=data, is_edit=False, emp_id=None, **options)
        data["photo_path"] = _save_upload(request.files.get("photo"))
        data["employee_code"] = db.next_sequence("EMPLOYEE", "EMP", 4)
        data["created_by"] = g.user["id"]
        cols = list(data.keys())
        placeholders = ",".join(["?"] * len(cols))
        new_id = db.execute(
            f"INSERT INTO employees ({','.join(cols)}) VALUES ({placeholders})",
            [data[c] for c in cols],
        )
        audit.log(
            "employees", "employees", new_id, "create",
            f"Created employee {data['first_name']} {data['last_name']} ({data['employee_code']})",
        )
        if data["reporting_manager_id"]:
            notify.notify_manager(
                new_id, "New team member",
                f"{data['first_name']} {data['last_name']} has joined your team.",
                "info", url_for("employees.view", id=new_id),
            )
        flash(f"Employee {data['first_name']} {data['last_name']} created successfully.", "success")
        return redirect(url_for("employees.view", id=new_id))
    options = _form_options()
    return render_template("employees/form.html", row=None, is_edit=False, emp_id=None, **options)


@bp.route("/<int:id>", endpoint="view")
@permission_required("employees.employees.view")
def view(id):
    emp = db.query(
        """SELECT e.*, d.name as department_name, ds.title as designation_name, l.name as location_name,
                  (m.first_name || ' ' || m.last_name) as manager_name
           FROM employees e
           LEFT JOIN departments d ON d.id = e.department_id
           LEFT JOIN designations ds ON ds.id = e.designation_id
           LEFT JOIN locations l ON l.id = e.location_id
           LEFT JOIN employees m ON m.id = e.reporting_manager_id
           WHERE e.id=? AND e.is_deleted=0""",
        (id,), one=True,
    )
    if emp is None:
        flash("Employee not found.", "error")
        return redirect(url_for("employees.list_view"))
    if not _can_access_employee(id, "employees.employees"):
        flash("You don't have permission to view this employee.", "error")
        return redirect(url_for("dashboard.index"))

    tab = request.args.get("tab", "profile")
    user_account = db.query(
        """SELECT u.username, u.is_active, r.name as role_name FROM users u
           JOIN roles r ON r.id=u.role_id WHERE u.employee_id=?""",
        (id,), one=True,
    )

    ctx = {}
    if tab == "education":
        ctx["education_rows"] = db.query(
            "SELECT * FROM employee_education WHERE employee_id=? ORDER BY end_year DESC, start_year DESC", (id,)
        )
    elif tab == "experience":
        ctx["experience_rows"] = db.query(
            "SELECT * FROM employee_experience WHERE employee_id=? ORDER BY start_date DESC", (id,)
        )
    elif tab == "documents":
        ctx["document_rows"] = db.query(
            "SELECT * FROM employee_documents WHERE employee_id=? ORDER BY uploaded_at DESC", (id,)
        )
        ctx["doc_types"] = DOC_TYPES
    elif tab == "attendance":
        ctx["attendance_rows"] = db.query(
            "SELECT * FROM attendance WHERE employee_id=? ORDER BY date DESC LIMIT 10", (id,)
        )
    elif tab == "leave":
        ctx["leave_rows"] = db.query(
            """SELECT lr.*, lt.name as leave_type_name FROM leave_requests lr
               JOIN leave_types lt ON lt.id=lr.leave_type_id
               WHERE lr.employee_id=? ORDER BY lr.created_at DESC LIMIT 5""",
            (id,),
        )
    elif tab == "payroll":
        ctx["payslip_rows"] = db.query(
            """SELECT p.*, pr.period_month, pr.period_year, pr.run_number FROM payslips p
               JOIN payroll_runs pr ON pr.id=p.payroll_run_id
               WHERE p.employee_id=? ORDER BY pr.period_year DESC, pr.period_month DESC LIMIT 3""",
            (id,),
        )
    elif tab == "performance":
        ctx["appraisal"] = db.query(
            """SELECT a.*, c.name as cycle_name FROM appraisals a
               JOIN appraisal_cycles c ON c.id=a.cycle_id
               WHERE a.employee_id=? ORDER BY a.id DESC LIMIT 1""",
            (id,), one=True,
        )
        ctx["goal_rows"] = db.query("SELECT * FROM goals WHERE employee_id=? ORDER BY id DESC LIMIT 5", (id,))
    elif tab == "training":
        ctx["training_rows"] = db.query(
            """SELECT te.*, ts.session_date, c.title as course_title FROM training_enrollments te
               JOIN training_sessions ts ON ts.id=te.session_id
               JOIN courses c ON c.id=ts.course_id
               WHERE te.employee_id=? ORDER BY ts.session_date DESC LIMIT 10""",
            (id,),
        )
    elif tab == "claims":
        ctx["claim_rows"] = db.query(
            """SELECT ec.*, ct.name as claim_type_name FROM expense_claims ec
               JOIN claim_types ct ON ct.id=ec.claim_type_id
               WHERE ec.employee_id=? ORDER BY ec.created_at DESC LIMIT 5""",
            (id,),
        )
    elif tab == "assets":
        ctx["asset_rows"] = db.query(
            "SELECT * FROM employee_assets WHERE employee_id=? ORDER BY issued_date DESC", (id,)
        )
        ctx["asset_conditions"] = ASSET_CONDITIONS
    elif tab == "activity":
        ctx["activity_rows"] = db.query(
            """SELECT al.*, u.full_name as user_name FROM audit_log al
               LEFT JOIN users u ON u.id=al.user_id
               WHERE al.entity_type LIKE 'employees.%' AND al.entity_id=?
               ORDER BY al.created_at DESC LIMIT 50""",
            (id,),
        )

    can_edit_profile = has_permission("employees.employees.edit") and _can_access_employee(id, "employees.employees")
    return render_template(
        "employees/view.html", emp=emp, tab=tab, user_account=user_account,
        can_edit=can_edit_profile,
        can_delete=has_permission("employees.employees.delete"),
        can_edit_profile=can_edit_profile,
        can_view_documents=has_permission("employees.documents.view"),
        can_add_document=has_permission("employees.documents.create") and _can_access_employee(id, "employees.documents"),
        can_delete_document=has_permission("employees.documents.delete"),
        can_view_assets=has_permission("employees.assets.view"),
        can_add_asset=has_permission("employees.assets.create") and _can_access_employee(id, "employees.assets"),
        can_delete_asset=has_permission("employees.assets.delete"),
        **ctx,
    )


@bp.route("/<int:id>/edit", methods=["GET", "POST"], endpoint="edit")
@permission_required("employees.employees.edit")
def edit(id):
    emp = db.query("SELECT * FROM employees WHERE id=? AND is_deleted=0", (id,), one=True)
    if emp is None:
        flash("Employee not found.", "error")
        return redirect(url_for("employees.list_view"))
    if not _can_access_employee(id, "employees.employees"):
        flash("You don't have permission to edit this employee.", "error")
        return redirect(url_for("employees.view", id=id))

    if request.method == "POST":
        data = _collect_employee_form()
        if not data["first_name"] or not data["last_name"]:
            flash("First name and last name are required.", "error")
            options = _form_options(exclude_id=id)
            return render_template(
                "employees/form.html", row=data, is_edit=True, emp_id=id,
                emp_code=emp["employee_code"], **options,
            )
        photo_path = _save_upload(request.files.get("photo"))
        sets = [f"{c}=?" for c in data.keys()]
        vals = list(data.values())
        if photo_path:
            sets.append("photo_path=?")
            vals.append(photo_path)
        sets.append("updated_at=datetime('now')")
        vals.append(id)
        db.execute(f"UPDATE employees SET {','.join(sets)} WHERE id=?", vals)
        audit.log("employees", "employees", id, "update", f"Updated employee {data['first_name']} {data['last_name']}")
        flash("Employee updated successfully.", "success")
        return redirect(url_for("employees.view", id=id))

    options = _form_options(exclude_id=id)
    return render_template(
        "employees/form.html", row=emp, is_edit=True, emp_id=id, emp_code=emp["employee_code"], **options
    )


@bp.route("/<int:id>/deactivate", methods=["POST"], endpoint="deactivate")
@permission_required("employees.employees.delete")
def deactivate(id):
    emp = db.query("SELECT * FROM employees WHERE id=? AND is_deleted=0", (id,), one=True)
    if emp is None:
        flash("Employee not found.", "error")
        return redirect(url_for("employees.list_view"))
    status = (request.form.get("status") or "Resigned").strip()
    if status not in EMPLOYMENT_STATUSES:
        status = "Resigned"
    if status in ("Resigned", "Terminated"):
        db.execute(
            "UPDATE employees SET employment_status=?, date_of_exit=date('now'), updated_at=datetime('now') WHERE id=?",
            (status, id),
        )
    else:
        db.execute(
            "UPDATE employees SET employment_status=?, updated_at=datetime('now') WHERE id=?",
            (status, id),
        )
    audit.log(
        "employees", "employees", id, "status_change",
        f"Changed employment status of {emp['first_name']} {emp['last_name']} to {status}",
    )
    notify.notify_role(
        "HR Admin", "Employee status changed",
        f"{emp['first_name']} {emp['last_name']} is now {status}.",
        "warning", url_for("employees.view", id=id),
    )
    flash(f"Employee status updated to {status}.", "success")
    return redirect(url_for("employees.view", id=id))


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------
@bp.route("/<int:id>/education/add", methods=["POST"], endpoint="education_add")
@permission_required("employees.employees.edit")
def education_add(id):
    emp = db.query("SELECT id FROM employees WHERE id=? AND is_deleted=0", (id,), one=True)
    if emp is None:
        flash("Employee not found.", "error")
        return redirect(url_for("employees.list_view"))
    if not _can_access_employee(id, "employees.employees"):
        flash("You don't have permission to do this.", "error")
        return redirect(url_for("employees.view", id=id))
    degree = (request.form.get("degree") or "").strip()
    if not degree:
        flash("Degree is required.", "error")
        return redirect(url_for("employees.view", id=id, tab="education"))
    db.execute(
        """INSERT INTO employee_education (employee_id, degree, institution, field_of_study, start_year, end_year, grade)
           VALUES (?,?,?,?,?,?,?)""",
        (id, degree, _s("institution"), _s("field_of_study"), _i("start_year"), _i("end_year"), _s("grade")),
    )
    audit.log("employees", "employees", id, "create", f"Added education record: {degree}")
    flash("Education record added.", "success")
    return redirect(url_for("employees.view", id=id, tab="education"))


@bp.route("/education/<int:id>/delete", methods=["POST"], endpoint="education_delete")
@permission_required("employees.employees.edit")
def education_delete(id):
    row = db.query("SELECT * FROM employee_education WHERE id=?", (id,), one=True)
    if row is None:
        flash("Record not found.", "error")
        return redirect(url_for("employees.list_view"))
    emp_id = row["employee_id"]
    if not _can_access_employee(emp_id, "employees.employees"):
        flash("You don't have permission to do this.", "error")
        return redirect(url_for("employees.view", id=emp_id))
    db.execute("DELETE FROM employee_education WHERE id=?", (id,))
    audit.log("employees", "employees", emp_id, "delete", f"Removed education record: {row['degree']}")
    flash("Education record removed.", "success")
    return redirect(url_for("employees.view", id=emp_id, tab="education"))


# ---------------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------------
@bp.route("/<int:id>/experience/add", methods=["POST"], endpoint="experience_add")
@permission_required("employees.employees.edit")
def experience_add(id):
    emp = db.query("SELECT id FROM employees WHERE id=? AND is_deleted=0", (id,), one=True)
    if emp is None:
        flash("Employee not found.", "error")
        return redirect(url_for("employees.list_view"))
    if not _can_access_employee(id, "employees.employees"):
        flash("You don't have permission to do this.", "error")
        return redirect(url_for("employees.view", id=id))
    company_name = (request.form.get("company_name") or "").strip()
    if not company_name:
        flash("Company name is required.", "error")
        return redirect(url_for("employees.view", id=id, tab="experience"))
    db.execute(
        """INSERT INTO employee_experience (employee_id, company_name, designation, start_date, end_date, description)
           VALUES (?,?,?,?,?,?)""",
        (id, company_name, _s("designation"), _s("start_date"), _s("end_date"), _s("description")),
    )
    audit.log("employees", "employees", id, "create", f"Added experience record: {company_name}")
    flash("Experience record added.", "success")
    return redirect(url_for("employees.view", id=id, tab="experience"))


@bp.route("/experience/<int:id>/delete", methods=["POST"], endpoint="experience_delete")
@permission_required("employees.employees.edit")
def experience_delete(id):
    row = db.query("SELECT * FROM employee_experience WHERE id=?", (id,), one=True)
    if row is None:
        flash("Record not found.", "error")
        return redirect(url_for("employees.list_view"))
    emp_id = row["employee_id"]
    if not _can_access_employee(emp_id, "employees.employees"):
        flash("You don't have permission to do this.", "error")
        return redirect(url_for("employees.view", id=emp_id))
    db.execute("DELETE FROM employee_experience WHERE id=?", (id,))
    audit.log("employees", "employees", emp_id, "delete", f"Removed experience record: {row['company_name']}")
    flash("Experience record removed.", "success")
    return redirect(url_for("employees.view", id=emp_id, tab="experience"))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@bp.route("/<int:id>/documents/add", methods=["POST"], endpoint="document_add")
@permission_required("employees.documents.create")
def document_add(id):
    emp = db.query("SELECT id FROM employees WHERE id=? AND is_deleted=0", (id,), one=True)
    if emp is None:
        flash("Employee not found.", "error")
        return redirect(url_for("employees.list_view"))
    if not _can_access_employee(id, "employees.documents"):
        flash("You don't have permission to do this.", "error")
        return redirect(url_for("employees.view", id=id))
    doc_type = (request.form.get("doc_type") or "").strip()
    title = (request.form.get("title") or "").strip()
    if not doc_type or not title:
        flash("Document type and title are required.", "error")
        return redirect(url_for("employees.view", id=id, tab="documents"))
    file_path = _save_upload(request.files.get("file"))
    db.execute(
        """INSERT INTO employee_documents (employee_id, doc_type, title, file_path, expiry_date)
           VALUES (?,?,?,?,?)""",
        (id, doc_type, title, file_path, _s("expiry_date")),
    )
    audit.log("employees", "documents", id, "create", f"Uploaded document '{title}' ({doc_type})")
    flash("Document uploaded.", "success")
    return redirect(url_for("employees.view", id=id, tab="documents"))


@bp.route("/documents/<int:id>/delete", methods=["POST"], endpoint="document_delete")
@permission_required("employees.documents.delete")
def document_delete(id):
    row = db.query("SELECT * FROM employee_documents WHERE id=?", (id,), one=True)
    if row is None:
        flash("Document not found.", "error")
        return redirect(url_for("employees.list_view"))
    emp_id = row["employee_id"]
    db.execute("DELETE FROM employee_documents WHERE id=?", (id,))
    audit.log("employees", "documents", emp_id, "delete", f"Deleted document '{row['title']}'")
    flash("Document deleted.", "success")
    return redirect(url_for("employees.view", id=emp_id, tab="documents"))


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
@bp.route("/<int:id>/assets/add", methods=["POST"], endpoint="asset_add")
@permission_required("employees.assets.create")
def asset_add(id):
    emp = db.query("SELECT id FROM employees WHERE id=? AND is_deleted=0", (id,), one=True)
    if emp is None:
        flash("Employee not found.", "error")
        return redirect(url_for("employees.list_view"))
    if not _can_access_employee(id, "employees.assets"):
        flash("You don't have permission to do this.", "error")
        return redirect(url_for("employees.view", id=id))
    asset_name = (request.form.get("asset_name") or "").strip()
    if not asset_name:
        flash("Asset name is required.", "error")
        return redirect(url_for("employees.view", id=id, tab="assets"))
    db.execute(
        """INSERT INTO employee_assets (employee_id, asset_name, asset_tag, issued_date, return_date, condition, remarks)
           VALUES (?,?,?,?,?,?,?)""",
        (id, asset_name, _s("asset_tag"), _s("issued_date"), _s("return_date"), _s("condition"), _s("remarks")),
    )
    audit.log("employees", "assets", id, "create", f"Issued asset: {asset_name}")
    flash("Asset added.", "success")
    return redirect(url_for("employees.view", id=id, tab="assets"))


@bp.route("/assets/<int:id>/delete", methods=["POST"], endpoint="asset_delete")
@permission_required("employees.assets.delete")
def asset_delete(id):
    row = db.query("SELECT * FROM employee_assets WHERE id=?", (id,), one=True)
    if row is None:
        flash("Asset not found.", "error")
        return redirect(url_for("employees.list_view"))
    emp_id = row["employee_id"]
    db.execute("DELETE FROM employee_assets WHERE id=?", (id,))
    audit.log("employees", "assets", emp_id, "delete", f"Removed asset: {row['asset_name']}")
    flash("Asset removed.", "success")
    return redirect(url_for("employees.view", id=emp_id, tab="assets"))
