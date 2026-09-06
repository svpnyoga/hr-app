"""Learning & Development (LMS) module.

Tables: courses, training_sessions, training_enrollments, skill_matrix.
Bespoke blueprint (not generic CRUD) because courses/sessions/enrollments are
nested workflows with roster management and self-service enrollment.
"""
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

import db
import audit
import notify
from auth import permission_required, has_permission
from helpers import paginate_args, today_iso, now_iso

bp = Blueprint("learning", __name__)

DELIVERY_MODES = ["Online", "Classroom", "Blended", "Self-paced"]
ATTENDANCE_STATUSES = ["Enrolled", "Attended", "Completed", "No Show", "Cancelled"]
PROFICIENCY_LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

@bp.route("/courses")
@permission_required("learning.courses.view")
def courses_list():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    page, per_page = paginate_args(request)

    where = []
    args = []
    if q:
        where.append("(c.title LIKE ? OR c.trainer_name LIKE ? OR c.course_code LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if category:
        where.append("c.category = ?")
        args.append(category)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = db.query(f"SELECT COUNT(*) c FROM courses c {where_sql}", args, one=True)["c"]
    offset = (page - 1) * per_page
    rows = db.query(
        f"""SELECT c.*, (SELECT COUNT(*) FROM training_sessions ts WHERE ts.course_id = c.id) AS session_count
            FROM courses c {where_sql}
            ORDER BY c.title LIMIT ? OFFSET ?""",
        args + [per_page, offset],
    )
    pages = max(1, -(-total // per_page))
    categories = db.query("SELECT DISTINCT category FROM courses WHERE category IS NOT NULL AND category != '' ORDER BY category")

    return render_template(
        "learning/courses_list.html",
        rows=rows, q=q, category=category, categories=categories,
        page=page, pages=pages, total=total, per_page=per_page,
        can_create=has_permission("learning.courses.create"),
    )


@bp.route("/courses/new", methods=("GET", "POST"))
@permission_required("learning.courses.create")
def course_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.", "error")
            return render_template("learning/course_form.html", row=None, modes=DELIVERY_MODES)
        course_code = db.next_sequence("COURSE", "CRS", 4)
        new_id = db.execute(
            """INSERT INTO courses (course_code, title, description, category, duration_hours,
                                     trainer_name, delivery_mode, is_active)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                course_code,
                title,
                request.form.get("description", "").strip() or None,
                request.form.get("category", "").strip() or None,
                float(request.form.get("duration_hours") or 1),
                request.form.get("trainer_name", "").strip() or None,
                request.form.get("delivery_mode") or "Online",
                1 if request.form.get("is_active") else 0,
            ),
        )
        audit.log("learning", "courses", new_id, "create", f"Created course {course_code} - {title}")
        flash(f"Course {course_code} created successfully.", "success")
        return redirect(url_for("learning.course_view", id=new_id))
    return render_template("learning/course_form.html", row=None, modes=DELIVERY_MODES)


@bp.route("/courses/<int:id>")
@permission_required("learning.courses.view")
def course_view(id):
    course = db.query("SELECT * FROM courses WHERE id=?", (id,), one=True)
    if course is None:
        flash("Course not found.", "error")
        return redirect(url_for("learning.courses_list"))
    sessions = db.query(
        """SELECT ts.*, l.name AS location_name,
                  (SELECT COUNT(*) FROM training_enrollments te WHERE te.session_id = ts.id) AS enrolled_count
           FROM training_sessions ts
           LEFT JOIN locations l ON l.id = ts.location_id
           WHERE ts.course_id = ?
           ORDER BY ts.session_date DESC""",
        (id,),
    )
    return render_template(
        "learning/course_view.html", course=course, sessions=sessions,
        can_edit=has_permission("learning.courses.edit"),
        can_schedule=has_permission("learning.sessions.create"),
    )


@bp.route("/courses/<int:id>/edit", methods=("GET", "POST"))
@permission_required("learning.courses.edit")
def course_edit(id):
    course = db.query("SELECT * FROM courses WHERE id=?", (id,), one=True)
    if course is None:
        flash("Course not found.", "error")
        return redirect(url_for("learning.courses_list"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.", "error")
            return render_template("learning/course_form.html", row=course, modes=DELIVERY_MODES)
        db.execute(
            """UPDATE courses SET title=?, description=?, category=?, duration_hours=?,
                                   trainer_name=?, delivery_mode=?, is_active=? WHERE id=?""",
            (
                title,
                request.form.get("description", "").strip() or None,
                request.form.get("category", "").strip() or None,
                float(request.form.get("duration_hours") or 1),
                request.form.get("trainer_name", "").strip() or None,
                request.form.get("delivery_mode") or "Online",
                1 if request.form.get("is_active") else 0,
                id,
            ),
        )
        audit.log("learning", "courses", id, "update", f"Updated course #{id}")
        flash("Course updated successfully.", "success")
        return redirect(url_for("learning.course_view", id=id))
    return render_template("learning/course_form.html", row=course, modes=DELIVERY_MODES)


# ---------------------------------------------------------------------------
# Training sessions
# ---------------------------------------------------------------------------

@bp.route("/courses/<int:course_id>/sessions/new", methods=("GET", "POST"))
@permission_required("learning.sessions.create")
def session_new(course_id):
    course = db.query("SELECT * FROM courses WHERE id=?", (course_id,), one=True)
    if course is None:
        flash("Course not found.", "error")
        return redirect(url_for("learning.courses_list"))
    locations = db.query("SELECT * FROM locations WHERE is_active=1 ORDER BY name")
    if request.method == "POST":
        session_date = request.form.get("session_date", "").strip()
        if not session_date:
            flash("Session date is required.", "error")
            return render_template("learning/session_form.html", course=course, locations=locations)
        new_id = db.execute(
            """INSERT INTO training_sessions (course_id, session_date, start_time, end_time,
                                                location_id, trainer_name, capacity, status)
               VALUES (?,?,?,?,?,?,?,'Scheduled')""",
            (
                course_id,
                session_date,
                request.form.get("start_time") or None,
                request.form.get("end_time") or None,
                request.form.get("location_id", type=int) or None,
                request.form.get("trainer_name", "").strip() or course["trainer_name"],
                request.form.get("capacity", type=int) or 20,
            ),
        )
        audit.log("learning", "sessions", new_id, "create", f"Scheduled session for course #{course_id} on {session_date}")
        flash("Training session scheduled.", "success")
        return redirect(url_for("learning.session_view", id=new_id))
    return render_template("learning/session_form.html", course=course, locations=locations)


@bp.route("/sessions/<int:id>")
@permission_required("learning.sessions.view")
def session_view(id):
    session_row = db.query(
        """SELECT ts.*, l.name AS location_name, c.title AS course_title, c.id AS course_id, c.course_code
           FROM training_sessions ts
           JOIN courses c ON c.id = ts.course_id
           LEFT JOIN locations l ON l.id = ts.location_id
           WHERE ts.id=?""",
        (id,), one=True,
    )
    if session_row is None:
        flash("Training session not found.", "error")
        return redirect(url_for("learning.courses_list"))
    roster = db.query(
        """SELECT te.*, e.first_name, e.last_name, e.employee_code
           FROM training_enrollments te
           JOIN employees e ON e.id = te.employee_id
           WHERE te.session_id = ?
           ORDER BY te.enrollment_date""",
        (id,),
    )
    enrolled_ids = {r["employee_id"] for r in roster}
    under_capacity = len(roster) < session_row["capacity"]

    can_enroll_self = (
        g.employee is not None
        and has_permission("learning.enrollments.create")
        and g.employee["id"] not in enrolled_ids
        and under_capacity
    )
    can_enroll_others = has_permission("learning.enrollments.edit") and under_capacity
    employees = []
    if can_enroll_others:
        employees = db.query(
            "SELECT id, employee_code, first_name, last_name FROM employees WHERE is_deleted=0 ORDER BY first_name, last_name"
        )

    return render_template(
        "learning/session_view.html",
        session=session_row, roster=roster, under_capacity=under_capacity,
        can_enroll_self=can_enroll_self, can_enroll_others=can_enroll_others, employees=employees,
        can_update_enrollment=has_permission("learning.enrollments.edit"),
        attendance_statuses=ATTENDANCE_STATUSES,
    )


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------

@bp.route("/sessions/<int:session_id>/enroll", methods=("POST",))
def enroll(session_id):
    session_row = db.query("SELECT * FROM training_sessions WHERE id=?", (session_id,), one=True)
    if session_row is None:
        flash("Training session not found.", "error")
        return redirect(url_for("learning.courses_list"))

    employee_id = request.form.get("employee_id", type=int)
    if not employee_id:
        if not has_permission("learning.enrollments.create"):
            flash("You don't have permission to enroll in this session.", "error")
            return redirect(url_for("learning.session_view", id=session_id))
        if g.employee is None:
            flash("Your account is not linked to an employee record.", "error")
            return redirect(url_for("learning.session_view", id=session_id))
        employee_id = g.employee["id"]
        self_enroll = True
    else:
        if not has_permission("learning.enrollments.edit"):
            flash("You don't have permission to enroll other employees.", "error")
            return redirect(url_for("learning.session_view", id=session_id))
        self_enroll = False

    enrolled_count = db.query(
        "SELECT COUNT(*) c FROM training_enrollments WHERE session_id=?", (session_id,), one=True
    )["c"]
    if enrolled_count >= session_row["capacity"]:
        flash("This session is at full capacity.", "error")
        return redirect(url_for("learning.session_view", id=session_id))

    try:
        new_id = db.execute(
            """INSERT INTO training_enrollments (session_id, employee_id, enrollment_date, attendance_status)
               VALUES (?,?,?,'Enrolled')""",
            (session_id, employee_id, today_iso()),
        )
    except sqlite3.IntegrityError:
        flash("This employee is already enrolled in this session.", "info")
        return redirect(url_for("learning.session_view", id=session_id))

    audit.log("learning", "enrollments", new_id, "create", f"Enrolled employee #{employee_id} in session #{session_id}")
    if not self_enroll:
        user_row = db.query("SELECT id FROM users WHERE employee_id=?", (employee_id,), one=True)
        if user_row:
            notify.notify_user(
                user_row["id"], "Training enrollment",
                "You have been enrolled in a training session.", "info",
                url_for("learning.session_view", id=session_id),
            )
    flash("Enrolled successfully.", "success")
    return redirect(url_for("learning.session_view", id=session_id))


@bp.route("/enrollments/<int:id>/update", methods=("POST",))
@permission_required("learning.enrollments.edit")
def enrollment_update(id):
    enrollment = db.query("SELECT * FROM training_enrollments WHERE id=?", (id,), one=True)
    if enrollment is None:
        flash("Enrollment not found.", "error")
        return redirect(url_for("learning.courses_list"))

    attendance_status = request.form.get("attendance_status") or enrollment["attendance_status"]
    assessment_score = request.form.get("assessment_score", "").strip()
    feedback_rating = request.form.get("feedback_rating", "").strip()
    certificate_issued = 1 if request.form.get("certificate_issued") else 0

    db.execute(
        """UPDATE training_enrollments
           SET attendance_status=?, assessment_score=?, certificate_issued=?, feedback_rating=?
           WHERE id=?""",
        (
            attendance_status,
            float(assessment_score) if assessment_score else None,
            certificate_issued,
            int(feedback_rating) if feedback_rating else None,
            id,
        ),
    )
    audit.log("learning", "enrollments", id, "update", f"Updated enrollment #{id} status to {attendance_status}")
    flash("Enrollment updated.", "success")
    return redirect(url_for("learning.session_view", id=enrollment["session_id"]))


# ---------------------------------------------------------------------------
# Self-service
# ---------------------------------------------------------------------------

@bp.route("/my-learning")
@permission_required("learning.enrollments.view")
def my_learning():
    if g.employee is None:
        flash("Your account is not linked to an employee record.", "error")
        return redirect(url_for("dashboard.index"))
    rows = db.query(
        """SELECT te.*, ts.session_date, ts.start_time, ts.status AS session_status,
                  c.title AS course_title, c.category, c.id AS course_id
           FROM training_enrollments te
           JOIN training_sessions ts ON ts.id = te.session_id
           JOIN courses c ON c.id = ts.course_id
           WHERE te.employee_id = ?
           ORDER BY ts.session_date DESC""",
        (g.employee["id"],),
    )
    return render_template("learning/my_learning.html", rows=rows)


# ---------------------------------------------------------------------------
# Skill matrix
# ---------------------------------------------------------------------------

@bp.route("/skills")
@permission_required("learning.skills.view")
def skills_list():
    employee_id = request.args.get("employee_id", type=int)
    view_all = has_permission("learning.skills.view_all")
    if not view_all:
        employee_id = g.employee["id"] if g.employee else -1

    where = ""
    args = []
    if employee_id:
        where = "WHERE sm.employee_id = ?"
        args = [employee_id]

    rows = db.query(
        f"""SELECT sm.*, e.first_name, e.last_name, e.employee_code
            FROM skill_matrix sm
            JOIN employees e ON e.id = sm.employee_id
            {where}
            ORDER BY sm.assessed_date DESC""",
        args,
    )
    employee = None
    if employee_id:
        employee = db.query("SELECT * FROM employees WHERE id=?", (employee_id,), one=True)
    employees = []
    if view_all:
        employees = db.query("SELECT id, employee_code, first_name, last_name FROM employees WHERE is_deleted=0 ORDER BY first_name, last_name")

    return render_template(
        "learning/skills_list.html",
        rows=rows, employee=employee, employee_id=employee_id, employees=employees,
        view_all=view_all, proficiency_levels=PROFICIENCY_LEVELS,
        can_add=has_permission("learning.skills.create"),
    )


@bp.route("/skills/add", methods=("POST",))
@permission_required("learning.skills.create")
def skill_add():
    employee_id = request.form.get("employee_id", type=int) or (g.employee["id"] if g.employee else None)
    skill_name = request.form.get("skill_name", "").strip()
    if not employee_id or not skill_name:
        flash("Employee and skill name are required.", "error")
        return redirect(url_for("learning.skills_list"))

    new_id = db.execute(
        """INSERT INTO skill_matrix (employee_id, skill_name, proficiency_level, assessed_date)
           VALUES (?,?,?,?)""",
        (
            employee_id,
            skill_name,
            request.form.get("proficiency_level") or "Beginner",
            today_iso(),
        ),
    )
    audit.log("learning", "skills", new_id, "create", f"Added skill '{skill_name}' for employee #{employee_id}")
    flash("Skill added.", "success")
    return redirect(url_for("learning.skills_list", employee_id=employee_id))
