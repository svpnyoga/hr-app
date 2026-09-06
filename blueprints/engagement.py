"""Engagement module: pulse/annual surveys with dynamic questions & responses,
and a company-wide recognition feed.
"""
from flask import Blueprint, g, render_template, request, redirect, url_for, flash

import db
import audit
import notify
from auth import permission_required, has_permission

bp = Blueprint("engagement", __name__)

SURVEY_TYPES = ["Pulse", "Annual", "Custom"]
SURVEY_STATUSES = ["Draft", "Active", "Closed"]
QUESTION_TYPES = ["Rating", "Text", "MultipleChoice"]
RECOGNITION_CATEGORIES = ["Award", "Kudos", "Milestone"]


def _employee_options():
    rows = db.query(
        "SELECT id, first_name || ' ' || last_name AS full_name FROM employees "
        "WHERE is_deleted=0 ORDER BY first_name, last_name"
    )
    return [(r["id"], r["full_name"]) for r in rows]


# ----------------------------------------------------------------------------
# Surveys
# ----------------------------------------------------------------------------

@bp.route("/surveys", endpoint="surveys_list")
@permission_required("engagement.surveys.view")
def surveys_list():
    rows = db.query(
        """SELECT s.*,
                  (SELECT COUNT(DISTINCT employee_id) FROM survey_responses r WHERE r.survey_id = s.id) AS response_count
           FROM surveys s ORDER BY s.created_at DESC"""
    )
    return render_template(
        "engagement/surveys_list.html", surveys=rows,
        can_create=has_permission("engagement.surveys.create"),
        can_edit=has_permission("engagement.surveys.edit"),
        statuses=SURVEY_STATUSES,
    )


@bp.route("/surveys/new", methods=("GET", "POST"), endpoint="survey_new")
@permission_required("engagement.surveys.create")
def survey_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        stype = request.form.get("type", "Pulse")
        if stype not in SURVEY_TYPES:
            stype = "Pulse"
        start_date = request.form.get("start_date") or None
        end_date = request.form.get("end_date") or None
        publish_now = bool(request.form.get("publish_now"))
        status = "Active" if publish_now else "Draft"

        question_texts = request.form.getlist("question_text[]")
        question_types = request.form.getlist("question_type[]")
        question_options = request.form.getlist("question_options[]")

        if not title:
            flash("Survey title is required.", "error")
            return render_template("engagement/survey_form.html", question_types=QUESTION_TYPES, survey_types=SURVEY_TYPES)

        new_id = db.execute(
            """INSERT INTO surveys (title, description, type, start_date, end_date, status, created_by)
               VALUES (?,?,?,?,?,?,?)""",
            (title, description, stype, start_date, end_date, status, g.user["id"]),
        )
        rows_to_insert = []
        for i, qtext in enumerate(question_texts):
            qtext = qtext.strip()
            if not qtext:
                continue
            qtype = question_types[i] if i < len(question_types) else "Rating"
            if qtype not in QUESTION_TYPES:
                qtype = "Rating"
            opts = question_options[i].strip() if i < len(question_options) and question_options[i] else None
            rows_to_insert.append((new_id, qtext, qtype, opts))
        if rows_to_insert:
            db.executemany(
                "INSERT INTO survey_questions (survey_id, question_text, question_type, options) VALUES (?,?,?,?)",
                rows_to_insert,
            )
        audit.log("engagement", "surveys", new_id, "create", f"Created survey '{title}' ({len(rows_to_insert)} questions)")
        flash("Survey created.", "success")
        return redirect(url_for("engagement.survey_view", id=new_id))

    return render_template("engagement/survey_form.html", question_types=QUESTION_TYPES, survey_types=SURVEY_TYPES)


@bp.route("/surveys/<int:id>", endpoint="survey_view")
@permission_required("engagement.surveys.view")
def survey_view(id):
    survey = db.query("SELECT * FROM surveys WHERE id=?", (id,), one=True)
    if survey is None:
        flash("Survey not found.", "error")
        return redirect(url_for("engagement.surveys_list"))

    questions = db.query("SELECT * FROM survey_questions WHERE survey_id=? ORDER BY id", (id,))
    view_all = has_permission("engagement.surveys.view_all")
    employee_id = g.employee["id"] if g.employee else None

    has_responded = False
    if employee_id:
        has_responded = db.query(
            "SELECT 1 FROM survey_responses WHERE survey_id=? AND employee_id=? LIMIT 1",
            (id, employee_id), one=True,
        ) is not None

    show_form = survey["status"] == "Active" and employee_id and not has_responded

    if show_form:
        return render_template(
            "engagement/survey_view.html", survey=survey, questions=questions, mode="form",
            can_edit=has_permission("engagement.surveys.edit"), statuses=SURVEY_STATUSES,
        )

    if view_all:
        agg = []
        for q in questions:
            stat = {"question": q}
            if q["question_type"] == "Rating":
                r = db.query(
                    "SELECT AVG(answer_rating) avg_r, COUNT(*) c FROM survey_responses WHERE question_id=?",
                    (q["id"],), one=True,
                )
                stat["avg_rating"] = round(r["avg_r"], 2) if r and r["avg_r"] is not None else None
                stat["count"] = r["c"] if r else 0
                dist = db.query(
                    """SELECT answer_rating AS rating, COUNT(*) c FROM survey_responses
                       WHERE question_id=? GROUP BY answer_rating ORDER BY answer_rating""",
                    (q["id"],),
                )
                stat["distribution"] = [{"label": str(d["rating"]), "value": d["c"]} for d in dist]
            else:
                r = db.query("SELECT COUNT(*) c FROM survey_responses WHERE question_id=?", (q["id"],), one=True)
                stat["count"] = r["c"] if r else 0
                if q["question_type"] == "MultipleChoice":
                    dist = db.query(
                        """SELECT answer_text AS choice, COUNT(*) c FROM survey_responses
                           WHERE question_id=? GROUP BY answer_text""",
                        (q["id"],),
                    )
                    stat["distribution"] = [{"label": d["choice"] or "-", "value": d["c"]} for d in dist]
                else:
                    stat["texts"] = db.query(
                        """SELECT sr.answer_text, e.first_name, e.last_name FROM survey_responses sr
                           JOIN employees e ON e.id = sr.employee_id
                           WHERE sr.question_id=? ORDER BY sr.submitted_at DESC LIMIT 20""",
                        (q["id"],),
                    )
            agg.append(stat)
        return render_template(
            "engagement/survey_view.html", survey=survey, questions=questions, mode="results",
            aggregate=agg, can_edit=has_permission("engagement.surveys.edit"), statuses=SURVEY_STATUSES,
        )

    if has_responded:
        own = db.query(
            """SELECT sr.*, sq.question_text, sq.question_type FROM survey_responses sr
               JOIN survey_questions sq ON sq.id = sr.question_id
               WHERE sr.survey_id=? AND sr.employee_id=? ORDER BY sq.id""",
            (id, employee_id),
        )
        return render_template(
            "engagement/survey_view.html", survey=survey, questions=questions, mode="own",
            own_responses=own, can_edit=has_permission("engagement.surveys.edit"), statuses=SURVEY_STATUSES,
        )

    return render_template(
        "engagement/survey_view.html", survey=survey, questions=questions, mode="none",
        can_edit=has_permission("engagement.surveys.edit"), statuses=SURVEY_STATUSES,
    )


@bp.route("/surveys/<int:id>/respond", methods=("POST",), endpoint="survey_respond")
@permission_required("engagement.surveys.view")
def survey_respond(id):
    survey = db.query("SELECT * FROM surveys WHERE id=?", (id,), one=True)
    if survey is None:
        flash("Survey not found.", "error")
        return redirect(url_for("engagement.surveys_list"))
    if not g.employee:
        flash("No employee profile linked to your account.", "error")
        return redirect(url_for("engagement.survey_view", id=id))
    if survey["status"] != "Active":
        flash("This survey is not currently accepting responses.", "error")
        return redirect(url_for("engagement.survey_view", id=id))

    already = db.query(
        "SELECT 1 FROM survey_responses WHERE survey_id=? AND employee_id=? LIMIT 1",
        (id, g.employee["id"]), one=True,
    )
    if already:
        flash("You have already responded to this survey.", "info")
        return redirect(url_for("engagement.survey_view", id=id))

    questions = db.query("SELECT * FROM survey_questions WHERE survey_id=?", (id,))
    rows_to_insert = []
    for q in questions:
        field = f"answer_{q['id']}"
        val = request.form.get(field, "").strip()
        if not val:
            continue
        if q["question_type"] == "Rating":
            try:
                rating = int(val)
            except ValueError:
                continue
            rows_to_insert.append((id, q["id"], g.employee["id"], None, rating))
        else:
            rows_to_insert.append((id, q["id"], g.employee["id"], val, None))

    if not rows_to_insert:
        flash("Please answer at least one question.", "error")
        return redirect(url_for("engagement.survey_view", id=id))

    db.executemany(
        """INSERT INTO survey_responses (survey_id, question_id, employee_id, answer_text, answer_rating)
           VALUES (?,?,?,?,?)""",
        rows_to_insert,
    )
    audit.log("engagement", "surveys", id, "update", f"Employee #{g.employee['id']} responded to survey '{survey['title']}'")
    flash("Thanks for your response!", "success")
    return redirect(url_for("engagement.survey_view", id=id))


@bp.route("/surveys/<int:id>/status", methods=("POST",), endpoint="survey_status")
@permission_required("engagement.surveys.edit")
def survey_status(id):
    survey = db.query("SELECT * FROM surveys WHERE id=?", (id,), one=True)
    if survey is None:
        flash("Survey not found.", "error")
        return redirect(url_for("engagement.surveys_list"))
    status = request.form.get("status", "")
    if status not in SURVEY_STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("engagement.survey_view", id=id))
    db.execute("UPDATE surveys SET status=? WHERE id=?", (status, id))
    audit.log("engagement", "surveys", id, "update", f"Changed survey '{survey['title']}' status to {status}")
    flash("Survey status updated.", "success")
    return redirect(url_for("engagement.survey_view", id=id))


# ----------------------------------------------------------------------------
# Recognitions
# ----------------------------------------------------------------------------

@bp.route("/recognitions", endpoint="recognitions_list")
@permission_required("engagement.recognitions.view")
def recognitions_list():
    rows = db.query(
        """SELECT r.*, e.first_name, e.last_name, u.full_name AS given_by_name
           FROM recognitions r
           JOIN employees e ON e.id = r.employee_id
           LEFT JOIN users u ON u.id = r.given_by
           ORDER BY r.created_at DESC"""
    )
    return render_template(
        "engagement/recognitions_list.html", recognitions=rows,
        can_create=has_permission("engagement.recognitions.create"),
    )


@bp.route("/recognitions/new", methods=("GET", "POST"), endpoint="recognition_new")
@permission_required("engagement.recognitions.create")
def recognition_new():
    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        category = request.form.get("category", "Kudos")
        if category not in RECOGNITION_CATEGORIES:
            category = "Kudos"
        title = request.form.get("title", "").strip()
        message = request.form.get("message", "").strip() or None
        if not employee_id or not title:
            flash("Employee and title are required.", "error")
            return render_template("engagement/recognition_form.html", employees=_employee_options(),
                                    categories=RECOGNITION_CATEGORIES)
        new_id = db.execute(
            "INSERT INTO recognitions (employee_id, given_by, category, title, message) VALUES (?,?,?,?,?)",
            (employee_id, g.user["id"], category, title, message),
        )
        audit.log("engagement", "recognitions", new_id, "create", f"Gave '{category}' recognition: {title}")
        emp_user = db.query("SELECT id FROM users WHERE employee_id=?", (employee_id,), one=True)
        if emp_user:
            notify.notify_user(
                emp_user["id"], f"You received a {category}!", title,
                ntype="success", link=url_for("engagement.recognitions_list"),
            )
        flash("Recognition posted.", "success")
        return redirect(url_for("engagement.recognitions_list"))
    return render_template("engagement/recognition_form.html", employees=_employee_options(),
                            categories=RECOGNITION_CATEGORIES)
