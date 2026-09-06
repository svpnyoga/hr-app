import os
from flask import Flask, g, redirect, url_for, render_template

import config
import db
import auth
import helpers
from auth import load_logged_in_user
import notify


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SESSION_COOKIE_NAME"] = config.SESSION_COOKIE_NAME
    app.config["PERMANENT_SESSION_LIFETIME"] = config.PERMANENT_SESSION_LIFETIME_MIN * 60
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB uploads

    db.init_app(app)

    app.register_blueprint(auth.bp)

    from blueprints.public import bp as public_bp
    from blueprints.dashboard import bp as dashboard_bp
    from blueprints.employees import bp as employees_bp
    from blueprints.attendance import bp as attendance_bp
    from blueprints.leave import bp as leave_bp
    from blueprints.payroll import bp as payroll_bp
    from blueprints.recruitment import bp as recruitment_bp
    from blueprints.performance import bp as performance_bp
    from blueprints.engagement import bp as engagement_bp
    from blueprints.learning import bp as learning_bp
    from blueprints.field import bp as field_bp
    from blueprints.claims import bp as claims_bp
    from blueprints.documents import bp as documents_bp
    from blueprints.crm import bp as crm_bp
    from blueprints.reports import bp as reports_bp
    from blueprints.notifications import bp as notifications_bp
    from blueprints.search import bp as search_bp
    from blueprints.admin import bp as admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(dashboard_bp, url_prefix="/app")
    app.register_blueprint(employees_bp, url_prefix="/employees")
    app.register_blueprint(attendance_bp, url_prefix="/attendance")
    app.register_blueprint(leave_bp, url_prefix="/leave")
    app.register_blueprint(payroll_bp, url_prefix="/payroll")
    app.register_blueprint(recruitment_bp, url_prefix="/recruitment")
    app.register_blueprint(performance_bp, url_prefix="/performance")
    app.register_blueprint(engagement_bp, url_prefix="/engagement")
    app.register_blueprint(learning_bp, url_prefix="/learning")
    app.register_blueprint(field_bp, url_prefix="/field")
    app.register_blueprint(claims_bp, url_prefix="/claims")
    app.register_blueprint(documents_bp, url_prefix="/documents")
    app.register_blueprint(crm_bp, url_prefix="/crm")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(notifications_bp, url_prefix="/notifications")
    app.register_blueprint(search_bp, url_prefix="/search")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.before_request
    def _before():
        load_logged_in_user()

    @app.context_processor
    def _inject():
        company = None
        unread = 0
        top = []
        pending_approvals = 0
        if g.get("user"):
            company = db.query("SELECT * FROM company_settings WHERE id=1", one=True)
            unread = notify.unread_count(g.user["id"])
            top = db.query(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 6",
                (g.user["id"],),
            )
        return dict(company=company, unread_notifs=unread, top_notifs=top)

    app.jinja_env.filters["money"] = helpers.money
    app.jinja_env.filters["fmt_date"] = helpers.fmt_date
    app.jinja_env.filters["fmt_datetime"] = helpers.fmt_datetime
    app.jinja_env.filters["fmt_time"] = helpers.fmt_time
    app.jinja_env.filters["days_until"] = helpers.days_until
    app.jinja_env.filters["age_years"] = helpers.age_years
    app.jinja_env.filters["initials"] = helpers.initials
    app.jinja_env.globals["status_badge_class"] = helpers.status_badge_class
    app.jinja_env.globals["has_permission"] = auth.has_permission

    @app.route("/")
    def root():
        if g.get("user"):
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("public.landing"))

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.cli.command("init-db")
    def init_db_command():
        db.init_db()
        print("Initialized the database.")

    @app.cli.command("seed")
    def seed_command():
        import seed
        seed.run()
        print("Seeded demo data.")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
