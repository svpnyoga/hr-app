"""Global search module: powers the topbar search box (app.js
`onGlobalSearch`) with a single small JSON API endpoint.

No tables owned here -- read-only lookups across whatever the logged-in user
has view permission for. Kept deliberately narrow (only entities we are
certain other modules expose canonical URLs for) per module instructions.
"""
from flask import Blueprint, request, jsonify, url_for

import db
from auth import login_required, has_permission

bp = Blueprint("search", __name__)


@bp.route("/api")
@login_required
def api():
    q = (request.args.get("q") or "").strip()
    results = []
    if len(q) < 2:
        return jsonify(results)

    like = f"%{q}%"

    if has_permission("employees.employees.view_all"):
        rows = db.query(
            """SELECT id, employee_code, first_name, last_name, work_email
               FROM employees
               WHERE is_deleted=0 AND (
                 first_name LIKE ? OR last_name LIKE ? OR employee_code LIKE ? OR work_email LIKE ?
               )
               ORDER BY first_name, last_name LIMIT 5""",
            (like, like, like, like),
        )
        for r in rows:
            results.append(
                {
                    "title": f"{r['first_name']} {r['last_name']}",
                    "subtitle": f"{r['employee_code']} · {r['work_email'] or 'Employee'}",
                    "url": url_for("employees.view", id=r["id"]),
                    "icon": "EMP",
                }
            )

    if has_permission("crm.leads.view_all"):
        rows = db.query(
            """SELECT id, lead_number, company_name, contact_name, status
               FROM crm_leads
               WHERE company_name LIKE ? OR contact_name LIKE ?
               ORDER BY created_at DESC LIMIT 5""",
            (like, like),
        )
        for r in rows:
            results.append(
                {
                    "title": r["company_name"],
                    "subtitle": f"{r['contact_name'] or 'Lead'} · {r['status']}",
                    "url": url_for("crm.leads_pipeline"),
                    "icon": "LEAD",
                }
            )

    if has_permission("documents.documents.view_all"):
        rows = db.query(
            """SELECT id, title FROM hr_documents WHERE title LIKE ? ORDER BY uploaded_at DESC LIMIT 5""",
            (like,),
        )
        for r in rows:
            results.append(
                {
                    "title": r["title"],
                    "subtitle": "HR Document",
                    "url": url_for("documents.list_view"),
                    "icon": "DOC",
                }
            )

    return jsonify(results)
