"""CRM module: customers, contacts, leads (kanban pipeline) and activities.

CRM records are not employee-owned. Scoping follows the sales-rep ownership
pattern instead of the employee_id pattern used elsewhere: when the current
user lacks the `<entity>.view_all` permission, records are filtered down to
`owner_user_id = g.user["id"]`.
"""
import math
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
import audit
import notify
from auth import permission_required, has_permission
from helpers import paginate_args

bp = Blueprint("crm", __name__)

STAGES = ["New", "Contacted", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]
ACTIVITY_TYPES = ["Call", "Email", "Meeting", "Note"]


# ============================================================================
# Customers
# ============================================================================

@bp.route("/customers")
@permission_required("crm.customers.view")
def customers_list():
    q = request.args.get("q", "").strip()
    page, per_page = paginate_args(request)

    where = []
    args = []
    if not has_permission("crm.customers.view_all"):
        where.append("c.owner_user_id = ?")
        args.append(g.user["id"])
    if q:
        where.append("c.name LIKE ?")
        args.append(f"%{q}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = db.query(f"SELECT COUNT(*) c FROM crm_customers c {where_sql}", args, one=True)["c"]
    offset = (page - 1) * per_page
    rows = db.query(
        f"""SELECT c.*, u.full_name as owner_name
            FROM crm_customers c LEFT JOIN users u ON u.id = c.owner_user_id
            {where_sql} ORDER BY c.name LIMIT ? OFFSET ?""",
        args + [per_page, offset],
    )
    pages = max(1, math.ceil(total / per_page))
    return render_template(
        "crm/customers_list.html", rows=rows, q=q, page=page, pages=pages, total=total,
        per_page=per_page, can_create=has_permission("crm.customers.create"),
    )


@bp.route("/customers/new", methods=("GET", "POST"))
@permission_required("crm.customers.create")
def customer_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Customer name is required.", "error")
            return render_template("crm/customer_form.html")
        code = db.next_sequence("CUSTOMER", "CUST", 4)
        new_id = db.execute(
            """INSERT INTO crm_customers (customer_code, name, industry, phone, email, address, city, owner_user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                code, name,
                request.form.get("industry", "").strip() or None,
                request.form.get("phone", "").strip() or None,
                request.form.get("email", "").strip() or None,
                request.form.get("address", "").strip() or None,
                request.form.get("city", "").strip() or None,
                g.user["id"],
            ),
        )
        audit.log("crm", "customers", new_id, "create", f"Created CRM customer {code} — {name}")
        flash("Customer created successfully.", "success")
        return redirect(url_for("crm.customer_view", id=new_id))
    return render_template("crm/customer_form.html")


@bp.route("/customers/<int:id>")
@permission_required("crm.customers.view")
def customer_view(id):
    row = db.query(
        """SELECT c.*, u.full_name as owner_name FROM crm_customers c
           LEFT JOIN users u ON u.id = c.owner_user_id WHERE c.id=?""",
        (id,), one=True,
    )
    if row is None:
        flash("Customer not found.", "error")
        return redirect(url_for("crm.customers_list"))
    if not has_permission("crm.customers.view_all") and row["owner_user_id"] != g.user["id"]:
        flash("You don't have permission to view this customer.", "error")
        return redirect(url_for("crm.customers_list"))

    contacts = db.query("SELECT * FROM crm_contacts WHERE customer_id=? ORDER BY id DESC", (id,))
    activities = db.query(
        """SELECT a.*, u.full_name as owner_name FROM crm_activities a
           LEFT JOIN users u ON u.id = a.owner_user_id
           WHERE a.customer_id=? ORDER BY a.activity_date DESC, a.id DESC""",
        (id,),
    )
    return render_template(
        "crm/customer_detail.html", row=row, contacts=contacts, activities=activities,
        activity_types=ACTIVITY_TYPES, today=date.today().isoformat(),
        can_edit=has_permission("crm.customers.edit"),
    )


@bp.route("/contacts/add", methods=("POST",))
@permission_required("crm.customers.edit")
def contact_add():
    customer_id = request.form.get("customer_id", type=int)
    customer = db.query("SELECT * FROM crm_customers WHERE id=?", (customer_id,), one=True) if customer_id else None
    if customer is None:
        flash("Customer not found.", "error")
        return redirect(url_for("crm.customers_list"))

    name = request.form.get("name", "").strip()
    if not name:
        flash("Contact name is required.", "error")
        return redirect(url_for("crm.customer_view", id=customer_id))

    db.execute(
        "INSERT INTO crm_contacts (customer_id, name, designation, phone, email) VALUES (?,?,?,?,?)",
        (
            customer_id, name,
            request.form.get("designation", "").strip() or None,
            request.form.get("phone", "").strip() or None,
            request.form.get("email", "").strip() or None,
        ),
    )
    audit.log("crm", "customers", customer_id, "update", f"Added contact '{name}' to customer #{customer_id}")
    flash("Contact added.", "success")
    return redirect(url_for("crm.customer_view", id=customer_id))


@bp.route("/contacts/<int:id>/delete", methods=("POST",))
@permission_required("crm.customers.edit")
def contact_delete(id):
    contact = db.query("SELECT * FROM crm_contacts WHERE id=?", (id,), one=True)
    if contact is None:
        flash("Contact not found.", "error")
        return redirect(url_for("crm.customers_list"))
    customer_id = contact["customer_id"]
    db.execute("DELETE FROM crm_contacts WHERE id=?", (id,))
    audit.log("crm", "customers", customer_id, "update", f"Removed contact '{contact['name']}' from customer #{customer_id}")
    flash("Contact removed.", "success")
    return redirect(url_for("crm.customer_view", id=customer_id))


# ============================================================================
# Leads (kanban pipeline)
# ============================================================================

@bp.route("/leads")
@permission_required("crm.leads.view")
def leads_pipeline():
    where = []
    args = []
    if not has_permission("crm.leads.view_all"):
        where.append("l.owner_user_id = ?")
        args.append(g.user["id"])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = db.query(
        f"""SELECT l.*, u.full_name as owner_name FROM crm_leads l
            LEFT JOIN users u ON u.id = l.owner_user_id
            {where_sql} ORDER BY l.created_at DESC""",
        args,
    )

    columns = {s: [] for s in STAGES}
    for r in rows:
        columns.setdefault(r["status"], []).append(r)

    open_rows = [r for r in rows if r["status"] not in ("Won", "Lost")]
    total_pipeline_value = sum((r["estimated_value"] or 0) for r in open_rows)

    # crm_leads has no dedicated "won_at" timestamp, so "won this month" is
    # approximated using the lead's created_at month.
    this_month = date.today().strftime("%Y-%m")
    won_this_month = sum(
        (r["estimated_value"] or 0) for r in rows
        if r["status"] == "Won" and str(r["created_at"] or "").startswith(this_month)
    )

    won_count = sum(1 for r in rows if r["status"] == "Won")
    lost_count = sum(1 for r in rows if r["status"] == "Lost")
    win_rate = (won_count / (won_count + lost_count) * 100) if (won_count + lost_count) > 0 else 0

    return render_template(
        "crm/leads_pipeline.html", columns=columns, stages=STAGES, lead_total=len(rows),
        total_pipeline_value=total_pipeline_value, won_this_month=won_this_month, win_rate=win_rate,
        can_create=has_permission("crm.leads.create"), can_edit=has_permission("crm.leads.edit"),
    )


@bp.route("/leads/new", methods=("GET", "POST"))
@permission_required("crm.leads.create")
def lead_new():
    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        if not company_name:
            flash("Company name is required.", "error")
            return render_template("crm/lead_form.html")
        lead_number = db.next_sequence("LEAD", "LD", 5)
        est_raw = request.form.get("estimated_value", "").strip()
        try:
            est_value = float(est_raw) if est_raw else None
        except ValueError:
            est_value = None
        new_id = db.execute(
            """INSERT INTO crm_leads (lead_number, company_name, contact_name, phone, email, source,
               status, estimated_value, owner_user_id) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                lead_number, company_name,
                request.form.get("contact_name", "").strip() or None,
                request.form.get("phone", "").strip() or None,
                request.form.get("email", "").strip() or None,
                request.form.get("source", "").strip() or None,
                "New", est_value, g.user["id"],
            ),
        )
        audit.log("crm", "leads", new_id, "create", f"Created CRM lead {lead_number} — {company_name}")
        flash("Lead created successfully.", "success")
        return redirect(url_for("crm.lead_view", id=new_id))
    return render_template("crm/lead_form.html")


@bp.route("/leads/<int:id>")
@permission_required("crm.leads.view")
def lead_view(id):
    row = db.query(
        """SELECT l.*, u.full_name as owner_name FROM crm_leads l
           LEFT JOIN users u ON u.id = l.owner_user_id WHERE l.id=?""",
        (id,), one=True,
    )
    if row is None:
        flash("Lead not found.", "error")
        return redirect(url_for("crm.leads_pipeline"))
    if not has_permission("crm.leads.view_all") and row["owner_user_id"] != g.user["id"]:
        flash("You don't have permission to view this lead.", "error")
        return redirect(url_for("crm.leads_pipeline"))

    activities = db.query(
        """SELECT a.*, u.full_name as owner_name FROM crm_activities a
           LEFT JOIN users u ON u.id = a.owner_user_id
           WHERE a.lead_id=? ORDER BY a.activity_date DESC, a.id DESC""",
        (id,),
    )
    return render_template(
        "crm/lead_detail.html", row=row, activities=activities, stages=STAGES,
        activity_types=ACTIVITY_TYPES, today=date.today().isoformat(),
        can_edit=has_permission("crm.leads.edit"),
    )


@bp.route("/leads/<int:id>/stage", methods=("POST",))
@permission_required("crm.leads.edit")
def lead_stage(id):
    lead = db.query("SELECT * FROM crm_leads WHERE id=?", (id,), one=True)
    if lead is None:
        flash("Lead not found.", "error")
        return redirect(url_for("crm.leads_pipeline"))
    if not has_permission("crm.leads.view_all") and lead["owner_user_id"] != g.user["id"]:
        flash("You don't have permission to update this lead.", "error")
        return redirect(url_for("crm.leads_pipeline"))

    stage = request.form.get("stage", "").strip()
    if stage not in STAGES:
        flash("Invalid pipeline stage.", "error")
        return redirect(url_for("crm.lead_view", id=id))

    db.execute("UPDATE crm_leads SET status=? WHERE id=?", (stage, id))
    audit.log("crm", "leads", id, "update", f"Moved lead {lead['lead_number']} to stage '{stage}'")

    if lead["owner_user_id"] and lead["owner_user_id"] != g.user["id"]:
        notify.notify_user(
            lead["owner_user_id"], "Lead stage updated",
            f"{g.user['full_name']} moved lead {lead['lead_number']} ({lead['company_name']}) to '{stage}'.",
            ntype="info", link=url_for("crm.lead_view", id=id),
        )

    # The kanban drag-and-drop posts here via fetch() and just reloads the
    # page afterwards, so a normal redirect (which fetch follows) is fine
    # both for that call and for a plain form submission to this endpoint.
    return redirect(url_for("crm.lead_view", id=id))


# ============================================================================
# Activities
# ============================================================================

@bp.route("/activities/new", methods=("GET", "POST"))
@permission_required("crm.activities.create")
def activity_new():
    lead_id = request.values.get("lead_id", type=int)
    customer_id = request.values.get("customer_id", type=int)

    lead = db.query("SELECT * FROM crm_leads WHERE id=?", (lead_id,), one=True) if lead_id else None
    customer = db.query("SELECT * FROM crm_customers WHERE id=?", (customer_id,), one=True) if customer_id else None

    if lead_id and lead is None:
        flash("Lead not found.", "error")
        return redirect(url_for("crm.leads_pipeline"))
    if customer_id and customer is None:
        flash("Customer not found.", "error")
        return redirect(url_for("crm.customers_list"))
    if not lead and not customer:
        flash("An activity must be linked to a lead or a customer.", "error")
        return redirect(url_for("crm.leads_pipeline"))

    if lead and not has_permission("crm.leads.view_all") and lead["owner_user_id"] != g.user["id"]:
        flash("You don't have permission to log activity on this lead.", "error")
        return redirect(url_for("crm.leads_pipeline"))
    if customer and not has_permission("crm.customers.view_all") and customer["owner_user_id"] != g.user["id"]:
        flash("You don't have permission to log activity on this customer.", "error")
        return redirect(url_for("crm.customers_list"))

    if request.method == "POST":
        activity_type = request.form.get("activity_type") or "Note"
        if activity_type not in ACTIVITY_TYPES:
            activity_type = "Note"
        subject = request.form.get("subject", "").strip() or None
        notes = request.form.get("notes", "").strip() or None
        activity_date = request.form.get("activity_date") or date.today().isoformat()

        new_id = db.execute(
            """INSERT INTO crm_activities (lead_id, customer_id, activity_type, subject, notes,
               activity_date, owner_user_id) VALUES (?,?,?,?,?,?,?)""",
            (lead_id, customer_id, activity_type, subject, notes, activity_date, g.user["id"]),
        )

        label = lead["lead_number"] if lead else customer["customer_code"]
        audit.log("crm", "activities", new_id, "create", f"Logged {activity_type} activity for {label}")

        owner_id = lead["owner_user_id"] if lead else customer["owner_user_id"]
        if owner_id and owner_id != g.user["id"]:
            target = url_for("crm.lead_view", id=lead_id) if lead_id else url_for("crm.customer_view", id=customer_id)
            notify.notify_user(
                owner_id, "New CRM activity logged",
                f"{g.user['full_name']} logged a {activity_type.lower()} on {label}"
                + (f": {subject}" if subject else "."),
                ntype="info", link=target,
            )

        flash("Activity logged.", "success")
        if lead_id:
            return redirect(url_for("crm.lead_view", id=lead_id))
        return redirect(url_for("crm.customer_view", id=customer_id))

    return render_template(
        "crm/activity_form.html", lead=lead, customer=customer,
        activity_types=ACTIVITY_TYPES, today=date.today().isoformat(),
    )
