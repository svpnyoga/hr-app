"""Recruitment / Applicant Tracking System.

Tables owned: job_requisitions, candidates, applications, interviews, offers.
Everyone holding recruitment.*.view gets full visibility (recruitment records
are not employee-owned, so the self-service view/view_all scoping convention
used elsewhere in the app does not apply here).
"""
import os
from datetime import date, datetime

from flask import Blueprint, g, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

import config
import db
import audit
import notify
from auth import permission_required, has_permission
from helpers import paginate_args

bp = Blueprint("recruitment", __name__)

STAGES = [
    "Applied", "Screening", "Shortlisted", "Interview", "Technical Interview",
    "HR Interview", "Selected", "Offer", "Joined", "Rejected",
]
REQUISITION_STATUSES = ["Open", "On Hold", "Closed", "Cancelled"]
OFFER_STATUSES = ["Draft", "Sent", "Accepted", "Declined", "Withdrawn"]
INTERVIEW_MODES = ["In-person", "Phone", "Video"]
RECOMMENDATIONS = ["Strong Yes", "Yes", "Neutral", "No", "Strong No"]

RESUME_SUBDIR = "recruitment"


# ---------------------------------------------------------------------------
# small shared lookups
# ---------------------------------------------------------------------------

def _departments():
    return db.query("SELECT id, name FROM departments ORDER BY name")


def _designations():
    return db.query("SELECT id, title, department_id FROM designations ORDER BY title")


def _locations():
    return db.query("SELECT id, name FROM locations ORDER BY name")


def _open_requisitions():
    return db.query(
        "SELECT id, requisition_number, title FROM job_requisitions WHERE status='Open' ORDER BY created_at DESC"
    )


def _requisition_or_404(id):
    row = db.query("SELECT * FROM job_requisitions WHERE id=?", (id,), one=True)
    if row is None:
        flash("Requisition not found.", "error")
        return None
    return row


def _candidate_or_404(id):
    row = db.query("SELECT * FROM candidates WHERE id=?", (id,), one=True)
    if row is None:
        flash("Candidate not found.", "error")
        return None
    return row


def _application_or_404(id):
    row = db.query(
        """SELECT a.*, c.full_name as candidate_name, c.email as candidate_email, c.phone as candidate_phone,
                  jr.title as requisition_title, jr.requisition_number, jr.id as requisition_id
           FROM applications a
           JOIN candidates c ON c.id = a.candidate_id
           JOIN job_requisitions jr ON jr.id = a.requisition_id
           WHERE a.id=?""",
        (id,), one=True,
    )
    if row is None:
        flash("Application not found.", "error")
        return None
    return row


def _save_resume(candidate_code, file_storage):
    if not file_storage or not file_storage.filename:
        return None
    fname = secure_filename(file_storage.filename)
    if not fname:
        return None
    target_dir = os.path.join(config.UPLOAD_DIR, RESUME_SUBDIR)
    os.makedirs(target_dir, exist_ok=True)
    stored_name = f"{candidate_code}_{fname}"
    file_storage.save(os.path.join(target_dir, stored_name))
    return f"{RESUME_SUBDIR}/{stored_name}"


# ---------------------------------------------------------------------------
# Job requisitions
# ---------------------------------------------------------------------------

@bp.route("/requisitions")
@permission_required("recruitment.requisitions.view")
def requisitions_list():
    status = request.args.get("status", "").strip()
    department_id = request.args.get("department_id", "").strip()
    where, args = [], []
    if status:
        where.append("jr.status=?")
        args.append(status)
    if department_id:
        where.append("jr.department_id=?")
        args.append(department_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(
        f"""SELECT jr.*, d.name as department_name, l.name as location_name, dz.title as designation_title,
                  (SELECT COUNT(*) FROM applications a WHERE a.requisition_id = jr.id) as application_count
           FROM job_requisitions jr
           LEFT JOIN departments d ON d.id = jr.department_id
           LEFT JOIN locations l ON l.id = jr.location_id
           LEFT JOIN designations dz ON dz.id = jr.designation_id
           {where_sql}
           ORDER BY jr.created_at DESC""",
        args,
    )
    kpis = db.query(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN status='Open' THEN 1 ELSE 0 END) as open_count,
                  SUM(CASE WHEN status='Open' THEN num_openings ELSE 0 END) as open_positions,
                  (SELECT COUNT(*) FROM applications) as total_applications
           FROM job_requisitions""",
        one=True,
    )
    return render_template(
        "recruitment/requisitions_list.html",
        rows=rows, kpis=kpis, departments=_departments(),
        status=status, department_id=department_id, statuses=REQUISITION_STATUSES,
        can_create=has_permission("recruitment.requisitions.create"),
        can_edit=has_permission("recruitment.requisitions.edit"),
    )


@bp.route("/requisitions/new", methods=("GET", "POST"))
@permission_required("recruitment.requisitions.create")
def requisition_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.", "error")
            return render_template(
                "recruitment/requisition_form.html",
                departments=_departments(), designations=_designations(), locations=_locations(),
            )
        try:
            num_openings = int(request.form.get("num_openings") or 1)
        except ValueError:
            num_openings = 1
        requisition_number = db.next_sequence("REQUISITION", "REQ", 4)
        new_id = db.execute(
            """INSERT INTO job_requisitions
               (requisition_number, title, department_id, designation_id, location_id, num_openings,
                employment_type, experience_required, description, status, requested_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                requisition_number, title,
                request.form.get("department_id") or None,
                request.form.get("designation_id") or None,
                request.form.get("location_id") or None,
                num_openings,
                request.form.get("employment_type") or "Full-time",
                request.form.get("experience_required", "").strip() or None,
                request.form.get("description", "").strip() or None,
                "Open",
                g.user["id"],
            ),
        )
        audit.log("recruitment", "requisitions", new_id, "create",
                   f"Created job requisition {requisition_number} ({title})")
        notify.notify_roles(
            ["HR Manager", "Recruiter"],
            "New job requisition",
            f"{requisition_number} — {title} was raised and needs sourcing.",
            "info",
            url_for("recruitment.requisition_view", id=new_id),
        )
        flash(f"Requisition {requisition_number} created.", "success")
        return redirect(url_for("recruitment.requisition_view", id=new_id))
    return render_template(
        "recruitment/requisition_form.html",
        departments=_departments(), designations=_designations(), locations=_locations(),
    )


@bp.route("/requisitions/<int:id>")
@permission_required("recruitment.requisitions.view")
def requisition_view(id):
    req = _requisition_or_404(id)
    if req is None:
        return redirect(url_for("recruitment.requisitions_list"))
    d = dict(req)
    if d.get("department_id"):
        r = db.query("SELECT name FROM departments WHERE id=?", (d["department_id"],), one=True)
        d["department_name"] = r["name"] if r else "—"
    if d.get("designation_id"):
        r = db.query("SELECT title FROM designations WHERE id=?", (d["designation_id"],), one=True)
        d["designation_title"] = r["title"] if r else "—"
    if d.get("location_id"):
        r = db.query("SELECT name FROM locations WHERE id=?", (d["location_id"],), one=True)
        d["location_name"] = r["name"] if r else "—"
    if d.get("requested_by"):
        r = db.query("SELECT full_name FROM users WHERE id=?", (d["requested_by"],), one=True)
        d["requested_by_name"] = r["full_name"] if r else "—"

    applications = db.query(
        """SELECT a.*, c.full_name as candidate_name, c.email as candidate_email
           FROM applications a JOIN candidates c ON c.id = a.candidate_id
           WHERE a.requisition_id=? ORDER BY a.applied_date DESC""",
        (id,),
    )
    stage_counts = {s: 0 for s in STAGES}
    for a in applications:
        stage_counts[a["stage"]] = stage_counts.get(a["stage"], 0) + 1

    return render_template(
        "recruitment/requisition_view.html",
        req=d, applications=applications, stage_counts=stage_counts, stages=STAGES,
        statuses=REQUISITION_STATUSES,
        can_edit=has_permission("recruitment.requisitions.edit"),
        can_add_application=has_permission("recruitment.applications.create"),
    )


@bp.route("/requisitions/<int:id>/status", methods=("POST",))
@permission_required("recruitment.requisitions.edit")
def requisition_status(id):
    req = _requisition_or_404(id)
    if req is None:
        return redirect(url_for("recruitment.requisitions_list"))
    new_status = request.form.get("status", "").strip()
    if new_status not in REQUISITION_STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("recruitment.requisition_view", id=id))
    db.execute("UPDATE job_requisitions SET status=? WHERE id=?", (new_status, id))
    audit.log("recruitment", "requisitions", id, "update",
               f"Requisition {req['requisition_number']} status changed from {req['status']} to {new_status}")
    flash("Requisition status updated.", "success")
    return redirect(url_for("recruitment.requisition_view", id=id))


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

@bp.route("/candidates")
@permission_required("recruitment.candidates.view")
def candidates_list():
    q = request.args.get("q", "").strip()
    page, per_page = paginate_args(request)
    where, args = [], []
    if q:
        where.append("(full_name LIKE ? OR email LIKE ? OR phone LIKE ? OR current_company LIKE ?)")
        args.extend([f"%{q}%"] * 4)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.query(f"SELECT COUNT(*) c FROM candidates {where_sql}", args, one=True)["c"]
    offset = (page - 1) * per_page
    rows = db.query(
        f"SELECT * FROM candidates {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        args + [per_page, offset],
    )
    import math
    pages = max(1, math.ceil(total / per_page))
    return render_template(
        "recruitment/candidates_list.html",
        rows=rows, q=q, page=page, pages=pages, total=total, per_page=per_page,
        can_create=has_permission("recruitment.candidates.create"),
    )


@bp.route("/candidates/new", methods=("GET", "POST"))
@permission_required("recruitment.candidates.create")
def candidate_new():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if not full_name:
            flash("Full name is required.", "error")
            return render_template("recruitment/candidate_form.html")

        def num(name):
            val = request.form.get(name, "").strip()
            try:
                return float(val) if val else None
            except ValueError:
                return None

        def integer(name):
            val = request.form.get(name, "").strip()
            try:
                return int(val) if val else None
            except ValueError:
                return None

        candidate_code = db.next_sequence("CANDIDATE", "CAND", 5)
        resume_path = _save_resume(candidate_code, request.files.get("resume"))

        new_id = db.execute(
            """INSERT INTO candidates
               (candidate_code, full_name, email, phone, resume_path, total_experience_years,
                current_company, current_designation, current_salary, expected_salary,
                notice_period_days, qualification, skills, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                candidate_code, full_name,
                request.form.get("email", "").strip() or None,
                request.form.get("phone", "").strip() or None,
                resume_path,
                num("total_experience_years"),
                request.form.get("current_company", "").strip() or None,
                request.form.get("current_designation", "").strip() or None,
                num("current_salary"),
                num("expected_salary"),
                integer("notice_period_days"),
                request.form.get("qualification", "").strip() or None,
                request.form.get("skills", "").strip() or None,
                request.form.get("source", "").strip() or None,
            ),
        )
        audit.log("recruitment", "candidates", new_id, "create",
                   f"Added candidate {candidate_code} ({full_name})")
        flash(f"Candidate {candidate_code} added.", "success")

        requisition_id = request.form.get("requisition_id", "").strip()
        if requisition_id:
            return redirect(url_for("recruitment.application_new", candidate_id=new_id, requisition_id=requisition_id))
        return redirect(url_for("recruitment.candidate_view", id=new_id))

    return render_template("recruitment/candidate_form.html", open_requisitions=_open_requisitions())


@bp.route("/candidates/<int:id>")
@permission_required("recruitment.candidates.view")
def candidate_view(id):
    cand = _candidate_or_404(id)
    if cand is None:
        return redirect(url_for("recruitment.candidates_list"))
    applications = db.query(
        """SELECT a.*, jr.title as requisition_title, jr.requisition_number
           FROM applications a JOIN job_requisitions jr ON jr.id = a.requisition_id
           WHERE a.candidate_id=? ORDER BY a.applied_date DESC""",
        (id,),
    )
    applied_requisition_ids = {a["requisition_id"] for a in applications}
    available_requisitions = [r for r in _open_requisitions() if r["id"] not in applied_requisition_ids]
    return render_template(
        "recruitment/candidate_view.html",
        cand=cand, applications=applications, available_requisitions=available_requisitions,
        can_apply=has_permission("recruitment.applications.create"),
    )


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.route("/applications/new", methods=("GET", "POST"))
@permission_required("recruitment.applications.create")
def application_new():
    candidate_id = request.values.get("candidate_id", type=int)
    requisition_id = request.values.get("requisition_id", type=int)

    if request.method == "POST":
        candidate_id = request.form.get("candidate_id", type=int)
        requisition_id = request.form.get("requisition_id", type=int)
        if not candidate_id or not requisition_id:
            flash("Both a candidate and a requisition are required.", "error")
            return redirect(url_for("recruitment.application_new"))
        existing = db.query(
            "SELECT id FROM applications WHERE candidate_id=? AND requisition_id=?",
            (candidate_id, requisition_id), one=True,
        )
        if existing:
            flash("This candidate has already applied to that requisition.", "error")
            return redirect(url_for("recruitment.application_view", id=existing["id"]))
        new_id = db.execute(
            """INSERT INTO applications (requisition_id, candidate_id, stage, applied_date)
               VALUES (?,?,?,?)""",
            (requisition_id, candidate_id, "Applied", date.today().isoformat()),
        )
        cand = db.query("SELECT full_name FROM candidates WHERE id=?", (candidate_id,), one=True)
        req = db.query("SELECT title, requisition_number FROM job_requisitions WHERE id=?", (requisition_id,), one=True)
        audit.log("recruitment", "applications", new_id, "create",
                   f"{cand['full_name'] if cand else 'Candidate'} applied to "
                   f"{req['requisition_number'] if req else 'requisition'}")
        flash("Application created.", "success")
        return redirect(url_for("recruitment.application_view", id=new_id))

    cand = db.query("SELECT * FROM candidates WHERE id=?", (candidate_id,), one=True) if candidate_id else None
    return render_template(
        "recruitment/application_form.html",
        candidate=cand, requisition_id=requisition_id,
        candidates=db.query("SELECT id, candidate_code, full_name FROM candidates ORDER BY full_name") if not cand else None,
        open_requisitions=_open_requisitions(),
    )


@bp.route("/applications/<int:id>")
@permission_required("recruitment.applications.view")
def application_view(id):
    app_row = _application_or_404(id)
    if app_row is None:
        return redirect(url_for("recruitment.pipeline"))
    interviews = db.query(
        "SELECT * FROM interviews WHERE application_id=? ORDER BY scheduled_at DESC, id DESC", (id,)
    )
    offers = db.query(
        "SELECT * FROM offers WHERE application_id=? ORDER BY offer_date DESC, id DESC", (id,)
    )
    offers_display = []
    for o in offers:
        od = dict(o)
        if od.get("designation_id"):
            r = db.query("SELECT title FROM designations WHERE id=?", (od["designation_id"],), one=True)
            od["designation_title"] = r["title"] if r else "—"
        offers_display.append(od)
    return render_template(
        "recruitment/application_view.html",
        app=app_row, interviews=interviews, offers=offers_display, stages=STAGES,
        offer_statuses=OFFER_STATUSES,
        can_edit=has_permission("recruitment.applications.edit"),
        can_schedule_interview=has_permission("recruitment.interviews.create"),
        can_create_offer=has_permission("recruitment.offers.create"),
        can_edit_offer=has_permission("recruitment.offers.edit"),
    )


@bp.route("/applications/<int:id>/stage", methods=("POST",))
@permission_required("recruitment.applications.edit")
def application_stage(id):
    app_row = db.query("SELECT * FROM applications WHERE id=?", (id,), one=True)
    if app_row is None:
        flash("Application not found.", "error")
        return redirect(url_for("recruitment.pipeline"))
    new_stage = request.form.get("stage", "").strip()
    if new_stage not in STAGES:
        flash("Invalid stage.", "error")
        return redirect(request.referrer or url_for("recruitment.pipeline"))
    rejection_reason = request.form.get("rejection_reason", "").strip() or None

    if new_stage == "Rejected":
        db.execute(
            "UPDATE applications SET stage=?, rejection_reason=? WHERE id=?",
            (new_stage, rejection_reason, id),
        )
    else:
        db.execute("UPDATE applications SET stage=? WHERE id=?", (new_stage, id))

    audit.log("recruitment", "applications", id, "update",
               f"Application #{id} stage changed from {app_row['stage']} to {new_stage}")

    if new_stage == "Selected":
        cand = db.query("SELECT full_name FROM candidates WHERE id=?", (app_row["candidate_id"],), one=True)
        req = db.query("SELECT title, requisition_number FROM job_requisitions WHERE id=?",
                        (app_row["requisition_id"],), one=True)
        notify.notify_roles(
            ["HR Manager", "Recruiter"],
            "Candidate selected",
            f"{cand['full_name'] if cand else 'A candidate'} was selected for "
            f"{req['title'] if req else 'a requisition'}.",
            "success",
            url_for("recruitment.application_view", id=id),
        )

    flash("Stage updated.", "success")
    return redirect(request.referrer or url_for("recruitment.application_view", id=id))


@bp.route("/pipeline")
@permission_required("recruitment.applications.view")
def pipeline():
    requisition_id = request.args.get("requisition_id", type=int)
    where_sql = "WHERE a.requisition_id=?" if requisition_id else ""
    args = [requisition_id] if requisition_id else []
    rows = db.query(
        f"""SELECT a.*, c.full_name as candidate_name, jr.title as requisition_title
           FROM applications a
           JOIN candidates c ON c.id = a.candidate_id
           JOIN job_requisitions jr ON jr.id = a.requisition_id
           {where_sql}
           ORDER BY a.applied_date DESC""",
        args,
    )
    today = date.today()
    columns = {s: [] for s in STAGES}
    for r in rows:
        d = dict(r)
        try:
            applied = datetime.fromisoformat(str(d["applied_date"])[:10]).date()
            d["days_since_applied"] = (today - applied).days
        except (ValueError, TypeError):
            d["days_since_applied"] = None
        columns.setdefault(d["stage"], []).append(d)

    req = None
    if requisition_id:
        req = db.query("SELECT * FROM job_requisitions WHERE id=?", (requisition_id,), one=True)

    return render_template(
        "recruitment/pipeline.html",
        stages=STAGES, columns=columns, requisition_id=requisition_id, req=req,
        requisitions=db.query("SELECT id, requisition_number, title FROM job_requisitions ORDER BY created_at DESC"),
        can_edit=has_permission("recruitment.applications.edit"),
    )


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------

@bp.route("/applications/<int:application_id>/interviews/new", methods=("GET", "POST"))
@permission_required("recruitment.interviews.create")
def interview_new(application_id):
    app_row = _application_or_404(application_id)
    if app_row is None:
        return redirect(url_for("recruitment.pipeline"))
    if request.method == "POST":
        round_name = request.form.get("round_name", "").strip()
        if not round_name:
            flash("Round name is required.", "error")
            return render_template("recruitment/interview_form.html", app=app_row, modes=INTERVIEW_MODES,
                                    recommendations=RECOMMENDATIONS)
        rating = request.form.get("rating", "").strip()
        try:
            rating_val = int(rating) if rating else None
        except ValueError:
            rating_val = None
        new_id = db.execute(
            """INSERT INTO interviews
               (application_id, round_name, scheduled_at, interviewer_name, mode, feedback, rating, recommendation)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                application_id, round_name,
                request.form.get("scheduled_at", "").strip() or None,
                request.form.get("interviewer_name", "").strip() or None,
                request.form.get("mode") or "In-person",
                request.form.get("feedback", "").strip() or None,
                rating_val,
                request.form.get("recommendation", "").strip() or None,
            ),
        )
        audit.log("recruitment", "interviews", new_id, "create",
                   f"Scheduled {round_name} interview for application #{application_id}")
        flash("Interview scheduled.", "success")
        return redirect(url_for("recruitment.application_view", id=application_id))
    return render_template("recruitment/interview_form.html", app=app_row, modes=INTERVIEW_MODES,
                            recommendations=RECOMMENDATIONS)


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

@bp.route("/applications/<int:application_id>/offers/new", methods=("GET", "POST"))
@permission_required("recruitment.offers.create")
def offer_new(application_id):
    app_row = _application_or_404(application_id)
    if app_row is None:
        return redirect(url_for("recruitment.pipeline"))
    if request.method == "POST":
        ctc = request.form.get("ctc", "").strip()
        try:
            ctc_val = float(ctc) if ctc else None
        except ValueError:
            ctc_val = None
        new_id = db.execute(
            """INSERT INTO offers (application_id, offer_date, designation_id, ctc, joining_date, status)
               VALUES (?,?,?,?,?,?)""",
            (
                application_id, date.today().isoformat(),
                request.form.get("designation_id") or None,
                ctc_val,
                request.form.get("joining_date", "").strip() or None,
                "Draft",
            ),
        )
        audit.log("recruitment", "offers", new_id, "create",
                   f"Created offer for application #{application_id}")
        flash("Offer created.", "success")
        return redirect(url_for("recruitment.application_view", id=application_id))
    return render_template("recruitment/offer_form.html", app=app_row, designations=_designations())


@bp.route("/offers/<int:id>/status", methods=("POST",))
@permission_required("recruitment.offers.edit")
def offer_status(id):
    offer = db.query("SELECT * FROM offers WHERE id=?", (id,), one=True)
    if offer is None:
        flash("Offer not found.", "error")
        return redirect(url_for("recruitment.pipeline"))
    new_status = request.form.get("status", "").strip()
    if new_status not in OFFER_STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("recruitment.application_view", id=offer["application_id"]))
    db.execute("UPDATE offers SET status=? WHERE id=?", (new_status, id))
    audit.log("recruitment", "offers", id, "update",
               f"Offer #{id} status changed from {offer['status']} to {new_status}")
    flash("Offer status updated.", "success")
    return redirect(url_for("recruitment.application_view", id=offer["application_id"]))
