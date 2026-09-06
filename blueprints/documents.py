"""HR Documents blueprint.

Table: hr_documents. Master data `document_types` is managed by the admin
module — this blueprint only reads it for dropdowns. Rows with a NULL
employee_id are company-wide policy documents, visible to everyone.
"""
import os
import uuid

from flask import Blueprint, g, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename

import db
import audit
import config
from auth import permission_required, has_permission
from helpers import now_iso

bp = Blueprint("documents", __name__)


def _save_document(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    folder = os.path.join(config.UPLOAD_DIR, "documents")
    os.makedirs(folder, exist_ok=True)
    safe_name = secure_filename(file_storage.filename)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    file_storage.save(os.path.join(folder, unique_name))
    return f"documents/{unique_name}"


@bp.route("/", endpoint="list_view")
@permission_required("documents.documents.view")
def list_view():
    view_all = has_permission("documents.documents.view_all")
    where = []
    args = []

    if view_all:
        emp_filter = request.args.get("employee_id", type=int)
        if emp_filter:
            where.append("(hd.employee_id = ? OR hd.employee_id IS NULL)")
            args.append(emp_filter)
    else:
        own_id = g.employee["id"] if g.employee else -1
        where.append("(hd.employee_id = ? OR hd.employee_id IS NULL)")
        args.append(own_id)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(
        f"""SELECT hd.*, dt.name AS document_type_name,
                   e.first_name || ' ' || e.last_name AS employee_name
            FROM hr_documents hd
            JOIN document_types dt ON dt.id = hd.document_type_id
            LEFT JOIN employees e ON e.id = hd.employee_id
            {where_sql}
            ORDER BY hd.uploaded_at DESC""",
        args,
    )

    expiring_soon = []
    if view_all:
        expiring_soon = db.query(
            """SELECT hd.*, dt.name AS document_type_name,
                      e.first_name || ' ' || e.last_name AS employee_name
               FROM hr_documents hd
               JOIN document_types dt ON dt.id = hd.document_type_id
               LEFT JOIN employees e ON e.id = hd.employee_id
               WHERE hd.expiry_date IS NOT NULL
                 AND date(hd.expiry_date) >= date('now')
                 AND date(hd.expiry_date) <= date('now', '+30 days')
               ORDER BY hd.expiry_date ASC"""
        )

    employees = db.query(
        "SELECT id, first_name || ' ' || last_name AS name FROM employees WHERE is_deleted=0 ORDER BY first_name"
    ) if view_all else []

    return render_template(
        "documents/list.html",
        rows=rows, view_all=view_all, expiring_soon=expiring_soon, employees=employees,
        employee_filter=request.args.get("employee_id", type=int),
    )


@bp.route("/new", methods=("GET", "POST"), endpoint="new")
@permission_required("documents.documents.create")
def new():
    document_types = db.query("SELECT id, name, requires_expiry FROM document_types ORDER BY name")
    employees = db.query(
        "SELECT id, first_name || ' ' || last_name AS name FROM employees WHERE is_deleted=0 ORDER BY first_name"
    )

    if request.method == "POST":
        document_type_id = request.form.get("document_type_id", type=int)
        title = request.form.get("title", "").strip()
        employee_id = request.form.get("employee_id", type=int)  # None/blank -> company-wide
        expiry_date = request.form.get("expiry_date", "").strip() or None
        file_storage = request.files.get("file")

        if not document_type_id or not title:
            flash("Document type and title are required.", "error")
            return render_template("documents/new.html", document_types=document_types, employees=employees)

        file_path = _save_document(file_storage)

        new_id = db.execute(
            """INSERT INTO hr_documents
               (employee_id, document_type_id, title, file_path, uploaded_by, expiry_date)
               VALUES (?,?,?,?,?,?)""",
            (employee_id, document_type_id, title, file_path, g.user["id"], expiry_date),
        )
        audit.log("documents", "documents", new_id, "create", f"Uploaded HR document '{title}'")
        flash("Document uploaded successfully.", "success")
        return redirect(url_for("documents.view", id=new_id))

    return render_template("documents/new.html", document_types=document_types, employees=employees)


@bp.route("/<int:id>", endpoint="view")
@permission_required("documents.documents.view")
def view(id):
    row = db.query(
        """SELECT hd.*, dt.name AS document_type_name,
                  e.first_name || ' ' || e.last_name AS employee_name,
                  uu.full_name AS uploaded_by_name, vu.full_name AS verified_by_name
           FROM hr_documents hd
           JOIN document_types dt ON dt.id = hd.document_type_id
           LEFT JOIN employees e ON e.id = hd.employee_id
           LEFT JOIN users uu ON uu.id = hd.uploaded_by
           LEFT JOIN users vu ON vu.id = hd.verified_by
           WHERE hd.id=?""",
        (id,), one=True,
    )
    if row is None:
        flash("Document not found.", "error")
        return redirect(url_for("documents.list_view"))

    if not has_permission("documents.documents.view_all"):
        if row["employee_id"] is not None:
            if g.employee is None or row["employee_id"] != g.employee["id"]:
                flash("You don't have permission to view this document.", "error")
                return redirect(url_for("documents.list_view"))

    can_verify = (not row["is_verified"]) and has_permission("documents.documents.edit")
    can_delete = has_permission("documents.documents.delete")

    return render_template("documents/view.html", row=row, can_verify=can_verify, can_delete=can_delete)


@bp.route("/<int:id>/verify", methods=("POST",), endpoint="verify")
@permission_required("documents.documents.edit")
def verify(id):
    row = db.query("SELECT * FROM hr_documents WHERE id=?", (id,), one=True)
    if row is None:
        flash("Document not found.", "error")
        return redirect(url_for("documents.list_view"))

    db.execute(
        "UPDATE hr_documents SET is_verified=1, verified_by=?, verified_at=? WHERE id=?",
        (g.user["id"], now_iso(), id),
    )
    audit.log("documents", "documents", id, "edit", f"Verified HR document '{row['title']}'")
    flash("Document marked as verified.", "success")
    return redirect(url_for("documents.view", id=id))


@bp.route("/<int:id>/delete", methods=("POST",), endpoint="delete")
@permission_required("documents.documents.delete")
def delete(id):
    row = db.query("SELECT * FROM hr_documents WHERE id=?", (id,), one=True)
    if row is None:
        flash("Document not found.", "error")
        return redirect(url_for("documents.list_view"))

    db.execute("DELETE FROM hr_documents WHERE id=?", (id,))
    audit.log("documents", "documents", id, "delete", f"Deleted HR document '{row['title']}'")
    flash("Document deleted.", "success")
    return redirect(url_for("documents.list_view"))
